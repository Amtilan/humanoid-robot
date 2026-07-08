import { useEffect, useState } from "react";
import { Mic } from "lucide-react";

import { useEventSubscription } from "./eventStream";

const isSpeechSubject = (subject: string) =>
  subject === "speech.vad.detected" ||
  subject === "speech.wake_word.triggered" ||
  subject === "asr.partial" ||
  subject === "asr.final";

const ACTIVE_WINDOW_MS = 2_000;

export function MicActivity() {
  const [lastAt, setLastAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());

  useEventSubscription(isSpeechSubject, () => {
    setLastAt(Date.now());
  });

  useEffect(() => {
    if (lastAt === null) return;
    const handle = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(handle);
  }, [lastAt]);

  const active = lastAt !== null && now - lastAt < ACTIVE_WINDOW_MS;

  return (
    <span
      className={
        active
          ? "inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300"
          : "inline-flex items-center gap-1.5 rounded-full border border-border bg-background/60 px-2 py-0.5 text-xs text-muted-foreground"
      }
      title={active ? "Recent speech activity" : "Idle"}
    >
      <Mic className={active ? "h-3 w-3 animate-pulse" : "h-3 w-3"} />
      {active ? "listening" : "idle"}
    </span>
  );
}
