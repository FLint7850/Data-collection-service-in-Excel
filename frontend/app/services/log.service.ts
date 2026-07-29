import type { LogsResponse } from "~/types/api";

export const logService = {
  list: (page = 1, limit = 200) =>
    $fetch<LogsResponse>("/api/logs", {
      query: { page, limit },
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
