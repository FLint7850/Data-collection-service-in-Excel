import type {
  FeedComparisonData,
  FeedComparisonState,
  OwnSite,
  SupplierFeed,
} from "~/types/api";

export const feedComparisonService = {
  get: () => $fetch<FeedComparisonData>("/api/feed-comparison"),

  saveOwnSite: (site: OwnSite) =>
    $fetch<FeedComparisonData>(
      site.id
        ? `/api/feed-comparison/own-sites/${site.id}`
        : "/api/feed-comparison/own-sites",
      { method: site.id ? "PATCH" : "POST", body: site },
    ),

  removeOwnSite: (id: number) =>
    $fetch<FeedComparisonData>(`/api/feed-comparison/own-sites/${id}`, {
      method: "DELETE",
    }),

  saveSupplier: (supplier: SupplierFeed) =>
    $fetch<FeedComparisonData>(
      supplier.id
        ? `/api/feed-comparison/suppliers/${supplier.id}`
        : "/api/feed-comparison/suppliers",
      { method: supplier.id ? "PATCH" : "POST", body: supplier },
    ),

  removeSupplier: (id: number) =>
    $fetch<FeedComparisonData>(`/api/feed-comparison/suppliers/${id}`, {
      method: "DELETE",
    }),

  start: () =>
    $fetch<FeedComparisonState>("/api/feed-comparison/start", {
      method: "POST",
    }),

  stop: () =>
    $fetch<FeedComparisonData>("/api/feed-comparison/stop", {
      method: "POST",
    }),
};
