import { newsService } from "~/services/news.service";
import type { NewsBrandSearchResult } from "~/types/api";
import { errorMessage } from "~/utils/format";

export function useNewsBrandSearch(debounceMs = 2500) {
  const searchTerm = ref("");
  const results = ref<NewsBrandSearchResult[]>([]);
  const loading = ref(false);
  const error = ref("");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let requestId = 0;

  const search = async (query: string, currentRequestId: number) => {
    controller = new AbortController();
    loading.value = true;
    try {
      const response = await newsService.searchBrands(query, controller.signal);
      if (currentRequestId !== requestId) return;
      results.value = response.brands;
    } catch (caught) {
      if (currentRequestId !== requestId) return;
      error.value = errorMessage(caught, "Не удалось выполнить поиск");
      results.value = [];
    } finally {
      if (currentRequestId === requestId) {
        loading.value = false;
        controller = undefined;
      }
    }
  };

  watch(searchTerm, (value) => {
    if (timer) clearTimeout(timer);
    timer = undefined;
    controller?.abort();
    controller = undefined;
    loading.value = false;
    error.value = "";
    results.value = [];

    const query = value.trim();
    const currentRequestId = ++requestId;
    if (query.length < 2) return;

    loading.value = true;
    timer = setTimeout(() => {
      timer = undefined;
      void search(query, currentRequestId);
    }, debounceMs);
  });

  onScopeDispose(() => {
    if (timer) clearTimeout(timer);
    requestId += 1;
    controller?.abort();
  });

  return {
    searchTerm,
    results,
    loading,
    error,
  };
}
