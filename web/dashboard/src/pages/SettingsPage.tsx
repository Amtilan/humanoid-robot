import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";

export function SettingsPage() {
  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Current runtime configuration. Read-only for now; secrets are redacted.
        </p>
      </div>

      {settingsQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : settingsQuery.error ? (
        <p className="text-sm text-red-500">{String(settingsQuery.error)}</p>
      ) : (
        <pre className="max-h-[70vh] overflow-auto rounded-lg border border-border bg-background/40 p-4 font-mono text-xs">
          {JSON.stringify(settingsQuery.data.settings, null, 2)}
        </pre>
      )}
    </div>
  );
}
