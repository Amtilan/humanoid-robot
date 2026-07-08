import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type PluginStatus } from "../api/client";

export function PluginsPage() {
  const queryClient = useQueryClient();
  const pluginsQuery = useQuery({ queryKey: ["plugins"], queryFn: api.plugins });

  const activate = useMutation({
    mutationFn: api.activatePlugin,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugins"] }),
  });
  const deactivate = useMutation({
    mutationFn: api.deactivatePlugin,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugins"] }),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Plugins</h1>
        <p className="text-sm text-muted-foreground">
          Activate or deactivate installed plugins at runtime.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-background/40">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Distribution</th>
              <th className="px-4 py-2">Version</th>
              <th className="px-4 py-2">State</th>
              <th className="px-4 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {pluginsQuery.isPending ? (
              <tr>
                <td className="px-4 py-3 text-muted-foreground" colSpan={5}>
                  Loading…
                </td>
              </tr>
            ) : pluginsQuery.error ? (
              <tr>
                <td className="px-4 py-3 text-red-500" colSpan={5}>
                  {String(pluginsQuery.error)}
                </td>
              </tr>
            ) : pluginsQuery.data.length === 0 ? (
              <tr>
                <td className="px-4 py-3 text-muted-foreground" colSpan={5}>
                  No plugins registered.
                </td>
              </tr>
            ) : (
              pluginsQuery.data.map((plugin) => (
                <PluginRow
                  key={plugin.name}
                  plugin={plugin}
                  onActivate={() => activate.mutate(plugin.name)}
                  onDeactivate={() => deactivate.mutate(plugin.name)}
                  pending={activate.isPending || deactivate.isPending}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {(activate.error || deactivate.error) && (
        <p className="text-sm text-red-500">
          {String(activate.error ?? deactivate.error)}
        </p>
      )}
    </div>
  );
}

interface RowProps {
  plugin: PluginStatus;
  onActivate: () => void;
  onDeactivate: () => void;
  pending: boolean;
}

function PluginRow({ plugin, onActivate, onDeactivate, pending }: RowProps) {
  return (
    <tr className="border-b border-border/50 last:border-none">
      <td className="px-4 py-2 font-medium">{plugin.name}</td>
      <td className="px-4 py-2 text-muted-foreground">{plugin.distribution ?? "—"}</td>
      <td className="px-4 py-2 text-muted-foreground">{plugin.version ?? "—"}</td>
      <td className="px-4 py-2">
        <span
          className={
            plugin.is_active
              ? "inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-400"
              : "inline-flex items-center gap-2 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
          }
        >
          <span
            className={
              plugin.is_active
                ? "inline-block h-1.5 w-1.5 rounded-full bg-emerald-500"
                : "inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground"
            }
          />
          {plugin.is_active ? "active" : "idle"}
        </span>
      </td>
      <td className="px-4 py-2">
        {plugin.is_active ? (
          <button
            type="button"
            onClick={onDeactivate}
            disabled={pending}
            className="rounded-md border border-border bg-background/60 px-3 py-1 text-xs hover:bg-accent disabled:opacity-50"
          >
            Deactivate
          </button>
        ) : (
          <button
            type="button"
            onClick={onActivate}
            disabled={pending}
            className="rounded-md border border-border bg-primary/10 px-3 py-1 text-xs text-primary hover:bg-primary/20 disabled:opacity-50"
          >
            Activate
          </button>
        )}
      </td>
    </tr>
  );
}
