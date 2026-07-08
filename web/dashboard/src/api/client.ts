async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} for ${url}`);
  }
  return (await response.json()) as T;
}

async function postJson<T, B = unknown>(url: string, body?: B): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return (await response.json()) as T;
}

// -----------------------------------------------------------------------
// Types mirroring the FastAPI models. Keep them in sync manually until we
// wire up an OpenAPI-generated client.
// -----------------------------------------------------------------------

export interface ServiceInfo {
  service: string;
  version: string;
  environment: string;
}

export interface HealthResponse {
  status: string;
}

export interface AdapterEntryInfo {
  name: string;
  distribution: string | null;
  version: string | null;
  target: string;
}

export interface AdapterListResponse {
  group: string;
  entries: AdapterEntryInfo[];
}

export interface AdapterGroupsResponse {
  groups: string[];
}

export interface PluginManifest {
  name: string;
  version: string;
  description: string;
  author: string;
  permissions: string[];
  subscribes: string[];
}

export interface PluginStatus {
  name: string;
  distribution: string | null;
  version: string | null;
  is_active: boolean;
  manifest: PluginManifest | null;
}

export interface RobotModel {
  vendor: string;
  family: string;
  variant: string;
  slug?: string;
}

export interface RobotManifest {
  adapter_name: string;
  adapter_version: string;
  robot_model: RobotModel;
  capabilities: Record<string, unknown>;
  transport_hint: string | null;
  network_interface: string | null;
}

export interface RobotManifestSnapshot {
  adapter_name: string;
  adapter_version: string;
  manifest: RobotManifest;
  observed_at: string;
}

export interface RagAskRequest {
  question: string;
  language?: "ru" | "en" | "und";
  timeout_s?: number;
}

export interface RagAskResponse {
  session_id: string;
  outcome: "answer" | "rejected" | "timeout";
  text: string | null;
  fallback_text: string | null;
  reason: string | null;
  citations: { chunk_id: string; quote: string }[];
}

export interface SettingsResponse {
  settings: Record<string, unknown>;
}

export interface KnowledgeSourceSummary {
  source_id: string;
  chunk_count: number;
  sample_title: string | null;
}

export interface KnowledgeStatusResponse {
  configured: boolean;
  sources: KnowledgeSourceSummary[];
}

export interface IngestJobStatus {
  id: string;
  directory: string;
  state: "running" | "succeeded" | "failed";
  started_at: string;
  finished_at: string | null;
  exit_code: number | null;
  stdout_tail: string | null;
  stderr_tail: string | null;
}

async function deleteJson(url: string): Promise<void> {
  const response = await fetch(url, { method: "DELETE" });
  if (!response.ok && response.status !== 204) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
}

export const api = {
  info: () => getJson<ServiceInfo>("/api/v1/system/info"),
  health: () => getJson<HealthResponse>("/api/v1/system/health/ready"),
  adapterGroups: () => getJson<AdapterGroupsResponse>("/api/v1/adapters/groups"),
  adaptersInGroup: (group: string) =>
    getJson<AdapterListResponse>(`/api/v1/adapters/${encodeURIComponent(group)}`),
  plugins: () => getJson<PluginStatus[]>("/api/v1/plugins/"),
  activatePlugin: (name: string) =>
    postJson<PluginStatus>(`/api/v1/plugins/${encodeURIComponent(name)}/activate`),
  deactivatePlugin: (name: string) =>
    postJson<PluginStatus>(`/api/v1/plugins/${encodeURIComponent(name)}/deactivate`),
  robotManifests: () => getJson<RobotManifestSnapshot[]>("/api/v1/robot/manifests"),
  ragAsk: (body: RagAskRequest) => postJson<RagAskResponse, RagAskRequest>("/api/v1/rag/ask", body),
  settings: () => getJson<SettingsResponse>("/api/v1/settings/"),
  knowledgeStatus: () => getJson<KnowledgeStatusResponse>("/api/v1/knowledge/status"),
  deleteKnowledgeSource: (sourceId: string) =>
    deleteJson(`/api/v1/knowledge/sources/${encodeURIComponent(sourceId)}`),
  startIngest: (body: { directory: string; config_path: string }) =>
    postJson<IngestJobStatus, typeof body>("/api/v1/knowledge/ingest-jobs", body),
  ingestJobs: () => getJson<IngestJobStatus[]>("/api/v1/knowledge/ingest-jobs"),
};
