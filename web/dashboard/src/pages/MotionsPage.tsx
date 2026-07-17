import { useState } from "react";
import { AlertTriangle, CheckCircle2, Hand, Loader2, PersonStanding, XCircle } from "lucide-react";

import { ConfirmDialog } from "../components/ConfirmDialog";
import { MotionButton } from "../components/MotionButton";
import { SafetyToggle } from "../components/SafetyToggle";
import { cn } from "../lib/cn";
import { GESTURE_LABELS, POSTURE_LABELS } from "../lib/labels";
import { useGestureBudget } from "../lib/useGestureBudget";
import { useRobotCommand } from "../lib/useRobotCommand";
import { useSafety } from "../lib/useSafety";

interface PendingPosture {
  posture: string;
  label: string;
}

export function MotionsPage() {
  const safety = useSafety();
  const budget = useGestureBudget();
  const { status, send } = useRobotCommand();
  const [confirm, setConfirm] = useState<PendingPosture | null>(null);

  const busy = status.phase === "sending" || status.phase === "waiting";
  const locked = safety.engaged;

  const sendGesture = (gesture: string) => void send("arms.gesture", { gesture });
  const sendPosture = (posture: string) => void send("locomotion.posture", { posture });

  return (
    <div className="mx-auto h-full w-full max-w-lg space-y-4 overflow-y-auto p-4">
      <h1 className="text-2xl font-semibold">Движения</h1>

      <SafetyToggle variant="hero" />

      <div className="flex gap-2 rounded-xl border border-amber-500/40 bg-amber-500/5 p-3 text-xs leading-relaxed text-amber-200/90">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
        <div>
          Особенность робота: за один сеанс выполняется только один жест руками —
          после него жесты блокируются до перезапуска адаптера. Не блокируйте
          экран телефона, пока робот двигается: защита остановит его автоматически.
        </div>
      </div>

      {status.phase !== "idle" && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
            status.phase === "done"
              ? status.ok
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                : "border-red-500/40 bg-red-500/10 text-red-200"
              : "border-border bg-background/60 text-muted-foreground",
          )}
        >
          {busy ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
          ) : status.ok ? (
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0" />
          )}
          <span>
            {status.phase === "sending" && "Отправляю команду…"}
            {status.phase === "waiting" && "Робот выполняет…"}
            {status.phase === "done" && status.message}
          </span>
        </div>
      )}

      <section>
        <h2 className="mb-2 flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-muted-foreground">
          <Hand className="h-4 w-4" /> Жесты
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {Object.entries(GESTURE_LABELS).map(([gesture, label]) => (
            <MotionButton
              key={gesture}
              label={label}
              onPress={() => sendGesture(gesture)}
              disabled={locked || budget.spent}
              busy={busy}
            />
          ))}
        </div>
        {locked && (
          <p className="mt-2 text-xs text-muted-foreground">
            Сначала нажмите «Разрешить движения».
          </p>
        )}
        {!locked && budget.spent && (
          <p className="mt-2 text-xs text-amber-300/90">
            Жест уже выполнен в этом сеансе. Следующий может подвесить робота.{" "}
            <button type="button" onClick={budget.override} className="underline">
              Всё равно отправить
            </button>
          </p>
        )}
      </section>

      <section>
        <h2 className="mb-2 flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-muted-foreground">
          <PersonStanding className="h-4 w-4" /> Позы
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {Object.entries(POSTURE_LABELS).map(([posture, label]) => (
            <MotionButton
              key={posture}
              label={label}
              onPress={() =>
                posture === "damp"
                  ? sendPosture(posture)
                  : setConfirm({ posture, label })
              }
              disabled={locked}
              busy={busy}
            />
          ))}
        </div>
        {locked && (
          <p className="mt-2 text-xs text-muted-foreground">
            Сначала нажмите «Разрешить движения».
          </p>
        )}
      </section>

      {confirm && (
        <ConfirmDialog
          title={confirm.label}
          body="Робот изменит позу. Убедитесь, что вокруг него свободно и он стоит устойчиво."
          onConfirm={() => sendPosture(confirm.posture)}
          onClose={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
