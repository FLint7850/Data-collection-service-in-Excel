import type {
  FeedComparisonData,
  FeedComparisonProgress,
  OwnSite,
  SupplierFeed,
} from "~/types/api";

export const feedComparisonService = {
  get: () => $fetch<FeedComparisonData>("/api/feed-comparison"),
  getProgress: () =>
    $fetch<FeedComparisonProgress>("/api/feed-comparison", {
      query: { compact: 1 },
    }),

  saveOwnSite: (site: OwnSite) => {
    const { id, ...body } = site;
    return $fetch<{ own_site: OwnSite; revision: string }>(
      site.id
        ? `/api/feed-comparison/own-sites/${site.id}`
        : "/api/feed-comparison/own-sites",
      { method: id ? "PATCH" : "POST", body },
    );
  },

  removeOwnSite: (id: number) =>
    $fetch<{ ok: boolean; id: number; revision: string }>(`/api/feed-comparison/own-sites/${id}`, {
      method: "DELETE",
    }),

  saveSupplier: (supplier: SupplierFeed) => {
    const { id, ...body } = supplier;
    return $fetch<{ supplier: SupplierFeed; revision: string }>(
      supplier.id
        ? `/api/feed-comparison/suppliers/${supplier.id}`
        : "/api/feed-comparison/suppliers",
      { method: id ? "PATCH" : "POST", body },
    );
  },

  removeSupplier: (id: number) =>
    $fetch<{ ok: boolean; id: number; revision: string }>(`/api/feed-comparison/suppliers/${id}`, {
      method: "DELETE",
    }),

  start: () =>
    $fetch<FeedComparisonProgress>("/api/feed-comparison/start", {
      method: "POST",
    }),

  stop: () =>
    $fetch<FeedComparisonProgress>("/api/feed-comparison/stop", {
      method: "POST",
    }),
};
