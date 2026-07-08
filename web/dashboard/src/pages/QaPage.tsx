import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useEventSubscription, type EventEnvelope } from "../lib/eventStream";

interface Citation {
  chunk_id: string;
  quote: string;
}

type Outcome = "answer" | "rejected" | "waiting";

const LIVE_SUBJECTS = new Set([
  "asr.partial",
  "asr.final",
  "llm.answer.token",
  "llm.answer",
  "llm.rejected",
]);
const isLiveSubject = (subject: string) => LIVE_SUBJECTS.has(subject);

const TYPEWRITER_MS_PER_CHAR = 18;

export function QaPage() {
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState<"ru" | "en">("ru");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [answer, setAnswer] = useState<{
    text: string;
    citations: Citation[];
    confidence: number;
  } | null>(null);
  const [rejection, setRejection] = useState<{
    reason: string;
    fallback_text: string | null;
  } | null>(null);

  const start = useMutation({
    mutationFn: () => api.ragAskStart({ question, language, timeout_s: 60 }),
    onMutate: () => {
      setEvents([]);
      setAnswer(null);
      setRejection(null);
      setSessionId(null);
    },
    onSuccess: ({ session_id }) => setSessionId(session_id),
  });

  useEventSubscription(isLiveSubject, (envelope) => {
    if (sessionId === null) return;
    if ((envelope.data.session_id as string | undefined) !== sessionId) return;
    setEvents((prev) => [...prev, envelope].slice(-40));
    if (envelope.subject === "llm.answer") {
      const text = String(envelope.data.text ?? "");
      const raw = envelope.data.citations;
      const citations = Array.isArray(raw)
        ? (raw.filter(isCitation) as Citation[])
        : [];
      const confidence = Number(envelope.data.confidence ?? 0);
      setAnswer({ text, citations, confidence });
    } else if (envelope.subject === "llm.rejected") {
      setRejection({
        reason: String(envelope.data.reason ?? ""),
        fallback_text:
          typeof envelope.data.fallback_text === "string"
            ? envelope.data.fallback_text
            : null,
      });
    }
  });

  const outcome: Outcome =
    answer !== null ? "answer" : rejection !== null ? "rejected" : "waiting";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">QA test</h1>
        <p className="text-sm text-muted-foreground">
          Publishes a synthetic <code>asr.final</code> and streams the pipeline
          live via the event bus.
        </p>
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-background/40 p-4">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Задайте вопрос роботу…"
          rows={3}
          className="w-full rounded-md border border-border bg-background/60 px-3 py-2 text-sm outline-none focus:border-primary"
        />
        <div className="flex items-center gap-3">
          <label className="text-xs uppercase text-muted-foreground">Language</label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as "ru" | "en")}
            className="rounded-md border border-border bg-background/60 px-2 py-1 text-sm"
          >
            <option value="ru">ru</option>
            <option value="en">en</option>
          </select>
          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={question.trim().length === 0 || start.isPending}
            className="ml-auto rounded-md bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
          >
            {start.isPending ? "Starting…" : "Ask"}
          </button>
        </div>
      </div>

      {start.error && (
        <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {String(start.error)}
        </p>
      )}

      {sessionId !== null && (
        <div className="space-y-4">
          <div className="flex items-baseline justify-between text-xs">
            <span className="font-mono text-muted-foreground">{sessionId}</span>
            <StatusBadge outcome={outcome} />
          </div>

          <Pipeline events={events} />

          {answer !== null && <AnswerCard answer={answer} />}
          {rejection !== null && <RejectionCard rejection={rejection} />}
        </div>
      )}
    </div>
  );
}

function Pipeline({ events }: { events: EventEnvelope[] }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-4">
      <div className="pb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Pipeline
      </div>
      {events.length === 0 ? (
        <p className="text-xs text-muted-foreground">Waiting for bus events…</p>
      ) : (
        <ol className="space-y-1">
          {events.map((event) => (
            <li key={event.event_id} className="flex items-center gap-3 text-xs">
              <span className="w-16 shrink-0 font-mono text-[10px] text-muted-foreground">
                {event.occurred_at.substring(11, 19)}
              </span>
              <span className="rounded px-1.5 py-0.5 text-[10px] font-medium">
                {event.subject}
              </span>
              <span className="min-w-0 truncate text-muted-foreground">
                {previewFor(event)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function AnswerCard({
  answer,
}: {
  answer: { text: string; citations: Citation[]; confidence: number };
}) {
  const rendered = useTypewriter(answer.text);
  return (
    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4">
      <div className="flex items-baseline justify-between pb-2">
        <div className="text-xs uppercase text-emerald-300">Answer</div>
        <div className="text-xs text-muted-foreground">
          confidence {answer.confidence.toFixed(2)}
        </div>
      </div>
      <p className="whitespace-pre-wrap text-sm">
        {rendered}
        {rendered.length < answer.text.length && (
          <span className="ml-0.5 inline-block h-3 w-1 animate-pulse bg-emerald-400 align-middle" />
        )}
      </p>
      {answer.citations.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs uppercase text-muted-foreground">Citations</div>
          <ul className="space-y-1 text-xs">
            {answer.citations.map((c, i) => (
              <li key={i} className="rounded bg-background/60 px-2 py-1">
                <span className="font-mono text-[10px] text-muted-foreground">
                  {c.chunk_id}
                </span>
                <div className="mt-0.5">{c.quote}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RejectionCard({
  rejection,
}: {
  rejection: { reason: string; fallback_text: string | null };
}) {
  return (
    <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/5 p-4">
      <div className="pb-2 text-xs uppercase text-yellow-300">Rejected</div>
      <p className="text-sm">reason: {rejection.reason}</p>
      {rejection.fallback_text && (
        <p className="mt-2 text-sm italic text-muted-foreground">
          {rejection.fallback_text}
        </p>
      )}
    </div>
  );
}

function StatusBadge({ outcome }: { outcome: Outcome }) {
  if (outcome === "answer") {
    return (
      <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-400">
        answer
      </span>
    );
  }
  if (outcome === "rejected") {
    return (
      <span className="rounded-full bg-yellow-500/10 px-2 py-0.5 text-xs text-yellow-400">
        rejected
      </span>
    );
  }
  return (
    <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-xs text-sky-400">
      waiting
    </span>
  );
}

function useTypewriter(target: string): string {
  const [rendered, setRendered] = useState("");
  const targetRef = useRef(target);
  useEffect(() => {
    targetRef.current = target;
    setRendered("");
    if (target === "") return;
    let index = 0;
    const handle = window.setInterval(() => {
      index += 1;
      setRendered(target.slice(0, index));
      if (index >= targetRef.current.length) {
        window.clearInterval(handle);
      }
    }, TYPEWRITER_MS_PER_CHAR);
    return () => window.clearInterval(handle);
  }, [target]);
  return rendered;
}

function isCitation(value: unknown): value is Citation {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Record<string, unknown>).chunk_id === "string" &&
    typeof (value as Record<string, unknown>).quote === "string"
  );
}

function previewFor(event: EventEnvelope): string {
  const text = event.data.text;
  if (typeof text === "string" && text.length > 0) return text;
  const delta = event.data.delta_text;
  if (typeof delta === "string" && delta.length > 0) return delta;
  const reason = event.data.reason;
  if (typeof reason === "string") return `reason: ${reason}`;
  return "";
}
