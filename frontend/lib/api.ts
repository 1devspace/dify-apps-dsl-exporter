// Thin fetch wrapper. All calls are same-origin (Next proxies /api to the
// FastAPI backend), so the session cookie is sent automatically.

export type User = {
  email: string;
  name: string;
  role: string;
  is_admin: boolean;
};

export type WorkflowRecord = {
  app_id: string;
  name: string;
  author: string;
  tags: string;
  decision: string;
  url: string;
  informations_added: boolean;
  missing_env_tag: boolean;
  live_in_dify: boolean;
  removed_from_dify: boolean;
  source: string;
};

export type Summary = {
  total_records: number;
  live: number;
  new: number;
  removed_from_dify: number;
  pending: number;
  missing_env_tag: number;
  marked_delete: number;
};

export type Dashboard = {
  summary: Summary;
  records: WorkflowRecord[];
  synced_at: string;
  tracker_url: string;
  dify_host: string;
};

export type Job = {
  id: string;
  type: string;
  status: "queued" | "running" | "success" | "error";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  log: string[];
  result: unknown;
  error: string | null;
  meta: Record<string, unknown>;
};

export type SettingField = {
  key: string;
  label: string;
  type: "text" | "password" | "bool";
  help: string;
  secret: boolean;
  is_set: boolean;
  value: string;
};

export type SettingGroup = { group: string; fields: SettingField[] };
export type SettingsResponse = { groups: SettingGroup[] };
export type TestResult = { ok: boolean; detail: string };
export type SettingsTest = { confluence: TestResult; dify: TestResult };

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  login: (email: string, password: string) =>
    req<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => req<User>("/api/auth/me"),
  logout: () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  workflows: () => req<Dashboard>("/api/workflows"),
  startJob: (type: "sync" | "tags" | "export") =>
    req<Job>(`/api/jobs/${type}`, { method: "POST" }),
  startPrune: (confirm: boolean) =>
    req<Job>("/api/jobs/prune", { method: "POST", body: JSON.stringify({ confirm }) }),
  startDoc: (appId: string, name: string) =>
    req<Job>("/api/jobs/doc", { method: "POST", body: JSON.stringify({ app_id: appId, name }) }),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  jobs: () => req<{ jobs: Job[] }>("/api/jobs"),
  addEnvTags: (appId: string, tags: string[]) =>
    req<{ ok: boolean; added: string[] }>(`/api/workflows/${appId}/env-tags`, {
      method: "POST",
      body: JSON.stringify({ tags }),
    }),
  removeEnvTag: (appId: string, env: string) =>
    req<{ ok: boolean; removed: string }>(
      `/api/workflows/${appId}/env-tags/${encodeURIComponent(env)}`,
      { method: "DELETE" }
    ),
  assignAuthor: (appId: string, author = "") =>
    req<{ ok: boolean; author: string }>(`/api/workflows/${appId}/author`, {
      method: "POST",
      body: JSON.stringify({ author }),
    }),
  unassignAuthor: (appId: string, author = "") =>
    req<{ ok: boolean; removed: string }>(`/api/workflows/${appId}/author/unassign`, {
      method: "POST",
      body: JSON.stringify({ author }),
    }),
  deleteWorkflow: (appId: string) =>
    req<{ ok: boolean }>(`/api/workflows/${appId}`, { method: "DELETE" }),
  readable: (appId: string, name: string) =>
    req<{ markdown: string }>(
      `/api/workflows/${appId}/readable?name=${encodeURIComponent(name)}`
    ),
  docLinks: () =>
    req<{
      links: Record<string, string>;
      links_by_id: Record<string, string>;
      index_url: string | null;
    }>("/api/workflows/doc-links"),
  exportUrl: (appId: string, name: string) =>
    `/api/workflows/${appId}/export?name=${encodeURIComponent(name)}`,
  settings: () => req<SettingsResponse>("/api/settings"),
  updateSettings: (values: Record<string, string | boolean>) =>
    req<SettingsResponse>("/api/settings", { method: "PUT", body: JSON.stringify({ values }) }),
  testSettings: (values: Record<string, string | boolean>) =>
    req<SettingsTest>("/api/settings/test", { method: "POST", body: JSON.stringify({ values }) }),
};

export { ApiError };
