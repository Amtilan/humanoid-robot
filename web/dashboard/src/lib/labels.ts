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

// Video-wall sections (MinTrans app). Keys mirror WallSection
// (domain/wall/commands.py) — the app's own screen names.
export const WALL_SECTIONS: { key: string; label: string }[] = [
  { key: "Avto1", label: "Кызылорда — Жезказган" },
  { key: "Avto2", label: "Актобе — Карабутак — Улгайсын" },
  { key: "Avto3", label: "Мост через Иртыш" },
  { key: "Avto4", label: "Обход Сарыагаша" },
  { key: "Avto5", label: "Актобе — Улгайсын" },
  { key: "JD1", label: "Дарбаза — Мактаарал" },
  { key: "JD2", label: "Мойынты — Кызылжар" },
  { key: "JD3", label: "Бахты — Аягоз" },
  { key: "Aero1", label: "Аэропорт Зайсан" },
  { key: "Aero2", label: "Аэропорт Катон-Карагай" },
  { key: "Aero3", label: "Аэропорт Кендерли" },
  { key: "Aero4", label: "Аэропорт Аркалык" },
];

export const WALL_CATEGORIES: { title: string; prefix: string }[] = [
  { title: "Автодороги", prefix: "Avto" },
  { title: "Железные дороги", prefix: "JD" },
  { title: "Аэропорты", prefix: "Aero" },
];

export function wallOutcomeLabel(outcome: string): string {
  switch (outcome) {
    case "accepted":
      return "Выполнено";
    case "rejected":
      return "Отклонено агентом стены";
    case "unreachable":
      return "Видеостена недоступна";
    default:
      return outcome;
  }
}

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
