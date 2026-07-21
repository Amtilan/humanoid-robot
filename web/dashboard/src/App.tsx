import { NavLink, Outlet, Route, Routes, Link } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  BookOpen,
  Bot,
  Boxes,
  ChevronDown,
  Gauge,
  Hand,
  Home,
  LayoutDashboard,
  Mic,
  Puzzle,
  Radio,
  Settings as SettingsIcon,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

import { AdaptersPage } from "./pages/AdaptersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { EventsPage } from "./pages/EventsPage";
import { HomePage } from "./pages/HomePage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { MorePage } from "./pages/MorePage";
import { GuardPage } from "./pages/GuardPage";
import { MotionsPage } from "./pages/MotionsPage";
import { PluginsPage } from "./pages/PluginsPage";
import { QaPage } from "./pages/QaPage";
import { RobotPage } from "./pages/RobotPage";
import { SafetyPage } from "./pages/SafetyPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StatusPage } from "./pages/StatusPage";
import { VoiceSessionsPage } from "./pages/VoiceSessionsPage";
import { TabBar } from "./components/TabBar";
import { MicActivity } from "./lib/micActivity";
import { cn } from "./lib/cn";

const PRIMARY_NAV = [
  { to: "/", label: "Главная", icon: Home },
  { to: "/motions", label: "Движения", icon: Hand },
  { to: "/status", label: "Состояние", icon: Activity },
];

const DEV_NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/safety", label: "Safety", icon: ShieldAlert },
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

/** Owner-facing app shell: content + bottom tab bar (all viewports). */
function PrimaryLayout() {
  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        <Outlet />
      </div>
      <TabBar />
    </div>
  );
}

/** Developer console shell: sidebar on desktop, back-bar on mobile. */
function ConsoleLayout() {
  return (
    <div className="flex h-full flex-col md:flex-row">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3 md:hidden">
        <Link
          to="/more"
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> Назад
        </Link>
        <span className="ml-auto text-xs text-muted-foreground">Для разработчика</span>
      </div>

      <aside className="hidden w-64 flex-col border-r border-border bg-background/50 p-4 md:flex">
        <div className="flex items-center gap-2 pb-4">
          <Activity className="h-5 w-5 text-primary" />
          <span className="text-sm font-semibold">Слуга</span>
        </div>
        <div className="pb-4">
          <MicActivity />
        </div>
        <nav className="flex flex-col gap-1">
          {PRIMARY_NAV.map((item) => (
            <SideLink key={item.to} {...item} />
          ))}
        </nav>
        <details className="mt-4" open>
          <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-2 text-xs uppercase tracking-wide text-muted-foreground">
            Для разработчика
            <ChevronDown className="h-3.5 w-3.5" />
          </summary>
          <nav className="mt-1 flex flex-col gap-1">
            {DEV_NAV.map((item) => (
              <SideLink key={item.to} {...item} />
            ))}
          </nav>
        </details>
      </aside>

      <main className="min-h-0 flex-1 overflow-auto p-4 md:p-8">
        <Outlet />
      </main>
    </div>
  );
}

function SideLink({ to, label, icon: Icon }: { to: string; label: string; icon: typeof Home }) {
  return (
    <NavLink
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
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<PrimaryLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/motions" element={<MotionsPage />} />
        <Route path="/status" element={<StatusPage />} />
        <Route path="/guard" element={<GuardPage />} />
        <Route path="/more" element={<MorePage />} />
      </Route>
      <Route element={<ConsoleLayout />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/safety" element={<SafetyPage />} />
        <Route path="/robot" element={<RobotPage />} />
        <Route path="/voice" element={<VoiceSessionsPage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/qa" element={<QaPage />} />
        <Route path="/adapters" element={<AdaptersPage />} />
        <Route path="/plugins" element={<PluginsPage />} />
        <Route path="/events" element={<EventsPage />} />
        <Route path="/diagnostics" element={<DiagnosticsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
