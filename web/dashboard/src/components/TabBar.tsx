import { useQuery } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { Activity, Hand, Home, Menu, Shield } from "lucide-react";

import { api } from "../api/client";
import { cn } from "../lib/cn";

const BASE_TABS = [
  { to: "/", label: "Главная", icon: Home },
  { to: "/motions", label: "Движения", icon: Hand },
  { to: "/status", label: "Состояние", icon: Activity },
];

// Role-specific tabs: the guard customer sees the visit journal, the
// presenter customer never does (and vice versa for future presenter tabs).
const GUARD_TAB = { to: "/guard", label: "Охрана", icon: Shield };
const MORE_TAB = { to: "/more", label: "Ещё", icon: Menu };

/** Bottom tab bar for the owner-facing screens (app-like on every viewport). */
export function TabBar() {
  const info = useQuery({ queryKey: ["system", "info"], queryFn: api.info, staleTime: 60_000 });
  const role = info.data?.role ?? "generic";
  const tabs = [...BASE_TABS, ...(role === "guard" ? [GUARD_TAB] : []), MORE_TAB];
  return (
    <nav
      className={cn(
        "grid shrink-0 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur",
        tabs.length === 5 ? "grid-cols-5" : "grid-cols-4",
      )}
    >
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
