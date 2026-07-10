import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  api,
  type RobotManifestSnapshot,
  type RobotTelemetrySample,
} from "../api/client";
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

  const client = useQueryClient();
  const telemetryQuery = useQuery({
    queryKey: ["robot", "telemetry"],
    queryFn: api.robotTelemetry,
    refetchInterval: 15_000,
  });
  useEventSubscription("robot.telemetry", (envelope) => {
    const kind = envelope.data.kind;
    const payload = envelope.data.payload;
    if (typeof kind !== "string" || typeof payload !== "object" || payload === null) return;
    const sample: RobotTelemetrySample = {
      kind,
      payload: payload as Record<string, unknown>,
      observed_at: envelope.occurred_at,
      producer: envelope.producer,
    };
    client.setQueryData<RobotTelemetrySample[]>(["robot", "telemetry"], (prev) => {
      const others = (prev ?? []).filter((s) => s.kind !== sample.kind);
      return [...others, sample];
    });
  });
  const battery = telemetryQuery.data?.find((s) => s.kind === "battery");
  const batteryPct =
    battery && typeof battery.payload.percentage === "number"
      ? (battery.payload.percentage as number)
      : null;
  const temperature = telemetryQuery.data?.find((s) => s.kind === "temperature");
  const tempMax =
    temperature && typeof temperature.payload === "object" && temperature.payload !== null
      ? Math.max(
          ...Object.values(temperature.payload as Record<string, unknown>).filter(
            (v): v is number => typeof v === "number",
          ),
          0,
        )
      : null;
  const imu = telemetryQuery.data?.find((s) => s.kind === "imu");
  const imuPitch =
    imu && typeof imu.payload.pitch_rad === "number"
      ? (imu.payload.pitch_rad as number)
      : null;
  const imuRoll =
    imu && typeof imu.payload.roll_rad === "number"
      ? (imu.payload.roll_rad as number)
      : null;

  const { push } = useToast();
  const [submitter, setSubmitter] = useState("operator");
  const command = useMutation({
    mutationFn: (body: {
      capability: string;
      payload: Record<string, unknown>;
      submitter: string;
    }) => api.robotCommand(body),
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
      submitter,
    });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Robot</h1>
          <p className="text-sm text-muted-foreground">
            Latest manifest reported by each adapter on the bus.
          </p>
        </div>
        <div className="flex items-start gap-3">
          {tempMax !== null && tempMax > 0 && <TemperatureBadge celsius={tempMax} />}
          {(imuPitch !== null || imuRoll !== null) && (
            <ImuBadge pitchRad={imuPitch} rollRad={imuRoll} />
          )}
          {batteryPct !== null && <BatteryBadge percentage={batteryPct} />}
        </div>
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
        <div className="flex items-center gap-2 pb-3">
          <label className="text-xs uppercase text-muted-foreground">
            Submitter
          </label>
          <select
            value={submitter}
            onChange={(e) => setSubmitter(e.target.value)}
            className="rounded-md border border-border bg-background/60 px-2 py-1 text-xs"
          >
            <option value="operator">operator</option>
            <option value="llm">llm</option>
            <option value="plugin">plugin</option>
            <option value="test">test</option>
          </select>
        </div>
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
            label="👋 wave"
            onClick={() =>
              command.mutate({
                capability: "arms.gesture",
                payload: { gesture: "high wave" },
                submitter,
              })
            }
            disabled={command.isPending}
          />
          <CmdButton
            label="↓ release arm"
            onClick={() =>
              command.mutate({
                capability: "arms.gesture",
                payload: { gesture: "release arm" },
                submitter,
              })
            }
            disabled={command.isPending}
          />
          <CmdButton
            label="← head yaw −0.4"
            onClick={() =>
              command.mutate({
                capability: "head.pose",
                payload: { pitch_rad: 0, yaw_rad: -0.4, duration_ms: 400 },
                submitter,
              })
            }
            disabled={command.isPending}
          />
          <CmdButton
            label="→ head yaw +0.4"
            onClick={() =>
              command.mutate({
                capability: "head.pose",
                payload: { pitch_rad: 0, yaw_rad: 0.4, duration_ms: 400 },
                submitter,
              })
            }
            disabled={command.isPending}
          />
          <CmdButton
            label="⌂ head reset"
            onClick={() =>
              command.mutate({
                capability: "head.reset",
                payload: {},
                submitter,
              })
            }
            disabled={command.isPending}
          />
          <CmdButton
            label="■ stop"
            onClick={() =>
              command.mutate({
                capability: "locomotion.stop",
                payload: {},
                submitter,
              })
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

function TemperatureBadge({ celsius }: { celsius: number }) {
  const style =
    celsius >= 85
      ? "border-red-500/50 bg-red-500/10 text-red-300"
      : celsius >= 70
        ? "border-yellow-500/50 bg-yellow-500/10 text-yellow-300"
        : "border-emerald-500/50 bg-emerald-500/10 text-emerald-300";
  return (
    <div className={`rounded-lg border ${style} px-3 py-2 text-xs`}>
      <div className="text-[10px] uppercase tracking-wide opacity-80">Temp max</div>
      <div className="font-mono">{celsius.toFixed(1)}°C</div>
    </div>
  );
}

function ImuBadge({
  pitchRad,
  rollRad,
}: {
  pitchRad: number | null;
  rollRad: number | null;
}) {
  const pitchDeg = pitchRad !== null ? (pitchRad * 180) / Math.PI : null;
  const rollDeg = rollRad !== null ? (rollRad * 180) / Math.PI : null;
  const worst = Math.max(Math.abs(pitchDeg ?? 0), Math.abs(rollDeg ?? 0));
  const style =
    worst >= 30
      ? "border-red-500/50 bg-red-500/10 text-red-300"
      : worst >= 20
        ? "border-yellow-500/50 bg-yellow-500/10 text-yellow-300"
        : "border-emerald-500/50 bg-emerald-500/10 text-emerald-300";
  return (
    <div className={`rounded-lg border ${style} px-3 py-2 text-xs`}>
      <div className="text-[10px] uppercase tracking-wide opacity-80">IMU tilt</div>
      <div className="font-mono">
        pitch {pitchDeg?.toFixed(1) ?? "—"}° · roll {rollDeg?.toFixed(1) ?? "—"}°
      </div>
    </div>
  );
}

function BatteryBadge({ percentage }: { percentage: number }) {
  const pct = Math.max(0, Math.min(1, percentage));
  const label = `${Math.round(pct * 100)}%`;
  const style =
    pct < 0.15
      ? "border-red-500/50 bg-red-500/10 text-red-300"
      : pct < 0.3
        ? "border-yellow-500/50 bg-yellow-500/10 text-yellow-300"
        : "border-emerald-500/50 bg-emerald-500/10 text-emerald-300";
  return (
    <div className={`rounded-lg border ${style} px-3 py-2 text-sm`}>
      <div className="text-[10px] uppercase tracking-wide opacity-80">Battery</div>
      <div className="font-mono text-lg font-semibold">{label}</div>
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
