import { newsService } from "~/services/news.service";
import type { NewsMonitor, NewsSettings } from "~/types/api";
import { mergeProgressState } from "~/utils/progress-state";

function mergeMonitor(current: NewsMonitor | undefined, incoming: NewsMonitor): NewsMonitor {
  if (!current) return incoming;
  return {
    ...current,
    ...incoming,
    state: mergeProgressState(current.state, incoming.state),
  };
}

export function useNews() {
  const data = useState<NewsSettings | null>("news-settings", () => null);
  const loading = useState<boolean>("news-loading", () => false);

  const merge = (incoming: NewsSettings) => {
    const previous = data.value;
    data.value = {
      ...(previous || incoming),
      ...incoming,
      smtp: { ...(previous?.smtp || incoming.smtp), ...incoming.smtp },
      monitors: incoming.monitors.map((monitor) =>
        mergeMonitor(
          previous?.monitors.find((current) => current.id === monitor.id),
          monitor,
        ),
      ),
    };
  };

  const load = async (summary = true, monitors = true) => {
    loading.value = true;
    try {
      const incoming = await newsService.get({ summary, monitors });
      merge(incoming);
      return data.value;
    } finally {
      loading.value = false;
    }
  };

  const upsertMonitor = (monitor: NewsMonitor) => {
    if (!data.value) return;
    const index = data.value.monitors.findIndex((item) => item.id === monitor.id);
    if (index === -1) data.value.monitors.push(monitor);
    else data.value.monitors[index] = mergeMonitor(data.value.monitors[index], monitor);
  };

  return { data, loading, load, merge, upsertMonitor };
}
