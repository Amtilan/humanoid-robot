import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useEventSubscription, type EventEnvelope } from "./eventStream";

// Subjects the conversation renders. Sessions we started show a streaming
// bubble; FOREIGN sessions (the robot's own mic dialogue, /voice/say
// announcements) are rendered too, so the panel is the full conversation log.
const CHAT_SUBJECTS = new Set([
  "asr.final",
  "llm.answer.token",
  "llm.answer",
  "llm.rejected",
]);
const isChatSubject = (subject: string) => CHAT_SUBJECTS.has(subject);

// The full history is persisted ON THE ROBOT (core dialogue journal) and
// fetched on mount — reloads, other devices and robot reboots all keep the
// same conversation. localStorage is no longer used.

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

  // Seed the chat from the robot's persisted journal once on mount; keep
  // whatever streamed in live before the fetch resolved.
  useEffect(() => {
    let cancelled = false;
    api
      .dialogueHistory()
      .then(({ records }) => {
        if (cancelled) return;
        const server: ChatMessage[] = records.map((r) => ({
          id: `srv-${r.id}`,
          role: r.role,
          text: r.text,
          status: r.status === "rejected" ? "rejected" : "done",
          sessionId: r.session_id,
        }));
        setMessages((prev) => {
          const live = prev.filter((m) => !m.id.startsWith("srv-"));
          // Drop live messages already present in the server tail (they were
          // journaled while we were fetching).
          const tail = new Set(server.slice(-20).map((m) => `${m.role}:${m.text}`));
          const fresh = live.filter(
            (m) => m.status === "streaming" || !tail.has(`${m.role}:${m.text}`),
          );
          return [...server, ...fresh];
        });
      })
      .catch(() => {
        // Robot unreachable — the live-only log still works.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const patch = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  useEventSubscription(isChatSubject, (envelope: EventEnvelope) => {
    const session = envelope.data.session_id as string | undefined;
    if (!session) return;
    const target = routeRef.current.get(session);
    if (!target) {
      // FOREIGN session — the robot's own mic dialogue or a voice/say
      // announcement. Render it so the panel shows the whole conversation.
      if (envelope.subject === "asr.final") {
        const text = String(envelope.data.text ?? "").trim();
        if (text) {
          setMessages((prev) => [
            ...prev,
            { id: nextId(), role: "user", text, status: "done", sessionId: session },
          ]);
        }
      } else if (envelope.subject === "llm.answer") {
        const text = String(envelope.data.text ?? "").trim();
        if (text) {
          setMessages((prev) => [
            ...prev,
            { id: nextId(), role: "assistant", text, status: "done", sessionId: session },
          ]);
        }
      }
      return;
    }

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
    // Also wipe the robot-side journal, so the history stays cleared after
    // the next reload.
    api.dialogueClear().catch(() => {
      // If the robot is unreachable the local clear still applies.
    });
  }, []);

  return { messages, pending, error, send, clear };
}
