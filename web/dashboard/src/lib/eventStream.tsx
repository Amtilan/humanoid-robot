import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { api, getAuthToken } from "../api/client";

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
      // Browsers cannot set custom headers on WebSocket connections, so the
      // token rides as a `?token=` query arg (cortex-core accepts either).
      const token = getAuthToken();
      const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
      const url = `${proto}://${location.host}/api/v1/events/ws?subject=>${tokenParam}`;
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

/**
 * Replay the robot-side persisted event tail (oldest-first) through
 * `handler` once on mount — pages seed their state before live WS events
 * arrive, so a refresh no longer starts from blank. Dedup against live
 * events by `event_id` is the caller's responsibility (envelopes carry it).
 */
export function useEventHistory(
  filter: string | ((subject: string) => boolean),
  handler: Listener,
  limit = 500,
): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const filterRef = useRef(filter);
  filterRef.current = filter;

  useEffect(() => {
    let cancelled = false;
    api
      .eventsHistory(limit)
      .then(({ records }) => {
        if (cancelled) return;
        const f = filterRef.current;
        const match =
          typeof f === "string" ? (s: string) => matchSubject(f, s) : f;
        for (const envelope of records) {
          if (match(envelope.subject)) {
            try {
              handlerRef.current(envelope);
            } catch (err) {
              console.error("history replay failed", err);
            }
          }
        }
      })
      .catch(() => {
        // History endpoint unavailable — live-only view still works.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit]);
}

function matchSubject(pattern: string, subject: string): boolean {
  if (pattern === ">" || pattern === "" || pattern === "*") return true;
  if (pattern.endsWith(".>")) {
    return subject.startsWith(pattern.slice(0, -2));
  }
  return subject === pattern;
}
