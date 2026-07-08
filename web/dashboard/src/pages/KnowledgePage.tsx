import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type IngestJobStatus } from "../api/client";

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({
    queryKey: ["knowledge", "status"],
    queryFn: api.knowledgeStatus,
    refetchInterval: 5_000,
  });
  const jobsQuery = useQuery({
    queryKey: ["knowledge", "ingest-jobs"],
    queryFn: api.ingestJobs,
    refetchInterval: 2_000,
  });

  const [directory, setDirectory] = useState("/var/lib/humanoid-robot/kb");
  const [configPath, setConfigPath] = useState("/etc/humanoid-robot/ingest.yaml");

  const startIngest = useMutation({
    mutationFn: () => api.startIngest({ directory, config_path: configPath }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge"] }),
  });

  const deleteSource = useMutation({
    mutationFn: api.deleteKnowledgeSource,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge", "status"] }),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Knowledge base</h1>
        <p className="text-sm text-muted-foreground">
          Sources indexed in the vector store, and operator-triggered ingest jobs.
        </p>
      </div>

      {statusQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : statusQuery.error ? (
        <p className="text-sm text-red-500">{String(statusQuery.error)}</p>
      ) : !statusQuery.data.configured ? (
        <div className="rounded-lg border border-border bg-background/40 p-6 text-sm text-muted-foreground">
          No vector store is bound to cortex-core. Install the qdrant runtime
          extra and configure it in <code>deploy/config/rag.yaml</code>.
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-background/40">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-2">Source id</th>
                <th className="px-4 py-2">Chunks</th>
                <th className="px-4 py-2">Sample</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {statusQuery.data.sources.length === 0 ? (
                <tr>
                  <td className="px-4 py-3 text-muted-foreground" colSpan={4}>
                    No documents ingested yet.
                  </td>
                </tr>
              ) : (
                statusQuery.data.sources.map((source) => (
                  <tr
                    key={source.source_id}
                    className="border-b border-border/50 last:border-none"
                  >
                    <td className="px-4 py-2 font-mono text-[10px]">
                      {source.source_id.substring(0, 16)}…
                    </td>
                    <td className="px-4 py-2">{source.chunk_count}</td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      {source.sample_title ?? "—"}
                    </td>
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        onClick={() => deleteSource.mutate(source.source_id)}
                        disabled={deleteSource.isPending}
                        className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-1 text-xs text-red-400 hover:bg-red-500/20 disabled:opacity-50"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="rounded-lg border border-border bg-background/40 p-4">
        <h2 className="text-sm font-semibold">Trigger ingest job</h2>
        <p className="pb-3 text-xs text-muted-foreground">
          Runs <code>cortex-ingest run</code> as a subprocess on the robot.
        </p>
        <div className="space-y-2">
          <label className="block text-xs uppercase text-muted-foreground">Directory</label>
          <input
            type="text"
            value={directory}
            onChange={(e) => setDirectory(e.target.value)}
            className="w-full rounded-md border border-border bg-background/60 px-3 py-1 text-sm"
          />
          <label className="block text-xs uppercase text-muted-foreground">Config path</label>
          <input
            type="text"
            value={configPath}
            onChange={(e) => setConfigPath(e.target.value)}
            className="w-full rounded-md border border-border bg-background/60 px-3 py-1 text-sm"
          />
          <button
            type="button"
            onClick={() => startIngest.mutate()}
            disabled={startIngest.isPending}
            className="mt-2 rounded-md bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
          >
            {startIngest.isPending ? "Starting…" : "Start ingest"}
          </button>
          {startIngest.error && (
            <p className="text-xs text-red-500">{String(startIngest.error)}</p>
          )}
        </div>
      </div>

      <div>
        <h2 className="pb-2 text-sm font-semibold">Recent jobs</h2>
        <div className="space-y-2">
          {jobsQuery.data && jobsQuery.data.length > 0 ? (
            jobsQuery.data.map((job) => <JobCard key={job.id} job={job} />)
          ) : (
            <p className="text-xs text-muted-foreground">No jobs recorded yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function JobCard({ job }: { job: IngestJobStatus }) {
  const stateColor: Record<IngestJobStatus["state"], string> = {
    running: "bg-blue-500/10 text-blue-400",
    succeeded: "bg-emerald-500/10 text-emerald-400",
    failed: "bg-red-500/10 text-red-400",
  };
  return (
    <div className="rounded-lg border border-border bg-background/40 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div className="font-mono">{job.id}</div>
        <span className={`rounded-full px-2 py-0.5 ${stateColor[job.state]}`}>
          {job.state}
        </span>
      </div>
      <div className="mt-1 text-muted-foreground">{job.directory}</div>
      {job.stderr_tail && (
        <pre className="mt-2 max-h-32 overflow-auto rounded bg-background/60 p-2 font-mono text-[10px] text-red-400">
          {job.stderr_tail}
        </pre>
      )}
    </div>
  );
}
