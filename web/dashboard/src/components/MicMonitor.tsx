import { useEffect, useRef, useState } from "react";
import { Ear, Square } from "lucide-react";

import { robotMicStreamUrl } from "../api/client";
import { cn } from "../lib/cn";

const GAINS = [
  { value: 5, label: "Тихо" },
  { value: 20, label: "Обычно" },
  { value: 60, label: "Громко" },
];

/**
 * "Robot's hearing" — plays the live head-mic stream (unbounded WAV over
 * HTTP). Stop must fully detach the src so the browser closes the connection
 * instead of buffering the stream in the background.
 */
export function MicMonitor({ className }: { className?: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [gain, setGain] = useState(20);
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

  const play = (g = gain) => {
    const audio = audioRef.current;
    if (!audio) return;
    setError(false);
    audio.src = robotMicStreamUrl(g);
    void audio.play().then(
      () => setPlaying(true),
      () => setError(true),
    );
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
          {GAINS.map(({ value, label }) => (
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
          Звук отстаёт на несколько секунд — это нормально.
        </p>
      )}

      <audio ref={audioRef} onError={() => playing && setError(true)} className="hidden" />
    </div>
  );
}
