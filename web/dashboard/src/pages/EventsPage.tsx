import { useEffect, useRef, useState } from "react";

interface EventEnvelope {
  subject: string;
  event_id: string;
  occurred_at: string;
  correlation_id: string;
  producer: string;
  data: Record<string, unknown>;
}

const MAX_EVENTS = 200;

export function EventsPage() {
  const [subject, setSubject] = useState(">");
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/api/v1/events/ws?subject=${encodeURIComponent(subject)}`;
    const ws = new WebSocket(url);
    socketRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (msg) => {
      try {
        const envelope = JSON.parse(msg.data) as EventEnvelope;
        setEvents((prev) => [envelope, ...prev].slice(0, MAX_EVENTS));
      } catch {
        // ignore malformed
      }
    };
    return () => ws.close();
  }, [subject]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Events</h1>
        <p className="text-sm text-muted-foreground">
          Live tail of the platform event bus. Read-only.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <label className="text-sm text-muted-foreground">Subject</label>
        <input
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="e.g. asr.>"
          className="w-64 rounded-md border border-border bg-background/40 px-3 py-1 text-sm"
        />
        <span
          className={
            connected
              ? "inline-flex items-center gap-1.5 text-xs text-emerald-400"
              : "inline-flex items-center gap-1.5 text-xs text-muted-foreground"
          }
        >
          <span
            className={
              connected
                ? "inline-block h-2 w-2 rounded-full bg-emerald-500"
                : "inline-block h-2 w-2 rounded-full bg-muted-foreground"
            }
          />
          {connected ? "connected" : "reconnecting"}
        </span>
      </div>

      <div className="rounded-lg border border-border bg-background/40">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-border text-muted-foreground">
            <tr>
              <th className="px-4 py-2">Time</th>
              <th className="px-4 py-2">Subject</th>
              <th className="px-4 py-2">Producer</th>
              <th className="px-4 py-2">Payload</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td className="px-4 py-3 text-muted-foreground" colSpan={4}>
                  Waiting for events…
                </td>
              </tr>
            ) : (
              events.map((event) => (
                <tr key={event.event_id} className="border-b border-border/50 last:border-none">
                  <td className="whitespace-nowrap px-4 py-2 font-mono text-[10px]">
                    {event.occurred_at.substring(11, 19)}
                  </td>
                  <td className="px-4 py-2 font-medium">{event.subject}</td>
                  <td className="px-4 py-2 text-muted-foreground">{event.producer}</td>
                  <td className="px-4 py-2 font-mono text-[10px] text-muted-foreground">
                    {JSON.stringify(event.data)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
