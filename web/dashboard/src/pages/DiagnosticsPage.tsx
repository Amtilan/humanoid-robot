import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, type GpuStats, type HostDiagnostics } from "../api/client";
import { useEventSubscription } from "../lib/eventStream";

const DIAG_SUBJECT = "system.diagnostics.tick";
const STALE_MS = 12_000;

export function DiagnosticsPage() {
  const client = useQueryClient();
  const [lastTickAt, setLastTickAt] = useState<number | null>(null);
  const lastTickRef = useRef<number | null>(null);
  lastTickRef.current = lastTickAt;

  const usePush = lastTickAt !== null && Date.now() - lastTickAt < STALE_MS;

  const hostQuery = useQuery({
    queryKey: ["diagnostics", "host"],
    queryFn: api.diagnosticsHost,
    refetchInterval: usePush ? false : 2_000,
  });
  const gpuQuery = useQuery({
    queryKey: ["diagnostics", "gpu"],
    queryFn: api.diagnosticsGpu,
    refetchInterval: usePush ? false : 5_000,
  });

  useEventSubscription(DIAG_SUBJECT, (envelope) => {
    const host = envelope.data.host as HostDiagnostics | undefined;
    const gpu = envelope.data.gpu as GpuStats | undefined;
    if (host) client.setQueryData(["diagnostics", "host"], host);
    if (gpu) client.setQueryData(["diagnostics", "gpu"], gpu);
    setLastTickAt(Date.now());
  });

  useEffect(() => {
    if (lastTickAt === null) return;
    const handle = window.setInterval(() => {
      if (lastTickRef.current === null) return;
      if (Date.now() - lastTickRef.current > STALE_MS) {
        setLastTickAt(null);
      }
    }, 2_000);
    return () => window.clearInterval(handle);
  }, [lastTickAt]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Diagnostics</h1>
          <p className="text-sm text-muted-foreground">
            Live host metrics. GPU section only renders on hosts where
            <code className="mx-1 rounded bg-muted px-1">jtop</code> reports back.
          </p>
        </div>
        <span
          className={
            usePush
              ? "inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300"
              : "inline-flex items-center gap-1.5 rounded-full border border-border bg-background/60 px-2 py-0.5 text-xs text-muted-foreground"
          }
        >
          <span
            className={
              usePush
                ? "inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400"
                : "inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground"
            }
          />
          {usePush ? "push (bus)" : "polling"}
        </span>
      </div>

      {hostQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : hostQuery.error ? (
        <p className="text-sm text-red-500">{String(hostQuery.error)}</p>
      ) : (
        <HostSection host={hostQuery.data} />
      )}

      {gpuQuery.data?.supported ? (
        <GpuSection gpu={gpuQuery.data} />
      ) : (
        <div className="rounded-lg border border-border bg-background/40 p-4 text-xs text-muted-foreground">
          GPU stats unavailable ({gpuQuery.data?.detail ?? "checking…"}).
        </div>
      )}
    </div>
  );
}

function HostSection({ host }: { host: HostDiagnostics }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card title="CPU">
          <Gauge value={host.cpu.percent} suffix="%" />
          <p className="pt-2 text-xs text-muted-foreground">
            {host.cpu.core_count} cores · load{" "}
            {host.cpu.load_avg_1m.toFixed(2)} /{" "}
            {host.cpu.load_avg_5m.toFixed(2)} /{" "}
            {host.cpu.load_avg_15m.toFixed(2)}
          </p>
        </Card>
        <Card title="Memory">
          <Gauge value={host.memory.percent} suffix="%" />
          <p className="pt-2 text-xs text-muted-foreground">
            {formatBytes(host.memory.used_bytes)} / {formatBytes(host.memory.total_bytes)}
            {host.memory.swap_total_bytes > 0 && (
              <>
                {" "}· swap {formatBytes(host.memory.swap_used_bytes)} /{" "}
                {formatBytes(host.memory.swap_total_bytes)}
              </>
            )}
          </p>
        </Card>
        <Card title="Uptime">
          <div className="text-2xl font-semibold">{formatUptime(host.uptime_s)}</div>
        </Card>
      </div>

      <div>
        <h2 className="pb-2 text-sm font-semibold">Per-core CPU</h2>
        <div className="grid grid-cols-4 gap-2 md:grid-cols-8">
          {host.cpu.per_core_percent.map((value, index) => (
            <div
              key={index}
              className="rounded border border-border bg-background/40 px-2 py-1 text-center"
            >
              <div className="text-[10px] text-muted-foreground">core {index}</div>
              <div className="text-sm font-mono">{value.toFixed(0)}%</div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h2 className="pb-2 text-sm font-semibold">Disks</h2>
        <div className="space-y-2">
          {host.disks.map((disk) => (
            <div key={disk.path} className="rounded border border-border bg-background/40 p-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-mono">{disk.path}</span>
                <span className="text-muted-foreground">
                  {formatBytes(disk.used_bytes)} / {formatBytes(disk.total_bytes)}
                </span>
              </div>
              <div className="mt-2 h-1.5 w-full rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${Math.min(100, disk.percent)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function GpuSection({ gpu }: { gpu: GpuStats }) {
  return (
    <div>
      <h2 className="pb-2 text-sm font-semibold">GPU</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {gpu.gpu_percent !== null && (
          <Card title="GPU load">
            <Gauge value={gpu.gpu_percent} suffix="%" />
          </Card>
        )}
        {gpu.ram_total_bytes !== null && (
          <Card title="GPU RAM">
            <div className="text-lg font-semibold">
              {formatBytes(gpu.ram_used_bytes ?? 0)} /{" "}
              {formatBytes(gpu.ram_total_bytes)}
            </div>
          </Card>
        )}
        {gpu.temperature_c !== null && (
          <Card title="Temp">
            <div className="text-2xl font-semibold">
              {gpu.temperature_c.toFixed(1)}°C
            </div>
          </Card>
        )}
        {gpu.power_w !== null && (
          <Card title="Power">
            <div className="text-2xl font-semibold">{gpu.power_w.toFixed(1)} W</div>
          </Card>
        )}
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-4">
      <h3 className="pb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Gauge({ value, suffix }: { value: number; suffix: string }) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div>
      <div className="text-3xl font-semibold">
        {value.toFixed(1)}
        <span className="pl-1 text-lg text-muted-foreground">{suffix}</span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

function formatBytes(n: number): string {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

function formatUptime(seconds: number): string {
  const s = Math.floor(seconds);
  const days = Math.floor(s / 86_400);
  const hours = Math.floor((s % 86_400) / 3_600);
  const minutes = Math.floor((s % 3_600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}
