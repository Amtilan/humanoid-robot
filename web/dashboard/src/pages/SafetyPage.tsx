import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type SafetyStatus } from "../api/client";
import { useEventSubscription, type EventEnvelope } from "../lib/eventStream";
import { useToast } from "../lib/toast";
import { AuditPanel } from "./SafetyAuditPanel";

const isSafetySubject = (subject: string) =>
  subject === "safety.estop.engaged" ||
  subject === "safety.estop.released" ||
  subject === "safety.command.denied" ||
  subject === "safety.command.forwarded" ||
  subject === "safety.command.timeout" ||
  subject === "safety.watchdog.heartbeat";

const MAX_TAPE = 40;

export function SafetyPage() {
  const client = useQueryClient();
  const { push } = useToast();
  const [actor, setActor] = useState("operator");
  const [reason, setReason] = useState("");
  const [tape, setTape] = useState<EventEnvelope[]>([]);

  const status = useQuery({
    queryKey: ["safety", "status"],
    queryFn: api.safetyStatus,
    refetchInterval: 10_000,
  });

  useEventSubscription(isSafetySubject, (envelope) => {
    setTape((prev) => [envelope, ...prev].slice(0, MAX_TAPE));
    if (envelope.subject === "safety.estop.engaged") {
      client.setQueryData<SafetyStatus | undefined>(
        ["safety", "status"],
        (prev) => (prev ? { ...prev, estop_engaged: true } : prev),
      );
    } else if (envelope.subject === "safety.estop.released") {
      client.setQueryData<SafetyStatus | undefined>(
        ["safety", "status"],
        (prev) => (prev ? { ...prev, estop_engaged: false } : prev),
      );
    }
  });

  const engage = useMutation({
    mutationFn: () =>
      api.safetyEngage({ actor, reason: reason.trim() || undefined }),
    onSuccess: () => push({ kind: "warning", title: "E-STOP engaged" }),
    onError: (err) => push({ kind: "error", title: "E-stop failed", description: String(err) }),
  });

  const release = useMutation({
    mutationFn: () => api.safetyRelease({ actor }),
    onSuccess: () => push({ kind: "success", title: "E-STOP released" }),
    onError: (err) => push({ kind: "error", title: "Release failed", description: String(err) }),
  });

  const engaged = status.data?.estop_engaged ?? true;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Safety</h1>
        <p className="text-sm text-muted-foreground">
          Fail-closed gate between orchestrators and motor commands.
        </p>
      </div>

      <div
        className={
          engaged
            ? "rounded-xl border-2 border-red-500/60 bg-red-500/10 p-6"
            : "rounded-xl border-2 border-emerald-500/40 bg-emerald-500/5 p-6"
        }
      >
        <div className="flex items-center gap-4">
          <div
            className={
              engaged
                ? "h-3 w-3 animate-pulse rounded-full bg-red-500"
                : "h-3 w-3 rounded-full bg-emerald-500"
            }
          />
          <div>
            <div className="text-lg font-semibold">
              {engaged ? "E-STOP ENGAGED" : "E-stop released"}
            </div>
            <div className="text-xs text-muted-foreground">
              {engaged
                ? "All robot.command.requested events are being denied."
                : "Motor commands may flow — verify context is safe."}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              disabled={engage.isPending || engaged}
              onClick={() => engage.mutate()}
              className="rounded-md bg-red-600 px-5 py-2 text-sm font-semibold text-white shadow disabled:opacity-50"
            >
              {engage.isPending ? "Engaging…" : "Engage E-STOP"}
            </button>
            <button
              type="button"
              disabled={release.isPending || !engaged}
              onClick={() => release.mutate()}
              className="rounded-md border border-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-300 disabled:opacity-40"
            >
              {release.isPending ? "Releasing…" : "Release"}
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
          <label className="flex flex-col text-xs">
            <span className="pb-1 uppercase tracking-wide text-muted-foreground">Actor</span>
            <input
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              className="rounded-md border border-border bg-background/60 px-2 py-1 text-sm"
            />
          </label>
          <label className="flex flex-col text-xs">
            <span className="pb-1 uppercase tracking-wide text-muted-foreground">
              Reason (engage only)
            </span>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. tipping over"
              className="rounded-md border border-border bg-background/60 px-2 py-1 text-sm"
            />
          </label>
        </div>
      </div>

      {status.data && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <Card title="Watchdog">
            <div className="flex items-center gap-2 text-sm">
              <span
                className={
                  status.data.watchdog_live
                    ? "inline-block h-2 w-2 rounded-full bg-emerald-500"
                    : "inline-block h-2 w-2 animate-pulse rounded-full bg-yellow-500"
                }
              />
              <span>{status.data.watchdog_live ? "live" : "stale"}</span>
            </div>
            <p className="pt-1 text-xs text-muted-foreground">
              timeout {status.data.watchdog_timeout_s.toFixed(1)} s ·{" "}
              {status.data.watchdog_seconds_since_heartbeat === null
                ? "no heartbeat yet"
                : `${status.data.watchdog_seconds_since_heartbeat.toFixed(1)} s ago`}
            </p>
          </Card>
          <Card title="Reconciler">
            <div className="flex items-center gap-2 text-sm">
              <span
                className={
                  status.data.pending_command_count > 0
                    ? "inline-block h-2 w-2 animate-pulse rounded-full bg-sky-400"
                    : "inline-block h-2 w-2 rounded-full bg-emerald-500"
                }
              />
              <span>
                {status.data.pending_command_count} pending
              </span>
            </div>
            <p className="pt-1 text-xs text-muted-foreground">
              timeout {status.data.command_timeout_s.toFixed(1)} s → auto e-stop
            </p>
            {status.data.pending_command_ids.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-[10px] text-muted-foreground">
                {status.data.pending_command_ids.map((id) => (
                  <li key={id} className="font-mono">{id}</li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Allowed capabilities">
            {status.data.allowed_capabilities.length === 0 ? (
              <p className="text-xs text-muted-foreground">None (fail-closed).</p>
            ) : (
              <ul className="space-y-1 text-xs">
                {status.data.allowed_capabilities.map((cap) => (
                  <li key={cap} className="rounded bg-background/60 px-2 py-1 font-mono">
                    {cap}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Rate limit">
            <div className="text-sm">
              {status.data.rate_limit_max_events} events /{" "}
              {status.data.rate_limit_window_s.toFixed(1)} s
            </div>
          </Card>
          <Card title="Velocity envelope">
            <div className="text-sm">
              ≤ {status.data.max_linear_speed_mps.toFixed(2)} m/s ·{" "}
              {status.data.max_angular_rate_rps.toFixed(2)} rad/s
            </div>
            <p className="pt-1 text-xs text-muted-foreground">
              L2 norm of linear_x + linear_y is compared.
            </p>
          </Card>
          <Card title="Per-actor budgets">
            <ul className="space-y-0.5 text-xs">
              {Object.entries(status.data.actor_budgets).map(([name, b]) => (
                <li key={name} className="flex justify-between font-mono text-[11px]">
                  <span>{name}</span>
                  <span className="text-muted-foreground">
                    {b.max_events}/{b.window_s}s
                  </span>
                </li>
              ))}
              <li className="flex justify-between font-mono text-[11px] text-muted-foreground">
                <span>default</span>
                <span>
                  {status.data.actor_default_budget.max_events}/
                  {status.data.actor_default_budget.window_s}s
                </span>
              </li>
            </ul>
          </Card>
        </div>
      )}

      <AuditPanel />

      <div className="rounded-lg border border-border bg-background/40 p-4">
        <div className="pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Live safety feed ({tape.length})
        </div>
        {tape.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Subscribed to <code>safety.&gt;</code>. Waiting for events…
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
                <span
                  className={
                    event.subject === "safety.command.forwarded"
                      ? "font-medium text-emerald-300"
                      : event.subject === "safety.command.denied"
                        ? "font-medium text-yellow-300"
                        : event.subject === "safety.estop.engaged"
                          ? "font-medium text-red-300"
                          : "font-medium text-sky-300"
                  }
                >
                  {event.subject}
                </span>
                <span className="truncate text-muted-foreground">
                  {JSON.stringify(event.data).slice(0, 100)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
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
