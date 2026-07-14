import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, MicOff } from "lucide-react";

import { cn } from "../lib/cn";

// Minimal ambient typing for the Web Speech API (not in lib.dom for all TS
// targets). This drives the browser mic; the robot's own mic is the offline
// path (voice pipeline), this is the convenience "talk from the dashboard" one.
interface SpeechRecognitionResultLike {
  0: { transcript: string };
  isFinal: boolean;
}
interface SpeechRecognitionEventLike {
  results: ArrayLike<SpeechRecognitionResultLike>;
  resultIndex: number;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

interface Props {
  onTranscript: (text: string) => void;
  language?: "ru" | "en";
  disabled?: boolean;
  size?: "sm" | "lg";
}

/**
 * Press-and-hold microphone. Uses the browser SpeechRecognition API to turn
 * speech into text, then hands the final transcript to `onTranscript` (which
 * feeds the same rag/ask/start path as typing). Degrades to a disabled,
 * explanatory button when the browser has no SpeechRecognition.
 */
export function PushToTalk({ onTranscript, language = "ru", disabled, size = "lg" }: Props) {
  const [supported] = useState(() => getRecognitionCtor() !== null);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const finalRef = useRef("");

  useEffect(() => {
    return () => recognitionRef.current?.abort();
  }, []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    if (disabled || !supported || listening) return;
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = language === "ru" ? "ru-RU" : "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    finalRef.current = "";
    rec.onresult = (e) => {
      let finalText = "";
      for (let i = e.resultIndex; i < e.results.length; i += 1) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript;
      }
      if (finalText) finalRef.current += finalText;
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => {
      setListening(false);
      const text = finalRef.current.trim();
      if (text) onTranscript(text);
    };
    recognitionRef.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch {
      setListening(false);
    }
  }, [disabled, supported, listening, language, onTranscript]);

  const title = !supported
    ? "Браузер не поддерживает распознавание речи (нужен Chrome). Говорите через микрофон робота."
    : listening
      ? "Отпустите, чтобы отправить"
      : "Зажмите и говорите";

  const lg = size === "lg";
  return (
    <button
      type="button"
      title={title}
      disabled={disabled || !supported}
      // Press-and-hold on both pointer and touch.
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={() => listening && stop()}
      className={cn(
        "flex shrink-0 select-none items-center justify-center rounded-full shadow-lg transition",
        lg ? "h-16 w-16" : "h-10 w-10",
        "disabled:cursor-not-allowed disabled:opacity-40",
        listening
          ? "scale-110 bg-red-500 text-white ring-4 ring-red-400/40"
          : "bg-primary text-primary-foreground hover:brightness-110",
      )}
    >
      {supported ? (
        <Mic className={cn(lg ? "h-7 w-7" : "h-5 w-5", listening && "animate-pulse")} />
      ) : (
        <MicOff className={lg ? "h-7 w-7" : "h-5 w-5"} />
      )}
    </button>
  );
}
