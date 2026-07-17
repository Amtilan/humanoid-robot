import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useEventSubscription } from "./eventStream";
import { denyReasonLabel, outcomeLabel } from "./labels";

const RESULT_TIMEOUT_MS = 15_000;

type Phase = "idle" | "sending" | "waiting" | "done";

export interface CommandStatus {
  phase: Phase;
  commandId: string | null;
  /** null until done; "denied"/"no_reply" are client-side verdicts. */
  outcome: string | null;
  /** Ready-to-render Russian text. */
  message: string | null;
  ok: boolean;
}

const IDLE: CommandStatus = { phase: "idle", commandId: null, outcome: null, message: null, ok: false };

const isVerdictSubject = (subject: string) =>
  subject === "robot.command.result" || subject === "safety.command.denied";

/**
 * Send one robot command and track it to a verdict: the first of
 * robot.command.result (matched by command_id), safety.command.denied, or a
 * client-side timeout ("adapter hung" is a real failure mode here).
 */
export function useRobotCommand(): {
  status: CommandStatus;
  send: (capability: string, payload: Record<string, unknown>) => Promise<void>;
  reset: () => void;
} {
  const [status, setStatus] = useState<CommandStatus>(IDLE);
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

  useEventSubscription(isVerdictSubject, (envelope) => {
    const id = commandIdRef.current;
    if (!id || envelope.data.command_id !== id) return;
    if (envelope.subject === "safety.command.denied") {
      const reason = String(envelope.data.reason ?? "");
      settle("denied", denyReasonLabel(reason));
      return;
    }
    const result = envelope.data.result as Record<string, unknown> | undefined;
    const outcome = String(result?.outcome ?? "timeout");
    const detail = typeof result?.error_message === "string" ? result.error_message : "";
    settle(outcome, detail ? `${outcomeLabel(outcome)}: ${detail}` : outcomeLabel(outcome));
  });

  const send = useCallback(
    async (capability: string, payload: Record<string, unknown>) => {
      clearTimer();
      setStatus({ phase: "sending", commandId: null, outcome: null, message: null, ok: false });
      try {
        const { command_id } = await api.robotCommand({
          capability,
          payload,
          submitter: "operator",
        });
        commandIdRef.current = command_id;
        setStatus({ phase: "waiting", commandId: command_id, outcome: null, message: null, ok: false });
        timerRef.current = window.setTimeout(() => {
          if (commandIdRef.current === command_id) {
            settle("no_reply", "Робот не ответил — возможно, адаптер завис");
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
