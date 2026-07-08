import { NavLink, Route, Routes } from "react-router-dom";
import { Activity, Boxes, LayoutDashboard, Radio } from "lucide-react";

import { AdaptersPage } from "./pages/AdaptersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { EventsPage } from "./pages/EventsPage";
import { cn } from "./lib/cn";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/adapters", label: "Adapters", icon: Boxes },
  { to: "/events", label: "Events", icon: Radio },
];

export function App() {
  return (
    <div className="flex h-full">
      <aside className="flex w-64 flex-col border-r border-border bg-background/50 p-4">
        <div className="flex items-center gap-2 pb-6">
          <Activity className="h-5 w-5 text-primary" />
          <span className="text-sm font-semibold">humanoid-robot</span>
        </div>
        <nav className="flex flex-col gap-1">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                  isActive && "bg-accent text-accent-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-8">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/adapters" element={<AdaptersPage />} />
          <Route path="/events" element={<EventsPage />} />
        </Routes>
      </main>
    </div>
  );
}
