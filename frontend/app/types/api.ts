export type ViewId =
  | "projects"
  | "news"
  | "file-import"
  | "price-converter"
  | "attribute-assistant"
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
  run_monitor_id?: string;
  paused_with_result?: boolean;
}

export interface AttributeCategorySummary {
  id: number;
  name: string;
  parent_name: string;
  full_path: string;
  external_key: string;
}

export interface AttributeValueSynonym {
  id: number;
  synonym: string;
}

export interface AttributeAllowedValue {
  id: number;
  value: string;
  value_type: string;
  is_global: boolean;
  is_recommended: boolean;
  is_active: boolean;
  source: string;
  sort_order: number;
  synonyms?: AttributeValueSynonym[];
}

export interface AttributeTemplateField {
  id: number;
  group_name: string;
  name: string;
  is_required: boolean;
  value_type: string;
  is_composite: boolean;
  separator: string;
  sort_order: number;
  use_dash_if_empty: boolean;
  is_active: boolean;
  allowed_values: AttributeAllowedValue[];
}

export interface AttributeTemplateSummary {
  id: number;
  name: string;
  description: string;
  product_type: string;
  is_active: boolean;
  is_default: boolean;
  version: number;
  category: AttributeCategorySummary;
  fields_count: number;
  values_count: number;
  updated_at: string;
}

export interface AttributeTemplate extends AttributeTemplateSummary {
  fields: AttributeTemplateField[];
}

export interface AttributeBatchCounters {
  encoding?: string;
  filled?: number;
  needs_review?: number;
  extra?: number;
  conflicts?: number;
  dash?: number;
  proposed?: number;
  ready_products?: number;
  url_errors?: Array<{ url: string; error: string }>;
}

export interface AttributeProductSummary {
  id: number;
  external_id: string;
  model: string;
  name: string;
  source_url: string;
  category_name: string;
  brand: string;
  status: string;
  sort_order: number;
}

export interface AttributeBatchSummary {
  id: number;
  template_id: number | null;
  template_name: string;
  category_name: string;
  source_filename: string;
  input_mode: string;
  processing_mode: string;
  status: string;
  products_count: number;
  attributes_count: number;
  summary: AttributeBatchCounters;
  result_ready: boolean;
  report_ready: boolean;
  created_at: string;
  updated_at: string;
}

export interface AttributeBatch extends AttributeBatchSummary {
  products: AttributeProductSummary[];
}

export interface AttributeProductValue {
  id: number;
  template_field_id: number | null;
  group_name: string;
  attribute_name: string;
  current_value: string;
  proposed_value: string;
  final_value: string;
  source: string;
  confidence: number;
  status: string;
  is_in_template: boolean;
  is_extra_attribute: boolean;
  reason: string;
  source_details: Record<string, unknown> & {
    match_type?: string;
    closest_allowed?: string;
    candidates?: Array<{
      value: string;
      raw_value?: string;
      source: string;
      confidence: number;
      url?: string;
    }>;
  };
  sort_order: number;
  has_allowed_values: boolean;
  allowed_values: AttributeAllowedValue[];
}

export interface AttributeProduct extends AttributeProductSummary {
  batch_id: number;
  values: AttributeProductValue[];
  donor_sources: AttributeDonorSource[];
}

export interface AttributeDonorSource {
  id: number;
  donor_id: number | null;
  donor_name: string;
  url: string;
  priority: number;
  status: string;
  error: string;
  parsed_data: Record<string, unknown>;
}

export interface AttributeDonor {
  id: number;
  name: string;
  domain: string;
  base_url: string;
  selectors: Record<string, string>;
  is_active: boolean;
  mapping_rules: AttributeMappingRule[];
  updated_at: string;
}

export interface AttributeParsedPageAttribute {
  group_name: string;
  name: string;
  value: string;
}

export interface AttributeParsedPage {
  url: string;
  name: string;
  model: string;
  brand: string;
  description: string;
  category: string;
  breadcrumbs: string[];
  attributes: AttributeParsedPageAttribute[];
}

export interface AttributeChatGptObservedAttribute {
  name: string;
  value: string;
  evidence: string;
}

export interface AttributeChatGptSuggestion {
  template_field_id: number;
  group_name: string;
  attribute_name: string;
  proposed_value: string;
  confidence: number;
  explanation: string;
  evidence: string;
}

export interface AttributeChatGptAnalysis {
  product: { name: string; model: string; brand: string; category: string };
  observed_attributes: AttributeChatGptObservedAttribute[];
  suggestions: AttributeChatGptSuggestion[];
  warnings: string[];
  prompt_version: string;
}

export interface AttributeChatGptStatus {
  available: boolean;
  authenticated: boolean;
  auth_mode: string;
  email: string;
  plan_type: string;
  pending: boolean;
  verification_url: string;
  user_code: string;
  error: string;
}

export interface AttributeMappingRule {
  id: number;
  template_id: number | null;
  template_field_id: number;
  donor_attribute_name: string;
  confidence: number;
  is_active: boolean;
}

export interface AttributeProductLog {
  id: number;
  action: string;
  details: Record<string, unknown> & {
    value_id?: number;
    before?: Record<string, unknown>;
    after?: Record<string, unknown>;
  };
  created_at: string;
}

export interface AttributeAssistantMetrics {
  templates: number;
  batches: number;
  products: number;
  filled: number;
  needs_review: number;
  conflicts: number;
  ready_products: number;
}

export interface AttributeAssistantWorkspace {
  templates: AttributeTemplateSummary[];
  batches: AttributeBatchSummary[];
  donors: AttributeDonor[];
  metrics: AttributeAssistantMetrics;
}

export interface AttributeTemplateImportReport {
  created?: boolean;
  encoding: string;
  source_format: "vertical" | "dictionary" | string;
  mode?: string;
  new_fields: number | string[];
  updated_fields?: number;
  new_values: number | Array<{ attribute: string; value: string }>;
  new_fields_count?: number;
  removed_fields_count?: number;
  new_values_count?: number;
  removed_values_count?: number;
  changed_groups_count?: number;
  removed_fields?: string[];
  removed_values?: Array<{ attribute: string; value: string }>;
  changed_groups?: Array<{ attribute: string; from: string; to: string }>;
  used_attributes?: Array<{ field_id: number; attribute: string; products_count: number }>;
  duplicate_values: number;
  empty_values: number;
  invalid_values: Array<{ group_name: string; attribute_name: string; value: string }>;
  template_exists?: boolean;
  fields_count?: number;
}

export interface AttributeBatchReportRow {
  product_id: number;
  model: string;
  name: string;
  group_name: string;
  attribute_name: string;
  current_value: string;
  proposed_value: string;
  final_value: string;
  source: string;
  confidence: number;
  status: string;
  reason: string;
}

export interface AttributeBatchReport {
  batch: AttributeBatchSummary;
  summary: AttributeBatchCounters;
  source_summary: Record<string, number>;
  status_summary: Record<string, number>;
  rows: AttributeBatchReportRow[];
  export_warning: string;
}

export interface AttributeTemplateRevision {
  id: number;
  version: number;
  action: string;
  report: Record<string, unknown>;
  created_at: string;
}

export type NewsSummaryState = Pick<
  ScanState,
  "status" | "percent" | "error"
> &
  Partial<ScanState>;

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
  upsert_news?: NewsMonitorSummary[];
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

export interface NewsMonitorSummary {
  id: string;
  brand_id?: number;
  primary_donor_id?: number | string | null;
  group: string;
  brand: string;
  site_url: string;
  start_urls: string[];
  start_urls_count?: number;
  enabled: boolean;
  state: NewsSummaryState;
}

export interface NewsMonitor extends NewsMonitorSummary {
  state: ScanState;
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

export interface NewsBrandSearchResult {
  id: number;
  name: string;
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
  monitors: NewsMonitorSummary[];
  connection_methods: ConnectionMethod[];
  progress_cursor?: string;
}

export interface NewsConfiguration {
  revision: string;
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
  revision: string;
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
  revision?: string;
  exclusions: string;
  model_field: string;
  price_field: string;
  replace_rules: string;
}

export interface FileImportProgress {
  revision: string;
  state: FileImportState;
  result_filename: string;
  result_ready: boolean;
}

export interface PriceConverterState {
  status: string;
  stage: string;
  rows_written: number;
  matched_sheets: number;
  skipped_sheets: number;
  error: string;
  started_at: string;
  finished_at: string;
  elapsed_seconds: number;
  result_filename: string;
}

export interface PriceConverterSettings {
  revision?: string;
  model_field: string;
  price_field: string;
  promo_field: string;
  promo_date: string;
  sheet_number: number | null;
}

export interface PriceConverterRuntime {
  revision: string;
  file: UploadedFile | null;
  result_filename: string;
  result_ready: boolean;
  state: PriceConverterState;
}

export interface PriceConverterData extends PriceConverterRuntime {
  model_field: string;
  price_field: string;
  promo_field: string;
  promo_date: string;
  sheet_number: number | null;
}

export interface SupplierFeed {
  id?: number;
  name: string;
  feed_url: string;
  model_field: string;
  name_field: string;
  price_field: string;
  brand_field: string;
  url_field: string;
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
  revision: string;
  own_sites: OwnSite[];
  suppliers: SupplierFeed[];
  state: FeedComparisonState;
  result_ready: boolean;
  result_filename: string;
}

export interface FeedComparisonProgress {
  revision: string;
  state: FeedComparisonState;
  result_ready: boolean;
  result_filename: string;
}

export interface LogEntry {
  id: number;
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
  logs_last_id: number;
  logs_counts: Record<string, number>;
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
