import { NavLink, Route, Routes } from "react-router-dom";
import {
  Activity,
  BookOpen,
  Bot,
  Boxes,
  Gauge,
  LayoutDashboard,
  Mic,
  Puzzle,
  Radio,
  Settings as SettingsIcon,
  Sparkles,
} from "lucide-react";

import { AdaptersPage } from "./pages/AdaptersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { EventsPage } from "./pages/EventsPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { PluginsPage } from "./pages/PluginsPage";
import { QaPage } from "./pages/QaPage";
import { RobotPage } from "./pages/RobotPage";
import { SettingsPage } from "./pages/SettingsPage";
import { VoiceSessionsPage } from "./pages/VoiceSessionsPage";
import { MicActivity } from "./lib/micActivity";
import { cn } from "./lib/cn";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/robot", label: "Robot", icon: Bot },
  { to: "/voice", label: "Voice", icon: Mic },
  { to: "/knowledge", label: "Knowledge", icon: BookOpen },
  { to: "/qa", label: "QA test", icon: Sparkles },
  { to: "/adapters", label: "Adapters", icon: Boxes },
  { to: "/plugins", label: "Plugins", icon: Puzzle },
  { to: "/events", label: "Events", icon: Radio },
  { to: "/diagnostics", label: "Diagnostics", icon: Gauge },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function App() {
  return (
    <div className="flex h-full">
      <aside className="flex w-64 flex-col border-r border-border bg-background/50 p-4">
        <div className="flex items-center gap-2 pb-4">
          <Activity className="h-5 w-5 text-primary" />
          <span className="text-sm font-semibold">humanoid-robot</span>
        </div>
        <div className="pb-4">
          <MicActivity />
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
          <Route path="/robot" element={<RobotPage />} />
          <Route path="/voice" element={<VoiceSessionsPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/qa" element={<QaPage />} />
          <Route path="/adapters" element={<AdaptersPage />} />
          <Route path="/plugins" element={<PluginsPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/diagnostics" element={<DiagnosticsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
