import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";

export function DashboardPage() {
  const infoQuery = useQuery({ queryKey: ["info"], queryFn: api.info });
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 5_000,
  });
  const groupsQuery = useQuery({ queryKey: ["groups"], queryFn: api.adapterGroups });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Live status of the humanoid-robot platform.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card title="Service">
          {infoQuery.isPending ? (
            <Placeholder />
          ) : infoQuery.error ? (
            <ErrorBox message={String(infoQuery.error)} />
          ) : (
            <dl className="space-y-1 text-sm">
              <Row label="Service" value={infoQuery.data.service} />
              <Row label="Version" value={infoQuery.data.version} />
              <Row label="Environment" value={infoQuery.data.environment} />
            </dl>
          )}
        </Card>

        <Card title="Health">
          {healthQuery.isPending ? (
            <Placeholder />
          ) : healthQuery.error ? (
            <ErrorBox message={String(healthQuery.error)} />
          ) : (
            <div className="flex items-center gap-2 text-sm">
              <span
                className={
                  healthQuery.data.status === "ready"
                    ? "inline-block h-2 w-2 rounded-full bg-emerald-500"
                    : "inline-block h-2 w-2 rounded-full bg-red-500"
                }
              />
              <span>{healthQuery.data.status}</span>
            </div>
          )}
        </Card>

        <Card title="Registered adapter groups">
          {groupsQuery.isPending ? (
            <Placeholder />
          ) : groupsQuery.error ? (
            <ErrorBox message={String(groupsQuery.error)} />
          ) : (
            <p className="text-sm text-muted-foreground">
              {groupsQuery.data.groups.length} groups
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-4">
      <h2 className="pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function Placeholder() {
  return <div className="h-4 w-full animate-pulse rounded bg-muted" />;
}

function ErrorBox({ message }: { message: string }) {
  return <p className="text-sm text-red-500">{message}</p>;
}
