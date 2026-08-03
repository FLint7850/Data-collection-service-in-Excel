import type {
  FileImportData,
  FileImportProgress,
  FileImportSettings,
} from "~/types/api";

export const fileImportService = {
  get: () => $fetch<FileImportData>("/api/file-import"),
  getProgress: () =>
    $fetch<FileImportProgress>("/api/file-import", {
      query: { compact: 1 },
    }),

  saveSettings: (body: Partial<FileImportSettings>) =>
    $fetch<FileImportSettings>("/api/file-import", {
      method: "PATCH",
      body,
    }),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return $fetch<FileImportData>("/api/file-import", {
      method: "POST",
      body: form,
    });
  },

  remove: () =>
    $fetch<FileImportData>("/api/file-import", {
      method: "DELETE",
    }),

  compare: () =>
    $fetch<FileImportProgress>("/api/file-import/compare", {
      method: "POST",
    }),

  stop: () =>
    $fetch<FileImportProgress>("/api/file-import/stop", {
      method: "POST",
    }),
};
