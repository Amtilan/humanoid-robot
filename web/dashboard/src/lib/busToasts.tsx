import { useEventSubscription, type EventEnvelope } from "./eventStream";
import { outcomeLabel } from "./labels";
import { useToast } from "./toast";

const isNoticeSubject = (subject: string) =>
  subject === "system.health" ||
  subject === "system.ota.available" ||
  subject === "system.ota.applied" ||
  subject === "llm.rejected" ||
  subject === "robot.command.result" ||
  subject === "security.audit";

export function BusToastBridge() {
  const { push } = useToast();

  useEventSubscription(isNoticeSubject, (envelope) => {
    switch (envelope.subject) {
      case "system.health": {
        const status = pickString(envelope.data, "status");
        if (status && status !== "healthy" && status !== "ready" && status !== "ok") {
          push({
            kind: "warning",
            title: `Состояние системы: ${status}`,
            description: pickString(envelope.data, "detail") ?? undefined,
          });
        }
        return;
      }
      case "system.ota.available":
        push({
          kind: "info",
          title: "Доступно обновление",
          description: describeVersion(envelope),
        });
        return;
      case "system.ota.applied":
        push({
          kind: "success",
          title: "Обновление установлено",
          description: describeVersion(envelope),
        });
        return;
      case "llm.rejected":
        push({
          kind: "warning",
          title: "Робот не смог ответить",
          description:
            pickString(envelope.data, "reason") ??
            pickString(envelope.data, "fallback_text") ??
            undefined,
        });
        return;
      case "robot.command.result": {
        // Payload nests the verdict: data.result = { outcome, error_code,
        // error_message }; outcome "accepted" is the only success.
        const result = envelope.data.result;
        const outcome =
          typeof result === "object" && result !== null
            ? (result as Record<string, unknown>).outcome
            : undefined;
        if (typeof outcome === "string" && outcome !== "accepted") {
          const message =
            typeof result === "object" && result !== null
              ? (result as Record<string, unknown>).error_message
              : undefined;
          push({
            kind: "error",
            title: "Команда не выполнена",
            description:
              typeof message === "string" && message
                ? `${outcomeLabel(outcome)}: ${message}`
                : outcomeLabel(outcome),
          });
        }
        return;
      }
      case "security.audit":
        push({
          kind: "info",
          title: "Событие безопасности",
          description: pickString(envelope.data, "action") ?? undefined,
        });
    }
  });

  return null;
}

function describeVersion(envelope: EventEnvelope): string | undefined {
  const version = pickString(envelope.data, "version");
  return version ? `версия ${version}` : undefined;
}

function pickString(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}
