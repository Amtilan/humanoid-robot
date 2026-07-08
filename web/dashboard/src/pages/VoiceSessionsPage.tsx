import { useMemo, useState } from "react";

import {
  useEventStream,
  useEventSubscription,
  type EventEnvelope,
} from "../lib/eventStream";

const VOICE_SUBJECTS = new Set([
  "speech.vad.detected",
  "speech.wake_word.triggered",
  "asr.partial",
  "asr.final",
  "llm.answer",
  "llm.rejected",
  "tts.synth.started",
  "tts.synth.finished",
]);
const MAX_SESSIONS = 8;
const isVoiceSubject = (subject: string) => VOICE_SUBJECTS.has(subject);

interface Session {
  session_id: string;
  first_at: string;
  last_at: string;
  events: EventEnvelope[];
}

export function VoiceSessionsPage() {
  const { connected } = useEventStream();
  const [sessions, setSessions] = useState<Map<string, Session>>(new Map());

  useEventSubscription(isVoiceSubject, (envelope) => {
      const sessionId = (envelope.data.session_id as string | undefined) ?? null;
      if (!sessionId) return;
      setSessions((prev) => {
        const next = new Map(prev);
        const existing = next.get(sessionId);
        if (existing) {
          existing.events = [...existing.events, envelope].slice(-40);
          existing.last_at = envelope.occurred_at;
          next.set(sessionId, existing);
        } else {
          next.set(sessionId, {
            session_id: sessionId,
            first_at: envelope.occurred_at,
            last_at: envelope.occurred_at,
            events: [envelope],
          });
        }
        if (next.size > MAX_SESSIONS) {
          const oldestKey = [...next.entries()].sort((a, b) =>
            a[1].last_at.localeCompare(b[1].last_at),
          )[0][0];
          next.delete(oldestKey);
        }
        return next;
      });
    });

  const ordered = useMemo(
    () =>
      [...sessions.values()].sort((a, b) => b.last_at.localeCompare(a.last_at)),
    [sessions],
  );

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Voice sessions</h1>
          <p className="text-sm text-muted-foreground">
            Wake&nbsp;→&nbsp;VAD&nbsp;→&nbsp;ASR&nbsp;→&nbsp;LLM&nbsp;→&nbsp;TTS timeline grouped by
            <code className="mx-1 rounded bg-muted px-1">session_id</code>.
          </p>
        </div>
        <span
          className={
            connected
              ? "inline-flex items-center gap-1.5 text-xs text-emerald-400"
              : "inline-flex items-center gap-1.5 text-xs text-yellow-400"
          }
        >
          <span
            className={
              connected
                ? "inline-block h-2 w-2 rounded-full bg-emerald-500"
                : "inline-block h-2 w-2 animate-pulse rounded-full bg-yellow-500"
            }
          />
          bus {connected ? "connected" : "reconnecting"}
        </span>
      </div>

      {ordered.length === 0 ? (
        <p className="rounded-lg border border-border bg-background/40 p-6 text-sm text-muted-foreground">
          No voice sessions yet. Say the wake word or push an ASR event to start one.
        </p>
      ) : (
        <div className="space-y-4">
          {ordered.map((session) => (
            <SessionCard key={session.session_id} session={session} />
          ))}
        </div>
      )}
    </div>
  );
}

function SessionCard({ session }: { session: Session }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-4">
      <div className="flex items-baseline justify-between pb-3">
        <span className="font-mono text-xs text-muted-foreground">
          {session.session_id}
        </span>
        <span className="text-[10px] text-muted-foreground">
          started {session.first_at.substring(11, 19)} · last{" "}
          {session.last_at.substring(11, 19)}
        </span>
      </div>
      <ol className="space-y-1">
        {session.events.map((event) => (
          <SessionEvent key={event.event_id} event={event} />
        ))}
      </ol>
    </div>
  );
}

function SessionEvent({ event }: { event: EventEnvelope }) {
  const badge = subjectStyle(event.subject);
  const preview = renderPreview(event);
  return (
    <li className="flex items-start gap-3 text-xs">
      <span className="w-14 shrink-0 font-mono text-[10px] text-muted-foreground">
        {event.occurred_at.substring(11, 19)}
      </span>
      <span
        className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${badge}`}
      >
        {event.subject}
      </span>
      {preview && <span className="min-w-0 truncate">{preview}</span>}
    </li>
  );
}

function subjectStyle(subject: string): string {
  if (subject.startsWith("speech.wake_word"))
    return "bg-fuchsia-500/15 text-fuchsia-300";
  if (subject.startsWith("speech.vad"))
    return "bg-sky-500/15 text-sky-300";
  if (subject.startsWith("asr.")) return "bg-blue-500/15 text-blue-300";
  if (subject === "llm.answer") return "bg-emerald-500/15 text-emerald-300";
  if (subject === "llm.rejected") return "bg-yellow-500/15 text-yellow-300";
  if (subject.startsWith("tts.")) return "bg-purple-500/15 text-purple-300";
  return "bg-muted text-muted-foreground";
}

function renderPreview(event: EventEnvelope): string | null {
  const data = event.data;
  const text = pickString(data, "text");
  if (text) return text;
  const reason = pickString(data, "reason");
  if (reason) return `reason: ${reason}`;
  const fallback = pickString(data, "fallback_text");
  if (fallback) return fallback;
  const language = pickString(data, "language");
  return language ? `language=${language}` : null;
}

function pickString(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}
