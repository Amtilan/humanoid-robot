import { useEventSubscription, type EventEnvelope } from "./eventStream";
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
            title: `system.health: ${status}`,
            description: pickString(envelope.data, "detail") ?? undefined,
          });
        }
        return;
      }
      case "system.ota.available":
        push({
          kind: "info",
          title: "OTA update available",
          description: describeVersion(envelope),
        });
        return;
      case "system.ota.applied":
        push({
          kind: "success",
          title: "OTA update applied",
          description: describeVersion(envelope),
        });
        return;
      case "llm.rejected":
        push({
          kind: "warning",
          title: "LLM answer rejected",
          description:
            pickString(envelope.data, "reason") ??
            pickString(envelope.data, "fallback_text") ??
            undefined,
        });
        return;
      case "robot.command.result": {
        const ok = envelope.data.success === true;
        if (!ok) {
          push({
            kind: "error",
            title: "Robot command failed",
            description:
              pickString(envelope.data, "error") ??
              pickString(envelope.data, "command_id") ??
              undefined,
          });
        }
        return;
      }
      case "security.audit":
        push({
          kind: "info",
          title: "Security audit event",
          description: pickString(envelope.data, "action") ?? undefined,
        });
    }
  });

  return null;
}

function describeVersion(envelope: EventEnvelope): string | undefined {
  const version = pickString(envelope.data, "version");
  return version ? `version ${version}` : undefined;
}

function pickString(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}
