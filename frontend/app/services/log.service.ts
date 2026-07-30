import type { LogsPollResponse } from "~/types/api";

export const logService = {
  list: (page = 1, limit = 200, signature = "", sinceTotal?: number) =>
    $fetch<LogsPollResponse>("/api/logs", {
      query: {
        page,
        limit,
        signature: signature || undefined,
        since_total: sinceTotal,
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
