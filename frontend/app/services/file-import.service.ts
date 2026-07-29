import type { FileImportData, FileImportState } from "~/types/api";

export const fileImportService = {
  get: () => $fetch<FileImportData>("/api/file-import"),

  saveSettings: (body: {
    model_field: string;
    price_field: string;
    exclusions: string;
    replace_rules: string;
  }) =>
    $fetch<FileImportData>("/api/file-import", {
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
    $fetch<FileImportState>("/api/file-import/compare", {
      method: "POST",
    }),

  stop: () =>
    $fetch<FileImportData>("/api/file-import/stop", {
      method: "POST",
    }),
};
