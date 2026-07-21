// --- Bearer token wiring ----------------------------------------------
// The operator saves the token via the "Sign in" prompt (auth.ts). This
// module keeps every fetch in step and exposes an unauthorized() signal
// so React screens can pop the prompt when the API starts returning 401.

const AUTH_STORAGE_KEY = "humanoid-robot.auth.token";
let cachedToken: string | null = null;
const unauthorizedListeners = new Set<() => void>();

export function getAuthToken(): string | null {
  if (cachedToken !== null) return cachedToken;
  try {
    cachedToken = localStorage.getItem(AUTH_STORAGE_KEY);
  } catch {
    cachedToken = null;
  }
  return cachedToken;
}

export function setAuthToken(token: string | null): void {
  cachedToken = token;
  try {
    if (token) localStorage.setItem(AUTH_STORAGE_KEY, token);
    else localStorage.removeItem(AUTH_STORAGE_KEY);
  } catch {
    // localStorage may be blocked; the in-memory cache still works for
    // this session.
  }
}

export function onUnauthorized(fn: () => void): () => void {
  unauthorizedListeners.add(fn);
  return () => {
    unauthorizedListeners.delete(fn);
  };
}

function fireUnauthorized(): void {
  for (const fn of unauthorizedListeners) {
    try {
      fn();
    } catch (err) {
      console.error("unauthorized listener threw", err);
    }
  }
}

function authHeader(): Record<string, string> {
  const token = getAuthToken();
  return token ? { authorization: `Bearer ${token}` } : {};
}

// Camera endpoints are consumed by <img>/<video> tags, which can't set an
// Authorization header — so the token rides as ?token= (core accepts either).
// These return URL strings rather than promises for that reason.
function withToken(path: string): string {
  const token = getAuthToken();
  return token ? `${path}?token=${encodeURIComponent(token)}` : path;
}

export function robotCameraStreamUrl(cameraId = "front"): string {
  return withToken(`/api/v1/robot/camera/${encodeURIComponent(cameraId)}/stream`);
}

export function robotCameraSnapshotUrl(cameraId = "front"): string {
  return withToken(`/api/v1/robot/camera/${encodeURIComponent(cameraId)}/snapshot`);
}

// Live mic monitor (streaming WAV). source "usb" = the ASR microphone the
// robot actually listens to; "builtin" = the quiet G1 head mic (server-side
// ?gain= amplifies it).
export type MicSource = "usb" | "builtin";

export function robotMicStreamUrl(gain: number, source: MicSource = "usb"): string {
  const qs = new URLSearchParams({ gain: String(gain), source });
  const token = getAuthToken();
  if (token) qs.set("token", token);
  return `/api/v1/robot/mic/stream?${qs.toString()}`;
}

async function guard<T>(response: Response, url: string, fallback: () => Promise<T>): Promise<T> {
  if (response.status === 401) {
    fireUnauthorized();
    throw new Error(`401 unauthorized for ${url}`);
  }
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`${response.status} ${response.statusText}: ${detail || url}`);
  }
  return fallback();
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: { accept: "application/json", ...authHeader() },
  });
  return guard(response, url, async () => (await response.json()) as T);
}

async function postJson<T, B = unknown>(url: string, body?: B): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
      ...authHeader(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return guard(response, url, async () => (await response.json()) as T);
}

async function deleteJson<T = void>(url: string): Promise<T> {
  const response = await fetch(url, {
    method: "DELETE",
    headers: { accept: "application/json", ...authHeader() },
  });
  return guard(response, url, async () => {
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    return (text ? JSON.parse(text) : undefined) as T;
  });
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

export interface RobotTelemetrySample {
  kind: string;
  payload: Record<string, unknown>;
  observed_at: string;
  producer: string;
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

export interface DialogueRecord {
  id: number;
  created_at: string;
  session_id: string;
  role: "user" | "assistant";
  text: string;
  status: "done" | "rejected";
}

export interface VisitRecord {
  id: number;
  created_at: string;
  language: string;
  full_name: string;
  organization: string;
  purpose: string;
  destination: string;
  has_pass: boolean | null;
  has_id: boolean | null;
  status: "new" | "processed";
}

export interface LlmBackendConfig {
  mode: "local" | "cloud";
  base_url: string;
  model: string;
  api_key: string;
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
  robotTelemetry: () => getJson<RobotTelemetrySample[]>("/api/v1/robot/telemetry"),
  robotCommand: (body: {
    capability: string;
    payload: Record<string, unknown>;
    submitter?: string;
  }) => postJson<{ command_id: string }, typeof body>("/api/v1/robot/commands", body),
  // Video-wall manual remote (presenter mode). Result arrives on the WS bus
  // as wall.command.result, matched by command_id.
  wallCommand: (body: {
    kind: "open_section" | "navigate";
    section?: string;
    nav?: string;
    submitter?: string;
  }) => postJson<{ command_id: string }, typeof body>("/api/v1/wall/commands", body),
  wallHealth: () => getJson<{ enabled: boolean; reachable: boolean }>("/api/v1/wall/health"),
  ragAsk: (body: RagAskRequest) => postJson<RagAskResponse, RagAskRequest>("/api/v1/rag/ask", body),
  ragAskStart: (body: RagAskRequest) =>
    postJson<{ session_id: string }, RagAskRequest>("/api/v1/rag/ask/start", body),
  // Make the robot speak the given text verbatim (no LLM) out of its speaker.
  voiceSay: (body: { text: string; language?: "ru" | "en" }) =>
    postJson<{ session_id: string }, typeof body>("/api/v1/voice/say", body),
  // Stop the robot's speech immediately (voice barge-in is disabled by the
  // half-duplex mic, so this button is the interrupt path).
  voiceInterrupt: () => postJson<{ interrupted: boolean }>("/api/v1/voice/interrupt"),
  // LLM backend switching (local llama.cpp ⇄ cloud OpenAI-compatible). The
  // api key is stored on the robot (core-state volume), never in images.
  // Persisted event tail for the dev console pages (replayed on mount).
  eventsHistory: (limit = 500, subject = "") =>
    getJson<{ records: import("../lib/eventStream").EventEnvelope[] }>(
      `/api/v1/events/history?limit=${limit}${subject ? `&subject=${encodeURIComponent(subject)}` : ""}`,
    ),
  // Full conversation history persisted on the robot (voice + chat).
  dialogueHistory: (limit = 200) =>
    getJson<{ records: DialogueRecord[] }>(`/api/v1/dialogue?limit=${limit}`),
  dialogueClear: () => deleteJson<{ deleted: number }>("/api/v1/dialogue"),
  // Guard desk (пункт охраны): visitor journal + starting the interview.
  visitsList: (status?: "new" | "processed") =>
    getJson<{ records: VisitRecord[] }>(
      `/api/v1/visits?limit=100${status ? `&status=${status}` : ""}`,
    ),
  visitMarkProcessed: (id: number) =>
    postJson<{ id: number; status: string }>(`/api/v1/visits/${id}/processed`),
  visitIntakeStart: () => postJson<{ started: boolean }>("/api/v1/visits/intake/start"),
  llmConfigGet: () => getJson<LlmBackendConfig>("/api/v1/llm/config"),
  llmConfigSet: (body: LlmBackendConfig) =>
    postJson<LlmBackendConfig, LlmBackendConfig>("/api/v1/llm/config", body),
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
  safetyAudit: (params: { subject_prefix?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.subject_prefix) qs.set("subject_prefix", params.subject_prefix);
    if (params.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return getJson<SafetyAuditPage>(`/api/v1/safety/audit${suffix}`);
  },
};

export interface SafetyAuditRecord {
  id: number;
  occurred_at: string;
  subject: string;
  correlation_id: string;
  producer: string;
  payload: Record<string, unknown>;
}

export interface SafetyAuditPage {
  total: number;
  records: SafetyAuditRecord[];
}

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
  max_linear_speed_mps: number;
  max_angular_rate_rps: number;
  actor_budgets: Record<string, { window_s: number; max_events: number }>;
  actor_default_budget: { window_s: number; max_events: number };
}
