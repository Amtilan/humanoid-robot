import { useEffect } from "react";

import { api } from "../api/client";

const HEARTBEAT_INTERVAL_MS = 2_000;

export function WatchdogHeartbeat({ actor }: { actor: string }) {
  useEffect(() => {
    let cancelled = false;
    const send = async () => {
      if (cancelled) return;
      try {
        await api.safetyHeartbeat({ actor });
      } catch {
        // Watchdog stays quiet on transport errors — the cortex-core
        // side will engage e-stop if the outage persists.
      }
    };
    send();
    const handle = window.setInterval(send, HEARTBEAT_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [actor]);

  return null;
}
