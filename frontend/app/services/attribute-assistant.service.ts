import type {
  AttributeAllowedValue,
  AttributeAssistantWorkspace,
  AttributeBatch,
  AttributeBatchReport,
  AttributeBatchSummary,
  AttributeChatGptAnalysis,
  AttributeChatGptStatus,
  AttributeDonor,
  AttributeProduct,
  AttributeParsedPage,
  AttributeTemplate,
  AttributeTemplateImportReport,
  AttributeTemplateRevision,
  AttributeTemplateSummary,
} from "~/types/api";

interface WorkspaceResponse {
  workspace: AttributeAssistantWorkspace;
}

interface TemplateImportFields {
  category_name: string;
  category_path: string;
  template_name: string;
  product_type?: string;
  external_key?: string;
  is_default?: boolean;
  mode: "merge" | "replace" | "update_values";
}

function templateForm(file: File, fields: TemplateImportFields) {
  const form = new FormData();
  form.append("file", file);
  Object.entries(fields).forEach(([key, value]) => form.append(key, String(value ?? "")));
  return form;
}

export const attributeAssistantService = {
  getWorkspace: () =>
    $fetch<AttributeAssistantWorkspace>("/api/attribute-assistant"),

  getChatGptStatus: () =>
    $fetch<AttributeChatGptStatus>("/api/attribute-assistant/chatgpt/status"),

  startChatGptLogin: () =>
    $fetch<AttributeChatGptStatus>("/api/attribute-assistant/chatgpt/login/device", {
      method: "POST",
    }),

  logoutChatGpt: () =>
    $fetch<AttributeChatGptStatus>("/api/attribute-assistant/chatgpt/logout", {
      method: "POST",
    }),

  analyzeChatGptUrl: (
    url: string,
    templateId?: number,
  ) =>
    $fetch<{ analysis: AttributeChatGptAnalysis }>(
      "/api/attribute-assistant/chatgpt/analyze-url",
      { method: "POST", body: { url, template_id: templateId } },
    ),

  createTemplate: (fields: Omit<TemplateImportFields, "mode">) =>
    $fetch<{ template: AttributeTemplate; workspace: AttributeAssistantWorkspace }>(
      "/api/attribute-assistant/templates",
      { method: "POST", body: fields },
    ),

  getTemplate: (templateId: number) =>
    $fetch<{ template: AttributeTemplate; revisions: AttributeTemplateRevision[] }>(
      `/api/attribute-assistant/templates/${templateId}`,
    ),

  previewTemplate: (file: File, fields: TemplateImportFields) =>
    $fetch<{ report: AttributeTemplateImportReport }>(
      "/api/attribute-assistant/templates/preview",
      { method: "POST", body: templateForm(file, fields) },
    ),

  importTemplate: (file: File, fields: TemplateImportFields) =>
    $fetch<{
      template: AttributeTemplateSummary;
      report: AttributeTemplateImportReport;
      workspace: AttributeAssistantWorkspace;
    }>("/api/attribute-assistant/templates/import", {
      method: "POST",
      body: templateForm(file, fields),
    }),

  copyTemplate: (templateId: number, name: string) =>
    $fetch<{ template: AttributeTemplate; workspace: AttributeAssistantWorkspace }>(
      `/api/attribute-assistant/templates/${templateId}/copy`,
      { method: "POST", body: { name } },
    ),

  restoreTemplate: (templateId: number, revisionId: number) =>
    $fetch<{
      template: AttributeTemplate;
      revisions: AttributeTemplateRevision[];
      workspace: AttributeAssistantWorkspace;
    }>(`/api/attribute-assistant/templates/${templateId}/restore/${revisionId}`, {
      method: "POST",
    }),

  deleteTemplate: (templateId: number) =>
    $fetch<WorkspaceResponse>(
      `/api/attribute-assistant/templates/${templateId}`,
      { method: "DELETE" },
    ),

  updateField: (fieldId: number, fields: Record<string, unknown>) =>
    $fetch<{ template: AttributeTemplate }>(
      `/api/attribute-assistant/fields/${fieldId}`,
      { method: "PATCH", body: fields },
    ),

  createField: (templateId: number, fields: Record<string, unknown>) =>
    $fetch<{ template: AttributeTemplate }>(
      `/api/attribute-assistant/templates/${templateId}/fields`,
      { method: "POST", body: fields },
    ),

  reorderFields: (templateId: number, fieldIds: number[]) =>
    $fetch<{ template: AttributeTemplate }>(
      `/api/attribute-assistant/templates/${templateId}/fields/reorder`,
      { method: "POST", body: { field_ids: fieldIds } },
    ),

  deleteField: (fieldId: number) =>
    $fetch<{ template: AttributeTemplate }>(
      `/api/attribute-assistant/fields/${fieldId}`,
      { method: "DELETE" },
    ),

  getFieldAllowedValues: (fieldId: number) =>
    $fetch<{ field_id: number; allowed_values: AttributeAllowedValue[] }>(
      `/api/attribute-assistant/fields/${fieldId}/allowed-values`,
    ),

  addAllowedValue: (
    fieldId: number,
    fields: { value: string; is_global?: boolean; is_recommended?: boolean; synonyms?: string[] },
  ) =>
    $fetch<{ value: AttributeAllowedValue }>(
      `/api/attribute-assistant/fields/${fieldId}/allowed-values`,
      { method: "POST", body: fields },
    ),

  updateAllowedValue: (valueId: number, fields: Record<string, unknown>) =>
    $fetch<{ ok: boolean }>(`/api/attribute-assistant/allowed-values/${valueId}`, {
      method: "PATCH",
      body: fields,
    }),

  addSynonym: (valueId: number, synonym: string) =>
    $fetch<{ synonym: { id: number; synonym: string } }>(
      `/api/attribute-assistant/allowed-values/${valueId}/synonyms`,
      { method: "POST", body: { synonym } },
    ),

  deleteSynonym: (synonymId: number) =>
    $fetch<{ ok: boolean }>(`/api/attribute-assistant/synonyms/${synonymId}`, {
      method: "DELETE",
    }),

  importBatch: (file: File, templateId: number, processingMode: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("template_id", String(templateId));
    form.append("processing_mode", processingMode);
    return $fetch<{ batch: AttributeBatch; workspace: AttributeAssistantWorkspace }>(
      "/api/attribute-assistant/batches/import",
      { method: "POST", body: form },
    );
  },

  importUrls: (urls: string[], templateId: number, processingMode: string) =>
    $fetch<{ batch: AttributeBatch; workspace: AttributeAssistantWorkspace }>(
      "/api/attribute-assistant/batches/import-urls",
      { method: "POST", body: { urls, template_id: templateId, processing_mode: processingMode } },
    ),

  getBatch: (batchId: number) =>
    $fetch<{ batch: AttributeBatch; report: AttributeBatchReport }>(
      `/api/attribute-assistant/batches/${batchId}`,
    ),

  deleteBatch: (batchId: number) =>
    $fetch<WorkspaceResponse>(`/api/attribute-assistant/batches/${batchId}`, {
      method: "DELETE",
    }),

  bulkUpdate: (
    batchId: number,
    action: string,
    fields: { value_ids?: number[]; threshold?: number } = {},
  ) =>
    $fetch<{ result: { changed: number; skipped: number }; batch: AttributeBatchSummary }>(
      `/api/attribute-assistant/batches/${batchId}/bulk`,
      { method: "POST", body: { action, ...fields } },
    ),

  getProduct: (productId: number) =>
    $fetch<{ product: AttributeProduct }>(
      `/api/attribute-assistant/products/${productId}`,
    ),

  updateValue: (productId: number, valueId: number, finalValue: string) =>
    $fetch<{ product: AttributeProduct; batch: AttributeBatchSummary }>(
      `/api/attribute-assistant/products/${productId}/values/${valueId}`,
      { method: "PATCH", body: { final_value: finalValue } },
    ),

  getProductHistory: (productId: number) =>
    $fetch<{ logs: Array<{ id: number; action: string; details: Record<string, unknown>; created_at: string }> }>(
      `/api/attribute-assistant/products/${productId}/history`,
    ),

  rollbackValue: (productId: number, logId: number) =>
    $fetch<{ product: AttributeProduct }>(
      `/api/attribute-assistant/products/${productId}/rollback/${logId}`,
      { method: "POST" },
    ),

  parseDonor: (
    productId: number,
    fields: { url: string; donor_id?: number; priority?: number },
  ) =>
    $fetch<{ source_id: number; product: AttributeProduct }>(
      `/api/attribute-assistant/products/${productId}/donors/parse`,
      { method: "POST", body: fields },
    ),

  analyzeProductChatGpt: (
    productId: number,
    fields: { url?: string; donor_id?: number },
  ) =>
    $fetch<{
      analysis: AttributeChatGptAnalysis;
      changed: number;
      product: AttributeProduct;
      batch: AttributeBatchSummary;
    }>(`/api/attribute-assistant/products/${productId}/chatgpt/analyze`, {
      method: "POST",
      body: fields,
    }),

  createDonor: (fields: Partial<AttributeDonor>) =>
    $fetch<{ donor: AttributeDonor; workspace: AttributeAssistantWorkspace }>(
      "/api/attribute-assistant/donors",
      { method: "POST", body: fields },
    ),

  updateDonor: (donorId: number, fields: Partial<AttributeDonor>) =>
    $fetch<{ donor: AttributeDonor }>(`/api/attribute-assistant/donors/${donorId}`, {
      method: "PATCH",
      body: fields,
    }),

  deleteDonor: (donorId: number) =>
    $fetch<WorkspaceResponse>(`/api/attribute-assistant/donors/${donorId}`, {
      method: "DELETE",
    }),

  testDonor: (url: string, selectors: Record<string, string>) =>
    $fetch<{ parsed: AttributeParsedPage }>("/api/attribute-assistant/donors/test", {
      method: "POST",
      body: { url, selectors },
    }),

  saveMappingRule: (fields: {
    donor_id: number;
    template_id: number;
    template_field_id: number;
    donor_attribute_name: string;
  }) =>
    $fetch<{ rule_id: number }>("/api/attribute-assistant/mapping-rules", {
      method: "POST",
      body: fields,
    }),

  getReport: (batchId: number) =>
    $fetch<AttributeBatchReport>(`/api/attribute-assistant/batches/${batchId}/report`),

  exportReport: (batchId: number) =>
    $fetch<{ filename: string; download_url: string }>(
      `/api/attribute-assistant/batches/${batchId}/report`,
      { method: "POST" },
    ),

  exportBatch: (batchId: number, onlyReady = false) =>
    $fetch<{ batch: AttributeBatchSummary; filename: string; download_url: string }>(
      `/api/attribute-assistant/batches/${batchId}/export`,
      { method: "POST", body: { only_ready: onlyReady } },
    ),
};
