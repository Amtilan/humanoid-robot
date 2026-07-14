import { useEffect, useRef, useState } from "react";
import { VideoOff, Loader2 } from "lucide-react";

import { robotCameraStreamUrl } from "../api/client";
import { cn } from "../lib/cn";

interface Props {
  cameraId?: string;
  className?: string;
}

type Status = "loading" | "live" | "error";

/**
 * "Robot's eyes" — the front camera as an MJPEG stream in a plain <img>.
 * MJPEG connections drop occasionally (proxy hiccup, robot busy); on error we
 * reconnect with a cache-busting nonce rather than leaving a frozen frame.
 */
export function CameraView({ cameraId = "front", className }: Props) {
  const [status, setStatus] = useState<Status>("loading");
  const [nonce, setNonce] = useState(0);
  const retryRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (retryRef.current !== null) window.clearTimeout(retryRef.current);
    };
  }, []);

  const scheduleRetry = () => {
    if (retryRef.current !== null) return;
    retryRef.current = window.setTimeout(() => {
      retryRef.current = null;
      setStatus("loading");
      setNonce((n) => n + 1);
    }, 2000);
  };

  const base = robotCameraStreamUrl(cameraId);
  const src = `${base}${base.includes("?") ? "&" : "?"}_=${nonce}`;

  return (
    <div className={cn("relative overflow-hidden bg-black", className)}>
      <img
        key={nonce}
        src={src}
        alt="Robot camera"
        className={cn(
          "h-full w-full object-cover transition-opacity",
          status === "live" ? "opacity-100" : "opacity-0",
        )}
        onLoad={() => setStatus("live")}
        onError={() => {
          setStatus("error");
          scheduleRetry();
        }}
      />
      {status !== "live" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted-foreground">
          {status === "loading" ? (
            <>
              <Loader2 className="h-8 w-8 animate-spin" />
              <span className="text-sm">Подключение к камере…</span>
            </>
          ) : (
            <>
              <VideoOff className="h-8 w-8" />
              <span className="text-sm">Камера недоступна — переподключение…</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
