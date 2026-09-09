export interface ShopSyncReport {
  created: number;
  updated: number;
  unchanged: number;
  fields_added: number;
  values_added: number;
  categories_missing: number;
  fields_missing: number;
  values_missing: number;
  local_changes_preserved: number;
  normalized_duplicates: number;
}
export interface AttributeShop {
  id: number;
  name: string;
  endpoint: string;
  language_code: string;
  enabled: boolean;
  has_api_key: boolean;
  last_sync_at: string;
  last_error: string;
  last_report: Partial<ShopSyncReport>;
  syncing: boolean;
}
export interface AttributeShopForm {
  name: string;
  endpoint: string;
  api_key: string;
  language_code: string;
  enabled: boolean;
}
const base = "/api/attribute-assistant/shops";
export const opencartApi = {
  list: () => $fetch<AttributeShop[]>(base),
  save: (body: AttributeShopForm, id: number | null) =>
    $fetch<AttributeShop>(id ? base + "/" + id : base, { method: id ? "PATCH" : "POST", body }),
  remove: (id: number) => $fetch(base + "/" + id, { method: "DELETE" }),
  sync: (id: number) => $fetch<{ shop: AttributeShop; report: ShopSyncReport }>(
    base + "/" + id + "/sync", { method: "POST", timeout: 180000 },
  ),
};
