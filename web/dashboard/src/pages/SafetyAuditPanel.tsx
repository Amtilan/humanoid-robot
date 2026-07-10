import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { useEventSubscription } from "../lib/eventStream";

const AUDIT_PREFIXES = [
  { label: "all", value: "" },
  { label: "safety.", value: "safety." },
  { label: "safety.estop.", value: "safety.estop." },
  { label: "safety.command.", value: "safety.command." },
  { label: "robot.command.", value: "robot.command." },
];

const AUDIT_STAY_SUBJECTS = new Set([
  "safety.estop.engaged",
  "safety.estop.released",
  "safety.command.denied",
  "safety.command.timeout",
]);

const isAuditRefreshSubject = (subject: string) => AUDIT_STAY_SUBJECTS.has(subject);

export function AuditPanel() {
  const client = useQueryClient();
  const [prefix, setPrefix] = useState("safety.");
  const query = useQuery({
    queryKey: ["safety", "audit", prefix],
    queryFn: () => api.safetyAudit({ subject_prefix: prefix || undefined, limit: 50 }),
    refetchInterval: 15_000,
  });

  useEventSubscription(isAuditRefreshSubject, () => {
    client.invalidateQueries({ queryKey: ["safety", "audit"] });
  });

  return (
    <div className="rounded-lg border border-border bg-background/40 p-4">
      <div className="flex items-baseline justify-between pb-3">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Audit log{" "}
          {query.data && (
            <span className="ml-1 text-muted-foreground/60">
              ({query.data.records.length} of {query.data.total})
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-1">
          {AUDIT_PREFIXES.map((p) => (
            <button
              key={p.value || "all"}
              type="button"
              onClick={() => setPrefix(p.value)}
              className={
                prefix === p.value
                  ? "rounded border border-primary bg-primary/10 px-2 py-0.5 text-[10px] text-primary"
                  : "rounded border border-border bg-background/60 px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-accent"
              }
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {query.isPending ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : query.error ? (
        <p className="text-xs text-red-500">{String(query.error)}</p>
      ) : query.data && query.data.records.length === 0 ? (
        <p className="text-xs text-muted-foreground">No records for this filter.</p>
      ) : (
        <ul className="max-h-72 space-y-1 overflow-auto pr-1">
          {query.data?.records.map((r) => (
            <li
              key={r.id}
              className="flex items-start gap-3 rounded border border-border/40 bg-background/60 px-2 py-1 text-xs"
            >
              <span className="w-20 shrink-0 font-mono text-[10px] text-muted-foreground">
                {r.occurred_at.substring(11, 19)}
              </span>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${styleFor(r.subject)}`}
              >
                {r.subject}
              </span>
              <span className="min-w-0 truncate text-muted-foreground">
                {JSON.stringify(r.payload)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function styleFor(subject: string): string {
  if (subject === "safety.estop.engaged") return "bg-red-500/15 text-red-300";
  if (subject === "safety.estop.released") return "bg-emerald-500/15 text-emerald-300";
  if (subject === "safety.command.denied") return "bg-yellow-500/15 text-yellow-300";
  if (subject === "safety.command.timeout") return "bg-orange-500/15 text-orange-300";
  if (subject === "safety.command.forwarded") return "bg-emerald-500/15 text-emerald-300";
  if (subject.startsWith("robot.command.")) return "bg-sky-500/15 text-sky-300";
  return "bg-muted text-muted-foreground";
}
