import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type RobotTelemetrySample } from "../api/client";
import { useEventSubscription } from "./eventStream";

const STALE_AFTER_MS = 30_000;

export interface Telemetry {
  /** 0..1 or null when unknown. */
  batteryPct: number | null;
  tempMaxC: number | null;
  pitchDeg: number | null;
  rollDeg: number | null;
  /** True when the newest sample is older than 30 s — also the tell-tale of a
   * hung adapter DDS session (telemetry freezes). */
  stale: boolean;
  loaded: boolean;
}

/** Shared robot telemetry: poll + live merge by kind (same cache as RobotPage). */
export function useTelemetry(): Telemetry {
  const client = useQueryClient();
  const query = useQuery({
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

  const samples = query.data ?? [];
  const byKind = (kind: string) => samples.find((s) => s.kind === kind);

  const battery = byKind("battery");
  const batteryPct =
    battery && typeof battery.payload.percentage === "number"
      ? (battery.payload.percentage as number)
      : null;

  const temperature = byKind("temperature");
  const numericTemps = temperature
    ? Object.values(temperature.payload).filter((v): v is number => typeof v === "number")
    : [];
  const tempMaxC = numericTemps.length > 0 ? Math.max(...numericTemps) : null;

  const imu = byKind("imu");
  const rad = (key: string): number | null =>
    imu && typeof imu.payload[key] === "number" ? (imu.payload[key] as number) : null;
  const toDeg = (value: number | null) => (value === null ? null : (value * 180) / Math.PI);

  const newest = samples.reduce<number>(
    (max, s) => Math.max(max, Date.parse(s.observed_at) || 0),
    0,
  );
  const stale = newest === 0 || Date.now() - newest > STALE_AFTER_MS;

  return {
    batteryPct,
    tempMaxC,
    pitchDeg: toDeg(rad("pitch_rad")),
    rollDeg: toDeg(rad("roll_rad")),
    stale,
    loaded: query.data !== undefined,
  };
}
