import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ChevronRight, KeyRound, Wrench } from "lucide-react";

import { api, setAuthToken } from "../api/client";
import { LlmSwitcher } from "../components/LlmSwitcher";

const DEV_PAGES = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/safety", label: "Safety" },
  { to: "/robot", label: "Robot" },
  { to: "/voice", label: "Voice" },
  { to: "/knowledge", label: "Knowledge" },
  { to: "/qa", label: "QA test" },
  { to: "/adapters", label: "Adapters" },
  { to: "/plugins", label: "Plugins" },
  { to: "/events", label: "Events" },
  { to: "/diagnostics", label: "Diagnostics" },
  { to: "/settings", label: "Settings" },
];

export function MorePage() {
  const info = useQuery({ queryKey: ["system", "info"], queryFn: api.info });

  return (
    <div className="mx-auto h-full w-full max-w-lg space-y-4 overflow-y-auto p-4">
      <h1 className="text-2xl font-semibold">Ещё</h1>

      <section className="rounded-xl border border-border bg-background/40 p-4">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">О роботе</div>
        <div className="mt-2 space-y-1 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Имя</span>
            <span>Слуга (Unitree G1)</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Версия ПО</span>
            <span>{info.data ? `${info.data.version} (${info.data.environment})` : "…"}</span>
          </div>
        </div>
      </section>

      <LlmSwitcher />

      <button
        type="button"
        onClick={() => {
          setAuthToken(null);
          location.reload();
        }}
        className="flex min-h-14 w-full items-center gap-3 rounded-xl border border-border bg-background/40 px-4 text-left text-sm hover:bg-accent"
      >
        <KeyRound className="h-5 w-5 text-muted-foreground" />
        <span>Сменить токен доступа</span>
        <ChevronRight className="ml-auto h-4 w-4 text-muted-foreground" />
      </button>

      <details className="rounded-xl border border-border bg-background/40">
        <summary className="flex min-h-14 cursor-pointer select-none items-center gap-3 px-4 text-sm">
          <Wrench className="h-5 w-5 text-muted-foreground" />
          <span>Для разработчика</span>
          <ChevronRight className="ml-auto h-4 w-4 text-muted-foreground" />
        </summary>
        <div className="border-t border-border">
          {DEV_PAGES.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              className="flex min-h-12 items-center px-4 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              {label}
            </Link>
          ))}
        </div>
      </details>
    </div>
  );
}
