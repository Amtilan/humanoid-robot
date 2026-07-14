import { useCallback, useRef, useState } from "react";

import { api } from "../api/client";
import { useEventSubscription, type EventEnvelope } from "./eventStream";

// Subjects the conversation cares about. asr.final is the pipeline's echo of
// the user turn; we already have that text locally (typed or dictated), so we
// only consume the LLM side here.
const LLM_SUBJECTS = new Set([
  "llm.answer.token",
  "llm.answer",
  "llm.rejected",
]);
const isLlmSubject = (subject: string) => LLM_SUBJECTS.has(subject);

export type ChatRole = "user" | "assistant";
export type ChatStatus = "streaming" | "done" | "rejected";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  status: ChatStatus;
  sessionId?: string;
  confidence?: number;
}

export interface Conversation {
  messages: ChatMessage[];
  pending: boolean;
  error: string | null;
  send: (text: string, language?: "ru" | "en") => Promise<void>;
  clear: () => void;
}

let counter = 0;
const nextId = () => `m${Date.now().toString(36)}-${(counter += 1)}`;

/**
 * Multi-turn conversation over the RAG pipeline. `send()` posts the turn via
 * `rag/ask/start` and the answer streams back over the event bus keyed by
 * `session_id`, so several turns can be in flight and each routes to its own
 * assistant bubble.
 */
export function useConversation(): Conversation {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // session_id -> assistant message id, so streamed tokens find their bubble.
  const routeRef = useRef(new Map<string, string>());

  const patch = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  useEventSubscription(isLlmSubject, (envelope: EventEnvelope) => {
    const session = envelope.data.session_id as string | undefined;
    if (!session) return;
    const target = routeRef.current.get(session);
    if (!target) return;

    if (envelope.subject === "llm.answer.token") {
      const delta = String(envelope.data.delta_text ?? envelope.data.text ?? "");
      if (delta) patch(target, (m) => ({ ...m, text: m.text + delta }));
    } else if (envelope.subject === "llm.answer") {
      const text = String(envelope.data.text ?? "");
      const confidence = Number(envelope.data.confidence ?? 0);
      patch(target, (m) => ({
        ...m,
        text: text || m.text,
        confidence,
        status: "done",
      }));
      routeRef.current.delete(session);
      setPending(false);
    } else if (envelope.subject === "llm.rejected") {
      const fallback =
        typeof envelope.data.fallback_text === "string"
          ? envelope.data.fallback_text
          : String(envelope.data.reason ?? "отклонено");
      patch(target, (m) => ({ ...m, text: fallback, status: "rejected" }));
      routeRef.current.delete(session);
      setPending(false);
    }
  });

  const send = useCallback(
    async (text: string, language: "ru" | "en" = "ru") => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setError(null);
      setPending(true);
      const userId = nextId();
      const assistantId = nextId();
      setMessages((prev) => [
        ...prev,
        { id: userId, role: "user", text: trimmed, status: "done" },
        { id: assistantId, role: "assistant", text: "", status: "streaming" },
      ]);
      try {
        const { session_id } = await api.ragAskStart({
          question: trimmed,
          language,
          timeout_s: 60,
        });
        routeRef.current.set(session_id, assistantId);
        patch(assistantId, (m) => ({ ...m, sessionId: session_id }));
      } catch (err) {
        patch(assistantId, (m) => ({
          ...m,
          text: "Не удалось отправить запрос.",
          status: "rejected",
        }));
        setError(String(err));
        setPending(false);
      }
    },
    [patch],
  );

  const clear = useCallback(() => {
    routeRef.current.clear();
    setMessages([]);
    setError(null);
    setPending(false);
  }, []);

  return { messages, pending, error, send, clear };
}
