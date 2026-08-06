import type {
  PriceConverterData,
  PriceConverterRuntime,
  PriceConverterSettings,
} from "~/types/api";

export const priceConverterService = {
  get: () => $fetch<PriceConverterData>("/api/price-converter"),

  getRuntime: () =>
    $fetch<PriceConverterRuntime>("/api/price-converter", {
      query: { compact: 1 },
    }),

  saveSettings: (body: Partial<PriceConverterSettings>) =>
    $fetch<PriceConverterSettings>("/api/price-converter", {
      method: "PATCH",
      body,
    }),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return $fetch<PriceConverterData>("/api/price-converter", {
      method: "POST",
      body: form,
    });
  },

  remove: () =>
    $fetch<PriceConverterData>("/api/price-converter", {
      method: "DELETE",
    }),

  convert: () =>
    $fetch<PriceConverterRuntime>("/api/price-converter/convert", {
      method: "POST",
    }),
};
