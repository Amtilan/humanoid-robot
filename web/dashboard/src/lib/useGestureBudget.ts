import { useCallback, useState } from "react";

import { useEventSubscription } from "./eventStream";

const isBudgetSubject = (subject: string) =>
  subject === "safety.command.forwarded" || subject === "robot.adapter.ready";

/**
 * Vendor-bug guard: the G1 SDK executes exactly ONE arm gesture per adapter
 * session — a second ExecuteAction hangs the shared DDS participant (and
 * freezes telemetry). Track "a gesture was forwarded" from the bus (catches
 * gestures issued by ANY client while this page is open) and reset when the
 * adapter restarts (robot.adapter.ready). The guard is soft: we can't see
 * history from before page load, so callers pair it with a permanent banner
 * and an explicit override.
 */
export function useGestureBudget(): { spent: boolean; override: () => void } {
  const [spent, setSpent] = useState(false);

  useEventSubscription(isBudgetSubject, (envelope) => {
    if (envelope.subject === "robot.adapter.ready") {
      setSpent(false);
      return;
    }
    if (envelope.data.capability === "arms.gesture") {
      setSpent(true);
    }
  });

  const override = useCallback(() => setSpent(false), []);
  return { spent, override };
}
