import type {
  AttributeBatch,
  AttributeProduct,
  AttributeTemplate,
  AttributeValue,
  AttributeWorkspace,
  ChatGptLogin,
  ChatGptStatus,
} from "~/types/attribute-assistant";

const base = "/api/attribute-assistant";

export const attributeAssistantService = {
  workspace: () => $fetch<AttributeWorkspace>(base),

  template: (id: number) =>
    $fetch<AttributeTemplate>(`${base}/templates/${id}`),

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

  importBatch: (
    file: File,
    templateId: number,
    processingMode: "suggest" | "auto",
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
    processingMode: "suggest" | "auto",
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
  removeBatch: (id: number) =>
    $fetch(`${base}/batches/${id}`, { method: "DELETE" }),

  product: (id: number) =>
    $fetch<AttributeProduct>(`${base}/products/${id}`),

  processProduct: (id: number, donorIds: number[]) =>
    $fetch<{ report: unknown; product: AttributeProduct }>(
      `${base}/products/${id}/process`,
      { method: "POST", body: { donor_ids: donorIds } },
    ),

  useSimilar: (id: number) =>
    $fetch<{ changed: number; product: AttributeProduct }>(
      `${base}/products/${id}/similar`,
      { method: "POST" },
    ),

  updateValue: (
    id: number,
    body: { action: "accept" | "reject" | "dash"; value?: string; dash_reason?: string },
  ) =>
    $fetch<AttributeValue>(`${base}/values/${id}`, {
      method: "PATCH",
      body,
    }),

  bulk: (
    batchId: number,
    body: { action: "accept_high" | "fill_dashes"; minimum_confidence?: number; dash_reason?: string },
  ) =>
    $fetch<{ changed: number; batch: AttributeBatch }>(
      `${base}/batches/${batchId}/bulk`,
      { method: "POST", body },
    ),

  export: (batchId: number) =>
    $fetch<{ ok: boolean; filename: string }>(
      `${base}/batches/${batchId}/export`,
      { method: "POST" },
    ),

  chatGptStatus: () =>
    $fetch<ChatGptStatus>(`${base}/chatgpt/status`),
  chatGptLogin: () =>
    $fetch<ChatGptLogin>(`${base}/chatgpt/login`, { method: "POST" }),
  chatGptLogout: () =>
    $fetch(`${base}/chatgpt/logout`, { method: "POST" }),
};

