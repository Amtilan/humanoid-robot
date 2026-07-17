import { useEffect, useRef, useState, type FormEvent } from "react";
import { Send, Bot, User, Volume2 } from "lucide-react";

import { api } from "../api/client";
import { cn } from "../lib/cn";
import { useToast } from "../lib/toast";
import type { ChatMessage, Conversation } from "../lib/useConversation";
import { PushToTalk } from "./PushToTalk";

interface Props {
  conversation: Conversation;
  language: "ru" | "en";
  voice?: boolean;
  className?: string;
}

/** Chat transcript + composer, driven by a shared `useConversation`. */
export function ChatPanel({ conversation, language, voice = true, className }: Props) {
  const { messages, pending, send } = conversation;
  const { push } = useToast();
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft;
    setDraft("");
    void send(text, language);
  };

  // Speak the typed text verbatim through the robot's speaker (no LLM).
  const sayVerbatim = () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    api.voiceSay({ text, language }).catch((err) =>
      push({ kind: "error", title: "Не удалось озвучить", description: String(err) }),
    );
  };

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <p className="mt-8 text-center text-sm text-muted-foreground">
            Спросите робота о чём угодно — голосом или текстом.
          </p>
        ) : (
          messages.map((m) => <Bubble key={m.id} message={m} />)
        )}
      </div>
      <form onSubmit={submit} className="flex items-center gap-2 border-t border-border p-3">
        {voice && (
          <PushToTalk
            size="sm"
            language={language}
            onTranscript={(t) => void send(t, language)}
          />
        )}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Написать роботу…"
          className="flex-1 rounded-full border border-border bg-background/60 px-4 py-2 text-sm outline-none focus:border-primary"
        />
        <button
          type="button"
          onClick={sayVerbatim}
          disabled={draft.trim().length === 0}
          title="Робот произнесёт этот текст вслух"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-border text-foreground disabled:opacity-40"
        >
          <Volume2 className="h-4 w-4" />
        </button>
        <button
          type="submit"
          disabled={draft.trim().length === 0 || pending}
          title="Спросить робота (ответит сам)"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-40"
        >
          <Send className="h-4 w-4" />
        </button>
      </form>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const streaming = message.status === "streaming";
  return (
    <div className={cn("flex gap-2", isUser ? "flex-row-reverse" : "flex-row")}>
      <div
        className={cn(
          "mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary/20 text-primary" : "bg-accent text-accent-foreground",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={cn(
          "max-w-[78%] rounded-2xl px-3 py-2 text-sm",
          isUser
            ? "rounded-tr-sm bg-primary text-primary-foreground"
            : message.status === "rejected"
              ? "rounded-tl-sm border border-yellow-500/40 bg-yellow-500/5 text-yellow-100"
              : "rounded-tl-sm bg-background/70 text-foreground",
        )}
      >
        {message.text === "" && streaming ? (
          <span className="inline-flex gap-1">
            <Dot /> <Dot delay="150ms" /> <Dot delay="300ms" />
          </span>
        ) : (
          <span className="whitespace-pre-wrap">
            {message.text}
            {streaming && (
              <span className="ml-0.5 inline-block h-3 w-1 animate-pulse bg-current align-middle" />
            )}
          </span>
        )}
      </div>
    </div>
  );
}

function Dot({ delay = "0ms" }: { delay?: string }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground"
      style={{ animationDelay: delay }}
    />
  );
}
