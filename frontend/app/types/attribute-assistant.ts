export interface AttributeAllowedValue {
  id: number;
  value: string;
  synonyms: string[];
}

export interface AttributeTemplateField {
  id: number;
  group_name: string;
  name: string;
  value_type: "select" | "number" | "dimensions" | "boolean" | string;
  is_composite: boolean;
  is_required: boolean;
  sort_order: number;
  allowed_values: AttributeAllowedValue[];
}

export interface AttributeTemplate {
  id: number;
  name: string;
  category: string;
  product_type: string;
  description: string;
  is_default: boolean;
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
  source_details: {
    candidates?: Array<Record<string, unknown>>;
    unknown_values?: Array<{
      value: string;
      source: string;
      source_name: string;
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
  url: string;
  priority: number;
  role: string;
  status: string;
  message: string;
}

export interface AttributeProduct {
  id: number;
  model: string;
  name: string;
  brand: string;
  category_name: string;
  source_url: string;
  status: string;
  counts: {
    missing: number;
    conflicts: number;
    suggestions: number;
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

export interface AttributeWorkspace {
  templates: AttributeTemplate[];
  donors: AttributeDonor[];
  batches: AttributeBatch[];
}

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

