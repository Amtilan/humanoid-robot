import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useEventSubscription } from "./eventStream";
import { wallOutcomeLabel } from "./labels";

const RESULT_TIMEOUT_MS = 10_000;

type Phase = "idle" | "sending" | "waiting" | "done";

export interface WallCommandStatus {
  phase: Phase;
  commandId: string | null;
  outcome: string | null;
  message: string | null;
  ok: boolean;
}

const IDLE: WallCommandStatus = {
  phase: "idle",
  commandId: null,
  outcome: null,
  message: null,
  ok: false,
};

/**
 * Send one video-wall command and track it to the wall.command.result verdict
 * (matched by command_id) or a client-side timeout.
 */
export function useWallCommand(): {
  status: WallCommandStatus;
  send: (body: { kind: "open_section" | "navigate"; section?: string; nav?: string }) => Promise<void>;
  reset: () => void;
} {
  const [status, setStatus] = useState<WallCommandStatus>(IDLE);
  const commandIdRef = useRef<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };
  useEffect(() => clearTimer, []);

  const settle = useCallback((outcome: string, message: string) => {
    clearTimer();
    commandIdRef.current = null;
    setStatus((prev) => ({
      ...prev,
      phase: "done",
      outcome,
      message,
      ok: outcome === "accepted",
    }));
  }, []);

  useEventSubscription("wall.command.result", (envelope) => {
    const id = commandIdRef.current;
    if (!id || envelope.data.command_id !== id) return;
    const result = envelope.data.result as Record<string, unknown> | undefined;
    const outcome = String(result?.outcome ?? "unreachable");
    const detail = typeof result?.detail === "string" ? result.detail : "";
    settle(
      outcome,
      detail ? `${wallOutcomeLabel(outcome)}: ${detail}` : wallOutcomeLabel(outcome),
    );
  });

  const send = useCallback(
    async (body: { kind: "open_section" | "navigate"; section?: string; nav?: string }) => {
      clearTimer();
      setStatus({ phase: "sending", commandId: null, outcome: null, message: null, ok: false });
      try {
        const { command_id } = await api.wallCommand({ ...body, submitter: "operator" });
        commandIdRef.current = command_id;
        setStatus({
          phase: "waiting",
          commandId: command_id,
          outcome: null,
          message: null,
          ok: false,
        });
        timerRef.current = window.setTimeout(() => {
          if (commandIdRef.current === command_id) {
            settle("no_reply", "Нет ответа от видеостены");
          }
        }, RESULT_TIMEOUT_MS);
      } catch (err) {
        settle("send_failed", `Не удалось отправить команду: ${String(err)}`);
      }
    },
    [settle],
  );

  const reset = useCallback(() => {
    clearTimer();
    commandIdRef.current = null;
    setStatus(IDLE);
  }, []);

  return { status, send, reset };
}
