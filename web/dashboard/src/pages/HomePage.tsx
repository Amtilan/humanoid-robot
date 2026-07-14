import { useState } from "react";
import { Link } from "react-router-dom";
import { LayoutDashboard, Wifi, WifiOff } from "lucide-react";

import { CameraView } from "../components/CameraView";
import { ChatPanel } from "../components/ChatPanel";
import { useConversation } from "../lib/useConversation";
import { useEventStream } from "../lib/eventStream";
import { cn } from "../lib/cn";

/**
 * Unitree-app-style home: the robot's eyes fill the screen with a translucent
 * conversation dock. Camera hero on the left/top, chat + push-to-talk on the
 * right/bottom. This is the default landing route ("/").
 */
export function HomePage() {
  const [language, setLanguage] = useState<"ru" | "en">("ru");
  const conversation = useConversation();
  const { connected } = useEventStream();

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-black md:flex-row">
      {/* Eyes */}
      <div className="relative min-h-0 flex-1">
        <CameraView className="absolute inset-0" />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/40 via-transparent to-black/40" />

        {/* Top bar overlaid on the video */}
        <header className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
          <div className="flex items-center gap-2 rounded-full bg-black/40 px-3 py-1.5 backdrop-blur">
            <span className="text-sm font-semibold text-white">Unitree G1</span>
            <span
              className={cn(
                "flex items-center gap-1 text-xs",
                connected ? "text-emerald-400" : "text-red-400",
              )}
            >
              {connected ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
              {connected ? "онлайн" : "нет связи"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex overflow-hidden rounded-full bg-black/40 text-xs backdrop-blur">
              {(["ru", "en"] as const).map((l) => (
                <button
                  key={l}
                  type="button"
                  onClick={() => setLanguage(l)}
                  className={cn(
                    "px-3 py-1.5 uppercase",
                    language === l ? "bg-primary text-primary-foreground" : "text-white/80",
                  )}
                >
                  {l}
                </button>
              ))}
            </div>
            <Link
              to="/dashboard"
              title="Консоль"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-black/40 text-white/80 backdrop-blur hover:text-white"
            >
              <LayoutDashboard className="h-4 w-4" />
            </Link>
          </div>
        </header>
      </div>

      {/* Conversation dock: bottom sheet on mobile, right column on desktop */}
      <div className="flex min-h-0 flex-[1.1] flex-col border-t border-border bg-background/85 backdrop-blur md:h-full md:max-w-[420px] md:flex-none md:border-l md:border-t-0">
        <ChatPanel conversation={conversation} language={language} className="min-h-0 flex-1" />
      </div>
    </div>
  );
}
