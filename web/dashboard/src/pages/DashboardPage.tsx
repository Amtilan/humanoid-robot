import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import {
  useEventStream,
  useEventSubscription,
  type EventEnvelope,
} from "../lib/eventStream";

const MAX_TAPE = 30;

export function DashboardPage() {
  const infoQuery = useQuery({ queryKey: ["info"], queryFn: api.info });
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 5_000,
  });
  const groupsQuery = useQuery({ queryKey: ["groups"], queryFn: api.adapterGroups });

  const { connected } = useEventStream();
  const [tape, setTape] = useState<EventEnvelope[]>([]);
  useEventSubscription(">", (envelope) => {
    setTape((prev) => [envelope, ...prev].slice(0, MAX_TAPE));
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Live status of the humanoid-robot platform.
          </p>
        </div>
        <span
          className={
            connected
              ? "inline-flex items-center gap-1.5 text-xs text-emerald-400"
              : "inline-flex items-center gap-1.5 text-xs text-yellow-400"
          }
        >
          <span
            className={
              connected
                ? "inline-block h-2 w-2 rounded-full bg-emerald-500"
                : "inline-block h-2 w-2 animate-pulse rounded-full bg-yellow-500"
            }
          />
          bus {connected ? "connected" : "reconnecting"}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card title="Service">
          {infoQuery.isPending ? (
            <Placeholder />
          ) : infoQuery.error ? (
            <ErrorBox message={String(infoQuery.error)} />
          ) : (
            <dl className="space-y-1 text-sm">
              <Row label="Service" value={infoQuery.data.service} />
              <Row label="Version" value={infoQuery.data.version} />
              <Row label="Environment" value={infoQuery.data.environment} />
            </dl>
          )}
        </Card>

        <Card title="Health">
          {healthQuery.isPending ? (
            <Placeholder />
          ) : healthQuery.error ? (
            <ErrorBox message={String(healthQuery.error)} />
          ) : (
            <div className="flex items-center gap-2 text-sm">
              <span
                className={
                  healthQuery.data.status === "ready"
                    ? "inline-block h-2 w-2 rounded-full bg-emerald-500"
                    : "inline-block h-2 w-2 rounded-full bg-red-500"
                }
              />
              <span>{healthQuery.data.status}</span>
            </div>
          )}
        </Card>

        <Card title="Registered adapter groups">
          {groupsQuery.isPending ? (
            <Placeholder />
          ) : groupsQuery.error ? (
            <ErrorBox message={String(groupsQuery.error)} />
          ) : (
            <p className="text-sm text-muted-foreground">
              {groupsQuery.data.groups.length} groups
            </p>
          )}
        </Card>
      </div>

      <Card title={`Live tape (${tape.length})`}>
        {tape.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Waiting for the first event on the bus…
          </p>
        ) : (
          <ul className="max-h-64 space-y-1 overflow-auto pr-1">
            {tape.map((event) => (
              <li
                key={event.event_id}
                className="flex items-center gap-3 rounded border border-border/40 bg-background/60 px-2 py-1 text-xs"
              >
                <span className="font-mono text-[10px] text-muted-foreground">
                  {event.occurred_at.substring(11, 19)}
                </span>
                <span className="font-medium">{event.subject}</span>
                <span className="text-muted-foreground">{event.producer}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-4">
      <h2 className="pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function Placeholder() {
  return <div className="h-4 w-full animate-pulse rounded bg-muted" />;
}

function ErrorBox({ message }: { message: string }) {
  return <p className="text-sm text-red-500">{message}</p>;
}
