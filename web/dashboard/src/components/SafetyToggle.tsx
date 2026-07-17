import { useNavigate } from "react-router-dom";
import { Loader2, OctagonX, ShieldCheck } from "lucide-react";

import { cn } from "../lib/cn";
import { useSafety } from "../lib/useSafety";

interface Props {
  variant?: "hero" | "chip";
  className?: string;
}

/**
 * The one big soft e-stop control.
 *
 * hero — full card with the state and a single large button (Motions page).
 * chip — compact pill for the home header: tapping while released ENGAGES
 * immediately (stop must be instant); tapping while engaged navigates to
 * /motions so releasing stays a deliberate act on the hero control.
 */
export function SafetyToggle({ variant = "hero", className }: Props) {
  const safety = useSafety();
  const navigate = useNavigate();

  if (variant === "chip") {
    return (
      <button
        type="button"
        onClick={() => (safety.engaged ? navigate("/motions") : safety.engage("home chip"))}
        className={cn(
          "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium backdrop-blur",
          safety.engaged ? "bg-red-500/20 text-red-300" : "bg-emerald-500/20 text-emerald-300",
          className,
        )}
      >
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            safety.engaged ? "bg-red-400" : "animate-pulse bg-emerald-400",
          )}
        />
        {safety.engaged ? "Движения запрещены" : "СТОП"}
      </button>
    );
  }

  return (
    <section
      className={cn(
        "rounded-xl border p-4",
        safety.engaged
          ? "border-red-500/40 bg-red-500/5"
          : "border-emerald-500/40 bg-emerald-500/5",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {safety.engaged ? (
          <OctagonX className="h-5 w-5 text-red-400" />
        ) : (
          <ShieldCheck className="h-5 w-5 text-emerald-400" />
        )}
        <span className="text-base font-semibold">
          {safety.engaged ? "Движения запрещены" : "Движения разрешены"}
        </span>
      </div>

      <button
        type="button"
        disabled={safety.pending || !safety.loaded}
        onClick={() => (safety.engaged ? safety.release() : safety.engage("stop button"))}
        className={cn(
          "mt-3 flex min-h-14 w-full items-center justify-center gap-2 rounded-xl text-lg font-semibold text-white transition active:scale-[0.98] disabled:opacity-50",
          safety.engaged
            ? "bg-emerald-600 hover:bg-emerald-500"
            : "bg-red-600 hover:bg-red-500",
        )}
      >
        {safety.pending && <Loader2 className="h-5 w-5 animate-spin" />}
        {safety.engaged ? "Разрешить движения" : "СТОП"}
      </button>

      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
        Программный стоп: блокирует новые команды, но не отключает моторы. В
        аварийной ситуации используйте пульт или кнопку на роботе.
      </p>
    </section>
  );
}
