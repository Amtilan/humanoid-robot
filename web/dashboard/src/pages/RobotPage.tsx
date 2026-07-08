import { useQuery } from "@tanstack/react-query";

import { api, type RobotManifestSnapshot } from "../api/client";

export function RobotPage() {
  const manifestsQuery = useQuery({
    queryKey: ["robot", "manifests"],
    queryFn: api.robotManifests,
    refetchInterval: 5_000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Robot</h1>
        <p className="text-sm text-muted-foreground">
          Latest manifest reported by each adapter on the bus.
        </p>
      </div>

      {manifestsQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : manifestsQuery.error ? (
        <p className="text-sm text-red-500">{String(manifestsQuery.error)}</p>
      ) : manifestsQuery.data.length === 0 ? (
        <div className="rounded-lg border border-border bg-background/40 p-6 text-sm text-muted-foreground">
          No robot adapter has reported a manifest yet. Start
          <code className="mx-1 rounded bg-muted px-1">cortex-robot-adapter</code>
          to populate this view.
        </div>
      ) : (
        <div className="space-y-4">
          {manifestsQuery.data.map((snapshot) => (
            <ManifestCard key={snapshot.adapter_name} snapshot={snapshot} />
          ))}
        </div>
      )}
    </div>
  );
}

function ManifestCard({ snapshot }: { snapshot: RobotManifestSnapshot }) {
  const { manifest } = snapshot;
  return (
    <div className="rounded-lg border border-border bg-background/40 p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            {manifest.robot_model.vendor} {manifest.robot_model.family}{" "}
            {manifest.robot_model.variant}
          </h2>
          <p className="text-xs text-muted-foreground">
            adapter <code>{snapshot.adapter_name}</code>@{snapshot.adapter_version}
          </p>
        </div>
        <div className="text-xs text-muted-foreground">
          observed {new Date(snapshot.observed_at).toLocaleTimeString()}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-4 text-xs md:grid-cols-4">
        <Info label="transport" value={manifest.transport_hint ?? "—"} />
        <Info label="interface" value={manifest.network_interface ?? "—"} />
      </div>

      <pre className="mt-4 max-h-64 overflow-auto rounded bg-background/60 p-3 font-mono text-[10px] text-muted-foreground">
        {JSON.stringify(manifest.capabilities, null, 2)}
      </pre>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="font-mono">{value}</div>
    </div>
  );
}
