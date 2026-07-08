import { useMemo, useState } from "react";

import {
  useEventStream,
  useEventSubscription,
  type EventEnvelope,
} from "../lib/eventStream";

const MAX_EVENTS = 200;

export function EventsPage() {
  const [pattern, setPattern] = useState(">");
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const { connected } = useEventStream();

  useEventSubscription(pattern, (envelope) => {
    setEvents((prev) => [envelope, ...prev].slice(0, MAX_EVENTS));
  });

  const stats = useMemo(() => {
    const counts = new Map<string, number>();
    for (const ev of events) counts.set(ev.subject, (counts.get(ev.subject) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [events]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Events</h1>
        <p className="text-sm text-muted-foreground">
          Live tail of the platform event bus. Read-only.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <label className="text-sm text-muted-foreground">Subject filter</label>
        <input
          type="text"
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          placeholder="e.g. asr.>"
          className="w-64 rounded-md border border-border bg-background/40 px-3 py-1 text-sm"
        />
        <ConnectionBadge connected={connected} />
        <button
          type="button"
          onClick={() => setEvents([])}
          className="ml-auto rounded-md border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          clear
        </button>
      </div>

      {stats.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {stats.map(([subject, count]) => (
            <span
              key={subject}
              className="rounded-full border border-border bg-background/40 px-2 py-0.5"
            >
              <span className="font-mono text-muted-foreground">{subject}</span>
              <span className="ml-1 text-primary">×{count}</span>
            </span>
          ))}
        </div>
      )}

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

function ConnectionBadge({ connected }: { connected: boolean }) {
  return (
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
            : "inline-block h-2 w-2 animate-pulse rounded-full bg-yellow-500"
        }
      />
      {connected ? "connected" : "reconnecting"}
    </span>
  );
}
