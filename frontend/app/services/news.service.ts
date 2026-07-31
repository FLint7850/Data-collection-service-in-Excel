import type {
  NewsConfiguration,
  NewsBrandSearchResponse,
  NewsMonitor,
  NewsWorkspaceData,
  OwnSite,
  ProgressEntity,
  SmtpSettings,
} from "~/types/api";

export interface MonitorPayload {
  brand?: string;
  site_url?: string;
  start_urls?: string[];
  enabled?: boolean;
  schedule_type?: string;
  scan_time?: string;
  weekday?: number;
  next_run_at?: string;
  thread_count?: number;
  connection_method?: string;
  auto_connection_fallback?: boolean;
  exclusions?: string[];
  product_url_filters?: string[];
  product_url_exclusions?: string[];
  extraction_rules?: NewsMonitor["extraction_rules"];
  selector_settings?: NewsMonitor["selector_settings"];
  primary_donor_id?: string | number | null;
}

export const newsService = {
  getWorkspace: () =>
    $fetch<NewsWorkspaceData>("/api/news", {
      query: { scope: "workspace" },
    }),

  getSettings: () =>
    $fetch<NewsConfiguration>("/api/news", {
      query: { scope: "settings" },
    }),

  getMonitor: (monitorId: string) =>
    $fetch<{ monitors: NewsMonitor[] }>(
      `/api/news/monitors/${encodeURIComponent(monitorId)}`,
    ),

  searchBrands: (query: string, signal?: AbortSignal) =>
    $fetch<NewsBrandSearchResponse>("/api/news/brands", {
      query: { q: query },
      signal,
    }),

  updateSettings: (body: { own_sites?: OwnSite[]; smtp?: Partial<SmtpSettings> }) =>
    $fetch<NewsConfiguration>("/api/news/settings", { method: "PATCH", body }),

  testEmail: () =>
    $fetch<{ ok: boolean }>("/api/news/email/test", { method: "POST" }),

  createMonitor: (body: {
    group: string;
    brand: string;
    site_url?: string;
    start_urls?: string[];
    create_new_brand?: boolean;
  }) =>
    $fetch<{ monitor: NewsMonitor }>("/api/news/monitors", {
      method: "POST",
      body,
    }),

  updateMonitor: (monitorId: string, body: MonitorPayload) =>
    $fetch<{ monitor: NewsMonitor }>(
      `/api/news/monitors/${encodeURIComponent(monitorId)}`,
      { method: "PATCH", body },
    ),

  removeMonitor: (monitorId: string, mode: "donor" | "brand" = "donor") =>
    $fetch<{ ok: boolean; removed_ids: string[]; monitors: NewsMonitor[] }>(
      `/api/news/monitors/${encodeURIComponent(monitorId)}`,
      { method: "DELETE", query: mode === "brand" ? { mode: "brand" } : undefined },
    ),

  action: (
    monitorId: string,
    action: "scan" | "stop" | "pause" | "resume" | "reset-visual",
  ) =>
    $fetch<{ monitor: ProgressEntity }>(
      `/api/news/monitors/${encodeURIComponent(monitorId)}/${action}`,
      { method: "POST" },
    ),
};
