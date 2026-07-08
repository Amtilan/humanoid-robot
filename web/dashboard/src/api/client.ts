async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} for ${url}`);
  }
  return (await response.json()) as T;
}

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

export const api = {
  info: () => getJson<ServiceInfo>("/api/v1/system/info"),
  health: () => getJson<HealthResponse>("/api/v1/system/health/ready"),
  adapterGroups: () => getJson<AdapterGroupsResponse>("/api/v1/adapters/groups"),
  adaptersInGroup: (group: string) =>
    getJson<AdapterListResponse>(`/api/v1/adapters/${encodeURIComponent(group)}`),
};
