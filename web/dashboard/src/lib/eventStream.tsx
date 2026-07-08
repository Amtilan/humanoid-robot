import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export interface EventEnvelope {
  subject: string;
  event_id: string;
  occurred_at: string;
  correlation_id: string;
  producer: string;
  data: Record<string, unknown>;
}

type Listener = (envelope: EventEnvelope) => void;

interface EventStreamContextValue {
  connected: boolean;
  subscribe: (listener: Listener) => () => void;
}

const EventStreamContext = createContext<EventStreamContextValue | null>(null);

const RECONNECT_DELAY_MS = 2_000;
const MAX_RECONNECT_DELAY_MS = 30_000;

export function EventStreamProvider({ children }: { children: React.ReactNode }) {
  const [connected, setConnected] = useState(false);
  const listenersRef = useRef(new Set<Listener>());
  const socketRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(RECONNECT_DELAY_MS);
  const closedRef = useRef(false);

  useEffect(() => {
    closedRef.current = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const url = `${proto}://${location.host}/api/v1/events/ws?subject=>`;
      const ws = new WebSocket(url);
      socketRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        backoffRef.current = RECONNECT_DELAY_MS;
      };
      ws.onmessage = (msg) => {
        let envelope: EventEnvelope;
        try {
          envelope = JSON.parse(msg.data) as EventEnvelope;
        } catch {
          return;
        }
        for (const listener of listenersRef.current) {
          try {
            listener(envelope);
          } catch (err) {
            console.error("event listener failed", err);
          }
        }
      };
      const scheduleReconnect = () => {
        setConnected(false);
        if (closedRef.current) return;
        window.setTimeout(connect, backoffRef.current);
        backoffRef.current = Math.min(
          backoffRef.current * 2,
          MAX_RECONNECT_DELAY_MS,
        );
      };
      ws.onclose = scheduleReconnect;
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closedRef.current = true;
      socketRef.current?.close();
    };
  }, []);

  const subscribe = useCallback((listener: Listener) => {
    listenersRef.current.add(listener);
    return () => {
      listenersRef.current.delete(listener);
    };
  }, []);

  const value = useMemo(
    () => ({ connected, subscribe }),
    [connected, subscribe],
  );
  return (
    <EventStreamContext.Provider value={value}>
      {children}
    </EventStreamContext.Provider>
  );
}

export function useEventStream(): EventStreamContextValue {
  const ctx = useContext(EventStreamContext);
  if (!ctx) {
    throw new Error("useEventStream must be used within EventStreamProvider");
  }
  return ctx;
}

export function useEventSubscription(
  filter: string | ((subject: string) => boolean),
  handler: Listener,
): void {
  const { subscribe } = useEventStream();
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const match =
      typeof filter === "string"
        ? (subject: string) => matchSubject(filter, subject)
        : filter;
    return subscribe((envelope) => {
      if (match(envelope.subject)) handlerRef.current(envelope);
    });
  }, [subscribe, filter]);
}

function matchSubject(pattern: string, subject: string): boolean {
  if (pattern === ">" || pattern === "" || pattern === "*") return true;
  if (pattern.endsWith(".>")) {
    return subject.startsWith(pattern.slice(0, -2));
  }
  return subject === pattern;
}
