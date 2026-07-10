import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type RobotManifestSnapshot } from "../api/client";
import {
  useEventSubscription,
  type EventEnvelope,
} from "../lib/eventStream";
import { useToast } from "../lib/toast";

const MAX_FEED = 40;

export function RobotPage() {
  const manifestsQuery = useQuery({
    queryKey: ["robot", "manifests"],
    queryFn: api.robotManifests,
    refetchInterval: 5_000,
  });
  const [feed, setFeed] = useState<EventEnvelope[]>([]);
  useEventSubscription("robot.>", (envelope) => {
    setFeed((prev) => [envelope, ...prev].slice(0, MAX_FEED));
  });

  const { push } = useToast();
  const command = useMutation({
    mutationFn: (body: { capability: string; payload: Record<string, unknown> }) =>
      api.robotCommand(body),
    onSuccess: (ack) =>
      push({ kind: "info", title: "Command dispatched", description: ack.command_id }),
    onError: (err) =>
      push({ kind: "error", title: "Command failed", description: String(err) }),
  });

  const sendMove = (
    linear_x_mps: number,
    angular_z_rps: number,
    duration_ms: number,
  ) =>
    command.mutate({
      capability: "locomotion.move",
      payload: { linear_x_mps, linear_y_mps: 0, angular_z_rps, duration_ms },
    });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Robot</h1>
        <p className="text-sm text-muted-foreground">
          Latest manifest reported by each adapter on the bus.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-background/40 p-4">
        <h2 className="pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Command tester
        </h2>
        <p className="pb-3 text-xs text-muted-foreground">
          Publishes <code>robot.command.requested</code>. The safety gate
          decides whether it becomes <code>safety.command.forwarded</code>.
          Release E-STOP first if commands are being denied.
        </p>
        <div className="flex flex-wrap gap-2">
          <CmdButton
            label="↑ walk 0.3 m/s"
            onClick={() => sendMove(0.3, 0, 800)}
            disabled={command.isPending}
          />
          <CmdButton
            label="↓ back 0.3 m/s"
            onClick={() => sendMove(-0.3, 0, 800)}
            disabled={command.isPending}
          />
          <CmdButton
            label="↻ turn +0.5 rad/s"
            onClick={() => sendMove(0, 0.5, 600)}
            disabled={command.isPending}
          />
          <CmdButton
            label="⚠ 2 m/s (should deny)"
            onClick={() => sendMove(2.0, 0, 500)}
            disabled={command.isPending}
            variant="warning"
          />
          <CmdButton
            label="■ stop"
            onClick={() =>
              command.mutate({ capability: "locomotion.stop", payload: {} })
            }
            disabled={command.isPending}
            variant="danger"
          />
        </div>
      </div>

      {manifestsQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : manifestsQuery.error ? (
        <p className="text-sm text-red-500">{String(manifestsQuery.error)}</p>
      ) : manifestsQuery.data.length === 0 ? (
        <div className="rounded-lg border border-border bg-background/40 p-6 text-sm text-muted-foreground">
          No robot adapter has reported a manifest yet. Start
          <code className="mx-1 rounded bg-muted px-1">cortex-robot-adapter</code>
          to populate this view.
        </div>
      ) : (
        <div className="space-y-4">
          {manifestsQuery.data.map((snapshot) => (
            <ManifestCard key={snapshot.adapter_name} snapshot={snapshot} />
          ))}
        </div>
      )}

      <div className="rounded-lg border border-border bg-background/40 p-4">
        <h2 className="pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Live robot feed ({feed.length})
        </h2>
        {feed.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Subscribed to <code>robot.&gt;</code>. Waiting for commands / telemetry…
          </p>
        ) : (
          <ul className="max-h-64 space-y-1 overflow-auto pr-1">
            {feed.map((event) => (
              <li
                key={event.event_id}
                className="flex items-center gap-3 rounded border border-border/40 bg-background/60 px-2 py-1 text-xs"
              >
                <span className="font-mono text-[10px] text-muted-foreground">
                  {event.occurred_at.substring(11, 19)}
                </span>
                <span className="font-medium">{event.subject}</span>
                <span className="truncate text-muted-foreground">
                  {JSON.stringify(event.data).slice(0, 120)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ManifestCard({ snapshot }: { snapshot: RobotManifestSnapshot }) {
  const { manifest } = snapshot;
  return (
    <div className="rounded-lg border border-border bg-background/40 p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            {manifest.robot_model.vendor} {manifest.robot_model.family}{" "}
            {manifest.robot_model.variant}
          </h2>
          <p className="text-xs text-muted-foreground">
            adapter <code>{snapshot.adapter_name}</code>@{snapshot.adapter_version}
          </p>
        </div>
        <div className="text-xs text-muted-foreground">
          observed {new Date(snapshot.observed_at).toLocaleTimeString()}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-4 text-xs md:grid-cols-4">
        <Info label="transport" value={manifest.transport_hint ?? "—"} />
        <Info label="interface" value={manifest.network_interface ?? "—"} />
      </div>

      <pre className="mt-4 max-h-64 overflow-auto rounded bg-background/60 p-3 font-mono text-[10px] text-muted-foreground">
        {JSON.stringify(manifest.capabilities, null, 2)}
      </pre>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

function CmdButton({
  label,
  onClick,
  disabled,
  variant = "default",
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  variant?: "default" | "danger" | "warning";
}) {
  const base =
    "rounded-md border px-3 py-1.5 text-sm font-medium disabled:opacity-40";
  const style =
    variant === "danger"
      ? "border-red-500/50 bg-red-500/10 text-red-300 hover:bg-red-500/20"
      : variant === "warning"
        ? "border-yellow-500/50 bg-yellow-500/10 text-yellow-300 hover:bg-yellow-500/20"
        : "border-border bg-background/60 hover:bg-accent hover:text-accent-foreground";
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={`${base} ${style}`}>
      {label}
    </button>
  );
}
