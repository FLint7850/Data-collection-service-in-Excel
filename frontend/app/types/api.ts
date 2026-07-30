export type ViewId =
  | "projects"
  | "news"
  | "file-import"
  | "feed-comparison"
  | "settings"
  | "logs";

export interface ApiErrorPayload {
  error?: string;
  message?: string;
}

export interface AuthSession {
  authenticated: boolean;
  username: string;
}

export interface ConnectionMethod {
  id: number;
  code: string;
  name: string;
  is_browser_render: boolean;
  is_debug_visible: boolean;
}

export interface ExtractionRules {
  product_card_selector?: string;
  product_url_selector?: string;
  model_selector?: string;
  price_selector?: string;
  model_start_marker?: string;
  model_end_marker?: string;
  model_replace_rules?: string;
}

export interface SelectorSettings {
  name_selector?: string;
  availability_selector?: string;
  availability_exclusions?: string[];
}

export interface MissingByFeed {
  source?: string;
  source_label?: string;
  name?: string;
  url?: string;
  count?: number;
  codes_count?: number;
  error?: string;
}

export interface ScanState {
  status: string;
  stage?: string;
  percent: number;
  currenturl: string;
  totalprocessed: number;
  processed_products: number;
  processed?: number;
  found_products: number;
  candidate_products?: number;
  compared_products?: number;
  in_memory_products?: number;
  queue_size?: number;
  active_tasks?: number;
  active_urls?: string[];
  skipped?: number;
  failed_pages?: number;
  availability_skipped?: number;
  stall_seconds?: number;
  new_count?: number;
  missing_by_feed?: MissingByFeed[];
  last_event?: string;
  last_warning?: string;
  last_scan_at?: string;
  last_csv?: string;
  error: string;
  download_ready?: boolean;
  csv_ready?: boolean;
  download_url?: string;
  filename?: string;
  thread_count?: number;
  started_at?: string;
  finished_at?: string;
  elapsed_seconds: number;
  paused_with_result?: boolean;
}

export interface Project {
  id: string;
  name: string;
  start_urls: string[];
  start_urls_count?: number;
  thread_count: number;
  exclusions: string[];
  product_url_filters: string[];
  product_url_exclusions: string[];
  extraction_rules: ExtractionRules;
  state: ScanState;
  auto_cleanup: boolean;
  connection_method: string;
  auto_connection_fallback: boolean;
  persist_profile: boolean;
}

export interface ProjectsResponse {
  projects: Project[];
  connection_methods: ConnectionMethod[];
  progress_cursor?: string;
}

export interface ProjectResponse {
  project: Project;
}

export interface ProgressEntity {
  id: string;
  state: Partial<ScanState>;
}

export interface ProgressPayload {
  cursor: string;
  projects?: ProgressEntity[];
  news?: ProgressEntity[];
  upsert_projects?: Project[];
  upsert_news?: NewsMonitor[];
  removed_projects_ids?: string[];
  removed_news_ids?: string[];
  replace_projects?: boolean;
  replace_news?: boolean;
}

export interface OwnSite {
  id?: number;
  name: string;
  feed_url: string;
  feed_generate_url: string;
}

export interface SmtpSettings {
  host: string;
  port: number;
  security: "ssl" | "starttls" | "none" | string;
  username: string;
  password?: string;
  password_set?: boolean;
  recipients: string[];
}

export interface NewsMonitor {
  id: string;
  brand_id?: number;
  primary_donor_id?: number | string | null;
  group: string;
  brand: string;
  site_url: string;
  start_urls: string[];
  start_urls_count?: number;
  enabled: boolean;
  schedule_type: "daily" | "weekly" | "once" | string;
  scan_time: string;
  weekday: number;
  next_run_at: string;
  thread_count: number;
  connection_method: string;
  auto_connection_fallback: boolean;
  exclusions: string[];
  product_url_filters: string[];
  product_url_exclusions: string[];
  extraction_rules: ExtractionRules;
  selector_settings: SelectorSettings;
  state: ScanState;
  created_at?: string;
  brand_created_at?: string;
}

export interface NewsBrand {
  id: number;
  brand_id: number;
  name: string;
  brand: string;
  group_name: string;
  group: string;
  state: ScanState;
  enabled: boolean;
  schedule_type: string;
  scan_time: string;
  weekday: number;
  next_run_at: string;
  primary_donor_id?: number | null;
  donors: NewsMonitor[];
}

export interface StoredFeed {
  source?: string;
  filename?: string;
  label?: string;
  size?: number;
  created_at?: string;
}

export interface NewsSettings {
  feed_url: string;
  feed_generate_url: string;
  feed_urls: string[];
  feed_generate_urls: string[];
  own_sites: OwnSite[];
  auto_cleanup: boolean;
  smtp: SmtpSettings;
  feed_storage: StoredFeed[];
  monitors: NewsMonitor[];
  brands?: NewsBrand[];
  connection_methods: ConnectionMethod[];
}

export interface NewsWorkspaceData {
  monitors: NewsMonitor[];
  connection_methods: ConnectionMethod[];
  progress_cursor?: string;
}

export interface NewsConfiguration {
  own_sites: OwnSite[];
  auto_cleanup: boolean;
  smtp: SmtpSettings;
  feed_storage: StoredFeed[];
}

export interface FileImportState {
  status: string;
  stage: string;
  percent: number;
  current_row: number;
  total_rows: number;
  processed_rows: number;
  excluded_rows: number;
  found_rows: number;
  missing_rows: number;
  model_not_found_rows: number;
  error: string;
  started_at: string;
  finished_at: string;
  elapsed_seconds: number;
  result_filename: string;
}

export interface UploadedFile {
  filename: string;
  stored_filename: string;
  size: number;
  uploaded_at: string;
}

export interface FileImportData {
  file: UploadedFile | null;
  exclusions: string;
  model_field: string;
  price_field: string;
  replace_rules: string;
  result_filename: string;
  result_ready: boolean;
  state: FileImportState;
}

export interface FileImportSettings {
  exclusions: string;
  model_field: string;
  price_field: string;
  replace_rules: string;
}

export interface FileImportProgress {
  state: FileImportState;
  result_filename: string;
  result_ready: boolean;
}

export interface SupplierFeed {
  id?: number;
  name: string;
  feed_url: string;
  model_field: string;
  exclusions: string;
  exclusions_list?: string[];
  replace_rules: string;
}

export interface FeedComparisonState {
  status: string;
  stage: string;
  percent: number;
  current_supplier: string;
  current_row: number;
  total_rows: number;
  processed_rows: number;
  excluded_rows: number;
  missing_rows: number;
  suppliers_done: number;
  suppliers_total: number;
  error: string;
  started_at: string;
  finished_at: string;
  elapsed_seconds: number;
  result_filename: string;
}

export interface FeedComparisonData {
  own_sites: OwnSite[];
  suppliers: SupplierFeed[];
  state: FeedComparisonState;
  result_ready: boolean;
  result_filename: string;
}

export interface FeedComparisonProgress {
  state: FeedComparisonState;
  result_ready: boolean;
  result_filename: string;
}

export interface LogEntry {
  time: string;
  level: "info" | "success" | "warning" | "error" | string;
  message: string;
  project_id?: string;
  project_name?: string;
  brand?: string;
  group?: string;
}

export interface LogsResponse {
  logs: LogEntry[];
  logs_total: number;
  logs_page: number;
  logs_limit: number;
  auto_cleanup: boolean;
  logs_signature: string;
  delta?: boolean;
}

export type LogsPollResponse =
  | LogsResponse
  | {
      not_modified: true;
      logs_signature: string;
      logs_total: number;
      auto_cleanup: boolean;
    };
