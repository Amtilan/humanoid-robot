import { useEffect, useRef, useState } from "react";
import { Ear, Square } from "lucide-react";

import { robotMicStreamUrl, type MicSource } from "../api/client";
import { cn } from "../lib/cn";

// The USB lavalier is loud; the built-in head mic needs heavy gain.
const GAINS: Record<MicSource, { value: number; label: string }[]> = {
  usb: [
    { value: 1, label: "Тихо" },
    { value: 2, label: "Обычно" },
    { value: 5, label: "Громко" },
  ],
  builtin: [
    { value: 5, label: "Тихо" },
    { value: 20, label: "Обычно" },
    { value: 60, label: "Громко" },
  ],
};

const SOURCES: { value: MicSource; label: string }[] = [
  { value: "usb", label: "Петличка (USB)" },
  { value: "builtin", label: "Встроенный" },
];

/**
 * "Robot's hearing" — plays a live mic stream (unbounded WAV over HTTP).
 * Source "usb" mirrors the microphone ASR listens to. Stop must fully detach
 * the src so the browser closes the connection instead of buffering.
 */
export function MicMonitor({ className }: { className?: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [source, setSource] = useState<MicSource>("usb");
  const [gain, setGain] = useState(GAINS.usb[1].value);
  const [error, setError] = useState(false);

  const stop = () => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    setPlaying(false);
  };

  const play = (g = gain, s = source) => {
    const audio = audioRef.current;
    if (!audio) return;
    setError(false);
    audio.src = robotMicStreamUrl(g, s);
    void audio.play().then(
      () => setPlaying(true),
      () => setError(true),
    );
  };

  const switchSource = (s: MicSource) => {
    if (s === source) return;
    const g = GAINS[s][1].value;
    setSource(s);
    setGain(g);
    if (playing) {
      stop();
      play(g, s);
    }
  };

  useEffect(() => stop, []);

  return (
    <div className={cn("rounded-xl border border-border bg-background/40 p-4", className)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Ear className="h-4 w-4 text-muted-foreground" />
          Слух робота
        </div>
        <div className="flex overflow-hidden rounded-full border border-border text-xs">
          {GAINS[source].map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setGain(value);
                if (playing) {
                  stop();
                  play(value);
                }
              }}
              className={cn(
                "px-2.5 py-1",
                gain === value ? "bg-primary text-primary-foreground" : "text-muted-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 flex overflow-hidden rounded-lg border border-border text-xs">
        {SOURCES.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => switchSource(value)}
            className={cn(
              "flex-1 px-2 py-1.5",
              source === value ? "bg-accent text-accent-foreground" : "text-muted-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={() => (playing ? stop() : play())}
        className={cn(
          "mt-3 flex min-h-12 w-full items-center justify-center gap-2 rounded-lg text-sm font-semibold transition active:scale-[0.98]",
          playing
            ? "bg-red-600/80 text-white hover:bg-red-500"
            : "bg-primary text-primary-foreground hover:brightness-110",
        )}
      >
        {playing ? <Square className="h-4 w-4" /> : <Ear className="h-4 w-4" />}
        {playing ? "Стоп" : "Слушать"}
      </button>

      {error ? (
        <p className="mt-2 text-xs text-red-300">
          Звук недоступен.{" "}
          <button type="button" onClick={() => play()} className="underline">
            Повторить
          </button>
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          «Петличка» — микрофон, который робот слушает. Звук отстаёт на несколько секунд — это
          нормально.
        </p>
      )}

      <audio ref={audioRef} onError={() => playing && setError(true)} className="hidden" />
    </div>
  );
}
