import type { LogsPollResponse } from "~/types/api";

export const logService = {
  list: (page = 1, limit = 200, signature = "", afterId?: number) =>
    $fetch<LogsPollResponse>("/api/logs", {
      query: {
        page,
        limit,
        signature: signature || undefined,
        after_id: afterId,
      },
    }),

  clear: () =>
    $fetch<{ ok: boolean }>("/api/logs", {
      method: "DELETE",
    }),

  setAutoCleanup: (autoCleanup: boolean) =>
    $fetch<{ auto_cleanup: boolean }>("/api/logs/settings", {
      method: "POST",
      body: { auto_cleanup: autoCleanup },
    }),
};
