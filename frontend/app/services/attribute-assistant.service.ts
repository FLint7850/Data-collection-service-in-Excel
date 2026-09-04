import type {
  AttributeAllowedValue,
  AttributeAllowedValueOptions,
  AttributeBatch,
  AttributeBatchOperation,
  AttributeBatchReport,
  AttributeChatGptAnalyzeResult,
  AttributeDonor,
  AttributeHistoryItem,
  AttributeMappingRule,
  AttributeValueMappingRule,
  AttributeProcessingMode,
  AttributeProcessReport,
  AttributeProduct,
  AttributeTemplate,
  AttributeTemplatePreview,
  AttributeValue,
  AttributeWorkspace,
  ChatGptLogin,
  ChatGptStatus,
} from "~/types/attribute-assistant";

const base = "/api/attribute-assistant";

export const attributeAssistantService = {
  workspace: () => $fetch<AttributeWorkspace>(base),

  template: (id: number) =>
    $fetch<AttributeTemplate>(`${base}/templates/${id}`, { query: { lazy: 1 } }),

  importTemplate: (file: File, data: {
    name: string;
    category: string;
    product_type?: string;
    description?: string;
  }) => {
    const form = new FormData();
    form.append("file", file);
    Object.entries(data).forEach(([key, value]) => form.append(key, value || ""));
    return $fetch<AttributeTemplate>(`${base}/templates/import`, {
      method: "POST",
      body: form,
    });
  },

  addAllowedValue: (fieldId: number, value: string, synonym = "") =>
    $fetch(`${base}/fields/${fieldId}/allowed-values`, {
      method: "POST",
      body: { value, synonym },
    }),

  allowedValues: (fieldId: number, query = "", editor = false, offset = 0, limit = 80) =>
    $fetch<AttributeAllowedValueOptions>(`${base}/fields/${fieldId}/allowed-values`, {
      query: { q: query, limit, offset, editor: editor ? 1 : 0 },
    }),

  importBatch: (
    file: File,
    templateId: number,
    processingMode: AttributeProcessingMode,
    name = "",
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("template_id", String(templateId));
    form.append("processing_mode", processingMode);
    form.append("name", name);
    return $fetch<AttributeBatch>(`${base}/batches/import`, {
      method: "POST",
      body: form,
    });
  },

  importUrls: (
    urls: string[],
    templateId: number | null,
    processingMode: AttributeProcessingMode,
    name = "",
  ) =>
    $fetch<AttributeBatch>(`${base}/batches/urls`, {
      method: "POST",
      body: {
        urls,
        template_id: templateId,
        processing_mode: processingMode,
        name,
      },
    }),

  batch: (id: number) => $fetch<AttributeBatch>(`${base}/batches/${id}`),
  batchOperation: (id: number) =>
    $fetch<AttributeBatchOperation>(`${base}/batches/${id}/operation`),
  processBatch: (
    id: number,
    donorIds: number[],
    urlOverridesByProduct: Record<string, Record<string, string>> = {},
  ) =>
    $fetch<AttributeBatchOperation>(`${base}/batches/${id}/process-all`, {
      method: "POST",
      body: { donor_ids: donorIds, url_overrides_by_product: urlOverridesByProduct },
    }),
  analyzeBatchWithChatGpt: (
    id: number,
    donorIds: number[],
    urlOverridesByProduct: Record<string, Record<string, string>> = {},
  ) =>
    $fetch<AttributeBatchOperation>(`${base}/batches/${id}/chatgpt/analyze-all`, {
      method: "POST",
      body: { donor_ids: donorIds, url_overrides_by_product: urlOverridesByProduct },
    }),
  removeBatch: (id: number) =>
    $fetch<{ ok: boolean; deleted: { products: number; files: number } }>(
      `${base}/batches/${id}`,
      { method: "DELETE" },
    ),

  product: (id: number) =>
    $fetch<AttributeProduct>(`${base}/products/${id}`),

  processProduct: (id: number, donorIds: number[], urlOverrides: Record<string, string> = {}) =>
    $fetch<{ report: AttributeProcessReport; product: AttributeProduct }>(
      `${base}/products/${id}/process`,
      { method: "POST", body: { donor_ids: donorIds, url_overrides: urlOverrides } },
    ),

  useSimilar: (id: number) =>
    $fetch<{ changed: number; product: AttributeProduct }>(
      `${base}/products/${id}/similar`,
      { method: "POST" },
    ),

  analyzeProductWithChatGpt: (
    id: number,
    donorIds: number[],
    urlOverrides: Record<string, string> = {},
  ) =>
    $fetch<AttributeChatGptAnalyzeResult>(
      `${base}/products/${id}/chatgpt/analyze`,
      { method: "POST", body: { donor_ids: donorIds, url_overrides: urlOverrides } },
    ),

  updateValue: (
    id: number,
    body: { action: "accept" | "reject" | "dash"; value?: string; dash_reason?: string },
  ) =>
    $fetch<AttributeValue>(`${base}/values/${id}`, {
      method: "PATCH",
      body,
    }),

  removeExtraValue: (id: number) =>
    $fetch<{ deleted_id: number; product: AttributeProduct }>(`${base}/values/${id}`, {
      method: "DELETE",
    }),

  bulk: (
    batchId: number,
    body: { action: "accept_high" | "fill_dashes"; minimum_confidence?: number; dash_reason?: string },
  ) =>
    $fetch<{ changed: number; batch: AttributeBatch }>(
      `${base}/batches/${batchId}/bulk`,
      { method: "POST", body },
    ),

  export: (batchId: number, readyOnly = false) =>
    $fetch<{ ok: boolean; filename: string }>(
      `${base}/batches/${batchId}/export`,
      { method: "POST", body: { ready_only: readyOnly } },
    ),

  previewTemplate: (file: File, templateId?: number | null) => {
    const form = new FormData();
    form.append("file", file);
    if (templateId) form.append("template_id", String(templateId));
    return $fetch<AttributeTemplatePreview>(`${base}/templates/preview`, { method: "POST", body: form });
  },
  updateTemplateCsv: (id: number, file: File, mode: "merge" | "replace") => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    return $fetch<{ preview: AttributeTemplatePreview; template: AttributeTemplate }>(`${base}/templates/${id}/update-csv`, { method: "POST", body: form });
  },
  updateTemplate: (id: number, body: Record<string, unknown>) =>
    $fetch<AttributeTemplate>(`${base}/templates/${id}`, { method: "PATCH", body }),
  removeTemplate: (id: number) =>
    $fetch<{ ok: boolean; deleted_id: number }>(`${base}/templates/${id}`, { method: "DELETE" }),
  copyTemplate: (id: number, name: string, category = "") =>
    $fetch<AttributeTemplate>(`${base}/templates/${id}/copy`, { method: "POST", body: { name, category } }),
  templateRevisions: (id: number) =>
    $fetch<{ items: Array<{ id: number; version: number; action: string; report: Record<string, unknown>; created_at: string }> }>(`${base}/templates/${id}/revisions`),
  restoreTemplate: (id: number, revisionId: number) =>
    $fetch<AttributeTemplate>(`${base}/templates/${id}/revisions/${revisionId}/restore`, { method: "POST" }),
  updateField: (id: number, body: Record<string, unknown>) =>
    $fetch<AttributeTemplate>(`${base}/fields/${id}`, { method: "PATCH", body }),
  updateAllowedValue: (id: number, body: Record<string, unknown>) =>
    $fetch<{ value: AttributeAllowedValue; template_version: number }>(`${base}/allowed-values/${id}`, { method: "PATCH", body }),
  createField: (templateId: number, body: Record<string, unknown>) =>
    $fetch<AttributeTemplate>(`${base}/templates/${templateId}/fields`, { method: "POST", body }),
  removeField: (id: number) =>
    $fetch<{ deleted_id: number }>(`${base}/fields/${id}`, { method: "DELETE" }),
  assignTemplate: (productId: number, templateId: number) =>
    $fetch<AttributeProduct>(`${base}/products/${productId}/template`, { method: "PATCH", body: { template_id: templateId } }),
  donorRecommendations: (productId: number) =>
    $fetch<{ items: AttributeDonor[] }>(`${base}/products/${productId}/donor-recommendations`),
  mapAttribute: (productId: number, body: Record<string, unknown>) =>
    $fetch<{ stats: Record<string, number>; product: AttributeProduct }>(`${base}/products/${productId}/map-attribute`, { method: "POST", body }),
  mappingRules: (templateId?: number) =>
    $fetch<{ items: AttributeMappingRule[] }>(`${base}/mapping-rules`, { query: templateId ? { template_id: templateId } : {} }),
  removeMappingRule: (id: number) =>
    $fetch(`${base}/mapping-rules/${id}`, { method: "DELETE" }),
  rememberValueMapping: (valueId: number, body: { donor_id: number; raw_value: string; allowed_value_id: number }) =>
    $fetch<{ rule_id: number; value: AttributeValue }>(`${base}/values/${valueId}/mapping-rule`, { method: "POST", body }),
  valueMappingRules: (templateId?: number) =>
    $fetch<{ items: AttributeValueMappingRule[] }>(`${base}/value-mapping-rules`, { query: templateId ? { template_id: templateId } : {} }),
  removeValueMappingRule: (id: number) =>
    $fetch(`${base}/value-mapping-rules/${id}`, { method: "DELETE" }),
  productHistory: (id: number) =>
    $fetch<{ items: AttributeHistoryItem[] }>(`${base}/products/${id}/history`),
  restoreProduct: (id: number, historyId: number) =>
    $fetch<AttributeProduct>(`${base}/products/${id}/history/${historyId}/restore`, { method: "POST" }),
  batchReport: (id: number) => $fetch<AttributeBatchReport>(`${base}/batches/${id}/report`),

  chatGptStatus: () =>
    $fetch<ChatGptStatus>(`${base}/chatgpt/status`),
  chatGptLogin: () =>
    $fetch<ChatGptLogin>(`${base}/chatgpt/login`, { method: "POST" }),
  chatGptLogout: () =>
    $fetch(`${base}/chatgpt/logout`, { method: "POST" }),
};
