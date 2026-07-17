// Domain-value → Russian label maps shared across the owner-facing screens
// (motions page, status page, toasts). Keys mirror backend enums:
// G1_GESTURES (adapters-unitree-g1/manifest.py) and PostureKind
// (domain/robot/commands.py). Keep in sync manually — the sets are tiny.

export const GESTURE_LABELS: Record<string, string> = {
  "high wave": "Помахать рукой",
  "face wave": "Помахать у лица",
  "high five": "Дать пять",
  "right kiss": "Послать поцелуй",
  "right hand up": "Поднять руку",
  "x-ray": "Поза «икс»",
  "release arm": "Опустить руки",
};

// Curated owner-safe subset. zero_torque / high_stand / low_stand / stop_move
// stay dev-only (RobotPage): zero_torque collapses a standing robot.
export const POSTURE_LABELS: Record<string, string> = {
  damp: "Расслабиться",
  sit: "Сесть",
  squat: "Присесть",
  stand_up: "Встать",
  balance_stand: "Стоять (баланс)",
};

export function outcomeLabel(outcome: string): string {
  switch (outcome) {
    case "accepted":
      return "Выполнено";
    case "rejected_by_policy":
      return "Отклонено защитой";
    case "hardware_error":
      return "Ошибка робота";
    case "timeout":
      return "Робот не ответил";
    default:
      return outcome;
  }
}

export function denyReasonLabel(reason: string): string {
  const lower = reason.toLowerCase();
  if (lower.includes("estop") || lower.includes("e-stop")) {
    return "Движения запрещены — нажмите «Разрешить движения»";
  }
  if (lower.includes("rate")) {
    return "Слишком много команд подряд — подождите немного";
  }
  if (lower.includes("capability")) {
    return "Эта команда не разрешена";
  }
  return reason;
}
