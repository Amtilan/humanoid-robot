import { NavLink } from "react-router-dom";
import { Activity, Hand, Home, Menu } from "lucide-react";

import { cn } from "../lib/cn";

const tabs = [
  { to: "/", label: "Главная", icon: Home },
  { to: "/motions", label: "Движения", icon: Hand },
  { to: "/status", label: "Состояние", icon: Activity },
  { to: "/more", label: "Ещё", icon: Menu },
];

/** Bottom tab bar for the owner-facing screens (app-like on every viewport). */
export function TabBar() {
  return (
    <nav className="grid shrink-0 grid-cols-4 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
      {tabs.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) =>
            cn(
              "flex h-16 flex-col items-center justify-center gap-1",
              isActive ? "text-foreground" : "text-muted-foreground",
            )
          }
        >
          <Icon className="h-6 w-6" />
          <span className="text-[11px] font-medium">{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
