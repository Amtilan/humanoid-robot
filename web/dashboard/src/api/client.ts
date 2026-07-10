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

export interface CpuStats {
  percent: number;
  per_core_percent: number[];
  load_avg_1m: number;
  load_avg_5m: number;
  load_avg_15m: number;
  core_count: number;
}

export interface MemoryStats {
  total_bytes: number;
  used_bytes: number;
  available_bytes: number;
  percent: number;
  swap_total_bytes: number;
  swap_used_bytes: number;
}

export interface DiskStats {
  path: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  percent: number;
}

export interface HostDiagnostics {
  uptime_s: number;
  cpu: CpuStats;
  memory: MemoryStats;
  disks: DiskStats[];
}

export interface GpuStats {
  supported: boolean;
  gpu_percent: number | null;
  ram_used_bytes: number | null;
  ram_total_bytes: number | null;
  temperature_c: number | null;
  power_w: number | null;
  detail: string | null;
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
  robotCommand: (body: { capability: string; payload: Record<string, unknown> }) =>
    postJson<{ command_id: string }, typeof body>("/api/v1/robot/commands", body),
  ragAsk: (body: RagAskRequest) => postJson<RagAskResponse, RagAskRequest>("/api/v1/rag/ask", body),
  ragAskStart: (body: RagAskRequest) =>
    postJson<{ session_id: string }, RagAskRequest>("/api/v1/rag/ask/start", body),
  settings: () => getJson<SettingsResponse>("/api/v1/settings/"),
  knowledgeStatus: () => getJson<KnowledgeStatusResponse>("/api/v1/knowledge/status"),
  deleteKnowledgeSource: (sourceId: string) =>
    deleteJson(`/api/v1/knowledge/sources/${encodeURIComponent(sourceId)}`),
  startIngest: (body: { directory: string; config_path: string }) =>
    postJson<IngestJobStatus, typeof body>("/api/v1/knowledge/ingest-jobs", body),
  ingestJobs: () => getJson<IngestJobStatus[]>("/api/v1/knowledge/ingest-jobs"),
  diagnosticsHost: () => getJson<HostDiagnostics>("/api/v1/diagnostics/host"),
  diagnosticsGpu: () => getJson<GpuStats>("/api/v1/diagnostics/gpu"),
  safetyStatus: () => getJson<SafetyStatus>("/api/v1/safety/status"),
  safetyEngage: (body: { actor: string; reason?: string }) =>
    postJson<{ engaged: boolean; changed: boolean }, typeof body>(
      "/api/v1/safety/estop/engage",
      body,
    ),
  safetyRelease: (body: { actor: string }) =>
    postJson<{ engaged: boolean; changed: boolean }, typeof body>(
      "/api/v1/safety/estop/release",
      body,
    ),
  safetyHeartbeat: (body: { actor: string }) =>
    postJson<{ accepted: boolean }, typeof body>(
      "/api/v1/safety/watchdog/heartbeat",
      body,
    ),
};

export interface SafetyStatus {
  estop_engaged: boolean;
  allowed_capabilities: string[];
  rate_limit_window_s: number;
  rate_limit_max_events: number;
  watchdog_timeout_s: number;
  watchdog_live: boolean;
  watchdog_seconds_since_heartbeat: number | null;
  command_timeout_s: number;
  pending_command_count: number;
  pending_command_ids: string[];
}
