import type {
  Project,
  ProjectResponse,
  ProjectsResponse,
  ScanState,
} from "~/types/api";

export interface ProjectSavePayload {
  name: string;
  start_urls: string[];
  thread_count: number;
  connection_method: string;
  auto_connection_fallback: boolean;
  persist_profile: boolean;
  product_url_filters: string[];
  product_url_exclusions: string[];
  extraction_rules: Project["extraction_rules"];
}

export const projectService = {
  list: (summary = false) =>
    $fetch<ProjectsResponse>("/api/projects", {
      query: summary ? { summary: 1 } : undefined,
    }),

  get: (projectId: string) =>
    $fetch<ProjectResponse>(`/api/projects/${encodeURIComponent(projectId)}`),

  create: (name: string, startUrls?: string[]) =>
    $fetch<ProjectResponse>("/api/projects", {
      method: "POST",
      body: { name, start_urls: startUrls },
    }),

  update: (projectId: string, body: Partial<ProjectSavePayload>) =>
    $fetch<ProjectResponse>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      body,
    }),

  remove: (projectId: string) =>
    $fetch<{ ok: boolean }>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: "DELETE",
    }),

  addPattern: (
    projectId: string,
    collection: "exclusions" | "product-url-filters" | "product-url-exclusions",
    pattern: string,
  ) =>
    $fetch<Record<string, string[]>>(
      `/api/projects/${encodeURIComponent(projectId)}/${collection}`,
      { method: "POST", body: { pattern } },
    ),

  removePattern: (
    projectId: string,
    collection: "exclusions" | "product-url-filters" | "product-url-exclusions",
    index: number,
  ) =>
    $fetch<Record<string, string[]>>(
      `/api/projects/${encodeURIComponent(projectId)}/${collection}/${index}`,
      { method: "DELETE" },
    ),

  start: (projectId: string, body: ProjectSavePayload) =>
    $fetch<ScanState>(`/api/projects/${encodeURIComponent(projectId)}/start`, {
      method: "POST",
      body,
    }),

  action: (
    projectId: string,
    action: "pause" | "soft-pause" | "resume" | "stop" | "restart",
  ) =>
    $fetch<ScanState>(
      `/api/projects/${encodeURIComponent(projectId)}/${action}`,
      { method: "POST" },
    ),
};
