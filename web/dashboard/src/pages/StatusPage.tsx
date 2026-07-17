import type { LucideIcon } from "lucide-react";
import { BatteryMedium, PersonStanding, Thermometer, Wifi } from "lucide-react";

import { MicMonitor } from "../components/MicMonitor";
import { cn } from "../lib/cn";
import { useEventStream } from "../lib/eventStream";
import { useTelemetry } from "../lib/useTelemetry";

type Tone = "ok" | "warn" | "bad" | "muted";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "border-emerald-500/40 bg-emerald-500/5",
  warn: "border-amber-500/40 bg-amber-500/5",
  bad: "border-red-500/40 bg-red-500/5",
  muted: "border-border bg-background/40",
};

export function StatusPage() {
  const { connected } = useEventStream();
  const t = useTelemetry();

  const linkTone: Tone = !connected ? "bad" : t.stale ? "warn" : "ok";
  const linkValue = !connected ? "Нет связи" : t.stale ? "Нет данных" : "На связи";
  const linkHint = connected && t.stale ? "Телеметрия замерла — возможно, нужен перезапуск адаптера" : undefined;

  const pct = t.batteryPct === null ? null : Math.round(t.batteryPct * 100);
  const batteryTone: Tone = pct === null ? "muted" : pct < 15 ? "bad" : pct < 30 ? "warn" : "ok";

  const tempTone: Tone =
    t.tempMaxC === null ? "muted" : t.tempMaxC >= 85 ? "bad" : t.tempMaxC >= 70 ? "warn" : "ok";
  const tempValue =
    t.tempMaxC === null
      ? "—"
      : `${Math.round(t.tempMaxC)}°C · ${t.tempMaxC >= 85 ? "Горячий" : t.tempMaxC >= 70 ? "Тёплый" : "В норме"}`;

  const tiltDeg =
    t.pitchDeg === null && t.rollDeg === null
      ? null
      : Math.max(Math.abs(t.pitchDeg ?? 0), Math.abs(t.rollDeg ?? 0));
  const tiltTone: Tone = tiltDeg === null ? "muted" : tiltDeg >= 30 ? "bad" : tiltDeg >= 20 ? "warn" : "ok";
  const tiltValue =
    tiltDeg === null ? "—" : tiltDeg >= 20 ? `Наклонён (${Math.round(tiltDeg)}°)` : "Стоит ровно";

  return (
    <div className="mx-auto h-full w-full max-w-lg space-y-4 overflow-y-auto p-4">
      <h1 className="text-2xl font-semibold">Состояние</h1>

      <div className="grid grid-cols-2 gap-3">
        <StatusCard title="Связь" icon={Wifi} tone={linkTone} value={linkValue} hint={linkHint} />
        <StatusCard
          title="Батарея"
          icon={BatteryMedium}
          tone={batteryTone}
          value={pct === null ? "—" : `${pct}%`}
        >
          {pct !== null && (
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-background/80">
              <div
                className={cn(
                  "h-full rounded-full",
                  batteryTone === "bad"
                    ? "bg-red-500"
                    : batteryTone === "warn"
                      ? "bg-amber-500"
                      : "bg-emerald-500",
                )}
                style={{ width: `${pct}%` }}
              />
            </div>
          )}
        </StatusCard>
        <StatusCard title="Температура" icon={Thermometer} tone={tempTone} value={tempValue} />
        <StatusCard title="Положение" icon={PersonStanding} tone={tiltTone} value={tiltValue} />
      </div>

      <MicMonitor />
    </div>
  );
}

function StatusCard({
  title,
  icon: Icon,
  tone,
  value,
  hint,
  children,
}: {
  title: string;
  icon: LucideIcon;
  tone: Tone;
  value: string;
  hint?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-xl border p-4", TONE_CLASSES[tone])}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
        <Icon className="h-4 w-4" />
        {title}
      </div>
      <div className="mt-2 text-lg font-semibold leading-tight">{value}</div>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      {children}
    </div>
  );
}
