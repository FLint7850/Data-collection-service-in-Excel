export interface AttributeAllowedValue {
  id: number;
  value: string;
  synonyms: string[];
  is_combination: boolean;
  is_active: boolean;
}

export interface AttributeTemplateField {
  id: number;
  group_name: string;
  name: string;
  synonyms: string[];
  value_type: "select" | "number" | "dimensions" | "boolean" | string;
  is_composite: boolean;
  is_required: boolean;
  separator: string;
  use_dash_if_empty: boolean;
  conversion_rules: Array<Record<string, unknown>>;
  sort_order: number;
  allowed_values_count: number;
  allowed_values: AttributeAllowedValue[];
}

export interface AttributeTemplate {
  id: number;
  name: string;
  category: string;
  product_type: string;
  description: string;
  is_default: boolean;
  is_active: boolean;
  version: number;
  updated_at: string;
  field_count: number;
  fields?: AttributeTemplateField[];
}

export interface AttributeDonor {
  id: number;
  name: string;
  group_name: string;
  site_url: string;
  start_urls: string[];
  cached_products: number;
  connection_method: string;
  connection_name: string;
  uses_browser: boolean;
  uses_debug_visible: boolean;
  score?: number;
  reasons?: string[];
  recommended?: boolean;
}

export interface AttributeValue {
  id: number;
  field_id: number | null;
  group_name: string;
  name: string;
  current_value: string;
  proposed_value: string;
  final_value: string;
  source: string;
  confidence: number;
  status: string;
  reason: string;
  dash_reason: string;
  is_in_template: boolean;
  is_extra: boolean;
  value_type: string;
  is_composite: boolean;
  allowed_values_count: number;
  allowed_values: Array<{ id: number; value: string; is_combination?: boolean }>;
  source_details: {
    candidates?: Array<{
      value: string;
      raw_value: string;
      source: string;
      confidence: number;
      reason: string;
      priority: number;
      source_name: string;
      url?: string;
      role?: string;
      matches_current?: boolean;
    }>;
    unknown_values?: Array<{
      value: string;
      donor_id?: number | null;
      source: string;
      source_name: string;
      url?: string;
      role?: string;
      suggestions: string[];
      reason: string;
    }>;
    chatgpt?: Record<string, unknown>;
  };
  sort_order: number;
}

export interface AttributeSource {
  id: number;
  donor_id: number | null;
  donor_name: string;
  source_type?: "chatgpt" | "donor" | "site";
  url: string;
  priority: number;
  role: string;
  status: string;
  message: string;
  attributes: Array<{ name: string; value: string; group?: string }>;
  attributes_found: number;
  mapped: number;
  unknown: number;
  ambiguous: number;
  already_filled: number;
}

export interface AttributeDonorReport {
  donor_id: number;
  name?: string;
  status: string;
  url?: string;
  message?: string;
  resolved_by?: string;
  attributes_found?: number;
  mapped?: number;
  unknown?: number;
  ambiguous?: number;
  already_filled?: number;
}

export interface AttributeProcessReport {
  product_id: number;
  reports: AttributeDonorReport[];
}

export interface AttributeAllowedValueOptions {
  field_id: number;
  total: number;
  matched: number;
  offset: number;
  limit: number;
  has_more: boolean;
  values: AttributeAllowedValue[];
}

export interface AttributeProduct {
  id: number;
  model: string;
  name: string;
  brand: string;
  category_name: string;
  source_url: string;
  status: string;
  template: AttributeTemplate | null;
  selected_donor_ids: number[];
  donor_url_overrides: Record<string, string>;
  donor_urls: string[];
  processing_state: Record<string, unknown>;
  counts: {
    missing: number;
    conflicts: number;
    suggestions: number;
    outside_template: number;
  };
  values?: AttributeValue[];
  sources?: AttributeSource[];
}

export interface AttributeBatch {
  id: number;
  name: string;
  input_mode: string;
  processing_mode: string;
  status: string;
  source_filename: string;
  source_urls: Array<Record<string, unknown>>;
  original_ready: boolean;
  summary: {
    products: number;
    ready: number;
    needs_review: number;
    filled: number;
    missing: number;
    conflicts: number;
    suggestions: number;
  };
  template: AttributeTemplate;
  export_ready: boolean;
  created_at: string;
  products?: AttributeProduct[];
}

export interface AttributeBatchOperationError {
  product_id: number | null;
  product: string;
  error: string;
}

export interface AttributeBatchOperation {
  id: string;
  batch_id: number;
  kind: "" | "donors" | "chatgpt";
  status: "idle" | "queued" | "running" | "completed" | "failed";
  stage: "" | "queued" | "preparing" | "donors" | "chatgpt" | "applying" | "completed" | "failed";
  total: number;
  prepared: number;
  processed: number;
  succeeded: number;
  failed: number;
  percent: number;
  changed: number;
  attributes_found: number;
  current_product_id: number | null;
  current_product: string;
  errors: AttributeBatchOperationError[];
  started_at: string;
  finished_at: string;
  error: string;
}

export interface AttributeWorkspace {
  templates: AttributeTemplate[];
  donors: AttributeDonor[];
  batches: AttributeBatch[];
  dashboard: {
    active_templates: number;
    batches: number;
    products: number;
    ready: number;
    conflicts: number;
    missing: number;
  };
}

export interface AttributeTemplatePreview {
  rows: number;
  fields: Array<{
    order: number;
    group_name: string;
    name: string;
    value_type: string;
    is_composite: boolean;
    values: string[];
    invalid_values: string[];
    change: "add" | "update";
    added_values: string[];
    removed_values: string[];
  }>;
  removed_fields: Array<{ id: number; group_name: string; name: string }>;
  warnings: string[];
  can_import: boolean;
}

export interface AttributeBatchReport {
  totals: { products: number; ready: number; conflicts: number; missing: number; unknown: number; dashes: number };
  products: Array<{ id: number; model: string; name: string; template: string; ready: boolean; conflicts: number; missing: number; unknown: number; dashes: number }>;
  can_export: boolean;
}

export interface AttributeHistoryChange {
  field_id: number;
  name: string;
  group_name: string;
  before: string;
  after: string;
  before_status: string;
  after_status: string;
  before_source: string;
  after_source: string;
  before_confidence: number;
  after_confidence: number;
}

export interface AttributeHistoryItem {
  id: number;
  label: string;
  created_at: string;
  changed_count: number;
  changes: AttributeHistoryChange[];
}
export interface AttributeMappingRule { id: number; donor_id: number; donor_name: string; template_id: number; field_id: number; field_name: string; donor_attribute_name: string; confidence: number; is_active: boolean }
export interface AttributeValueMappingRule { id: number; donor_id: number; donor_name: string; template_id: number; field_id: number; field_name: string; raw_value: string; allowed_value_id: number; allowed_value: string; is_active: boolean }

export interface ChatGptStatus {
  available: boolean;
  authenticated: boolean;
  proxy_enabled: boolean;
  account: { email: string; plan: string } | null;
  error?: string;
}

export interface ChatGptLogin {
  login_id: string;
  verification_url: string;
  user_code: string;
}


export interface AttributeChatGptAnalysis {
  observed_attributes: Array<{ name: string; value: string; evidence: string }>;
  suggestions: Array<{
    template_field_id: number;
    group_name: string;
    attribute_name: string;
    proposed_value: string;
    confidence: number;
    explanation: string;
    evidence: string;
  }>;
  warnings: string[];
  prompt_version: string;
}

export interface AttributeChatGptAnalyzeResult {
  changed: number;
  source_url: string;
  analysis: AttributeChatGptAnalysis;
  product: AttributeProduct;
}

export type AttributeProcessingMode = "check" | "suggest" | "auto" | "auto_exact" | "auto_primary" | "auto_confident" | "auto_all";
