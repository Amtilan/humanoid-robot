import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";

export function AdaptersPage() {
  const groupsQuery = useQuery({ queryKey: ["groups"], queryFn: api.adapterGroups });
  const [selected, setSelected] = useState<string | null>(null);

  const activeGroup = selected ?? groupsQuery.data?.groups[0] ?? null;
  const listQuery = useQuery({
    queryKey: ["adapters", activeGroup],
    queryFn: () => (activeGroup ? api.adaptersInGroup(activeGroup) : Promise.reject()),
    enabled: !!activeGroup,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Adapters</h1>
        <p className="text-sm text-muted-foreground">
          Everything registered under the platform's entry-point groups.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {groupsQuery.data?.groups.map((group) => (
          <button
            type="button"
            key={group}
            onClick={() => setSelected(group)}
            className={
              (activeGroup === group
                ? "bg-accent text-accent-foreground"
                : "bg-background/40 text-muted-foreground hover:bg-accent/60") +
              " rounded-md border border-border px-3 py-1 text-xs"
            }
          >
            {group.replace("humanoid_robot.", "")}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-border bg-background/40">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Distribution</th>
              <th className="px-4 py-2">Version</th>
              <th className="px-4 py-2">Target</th>
            </tr>
          </thead>
          <tbody>
            {listQuery.isPending && activeGroup ? (
              <tr>
                <td className="px-4 py-3 text-muted-foreground" colSpan={4}>
                  Loading…
                </td>
              </tr>
            ) : listQuery.data ? (
              listQuery.data.entries.map((entry) => (
                <tr key={entry.name} className="border-b border-border/50 last:border-none">
                  <td className="px-4 py-2 font-medium">{entry.name}</td>
                  <td className="px-4 py-2 text-muted-foreground">{entry.distribution}</td>
                  <td className="px-4 py-2 text-muted-foreground">{entry.version}</td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">{entry.target}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-4 py-3 text-muted-foreground" colSpan={4}>
                  No adapters yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
