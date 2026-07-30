import { newsService } from "~/services/news.service";
import type {
  NewsMonitor,
  NewsWorkspaceData,
  ProgressPayload,
} from "~/types/api";
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
  const data = useState<NewsWorkspaceData | null>("news-workspace", () => null);
  const progressCursor = useState<string>("news-progress-cursor", () => "");
  const loading = useState<boolean>("news-loading", () => false);

  const merge = (incoming: NewsWorkspaceData) => {
    const previous = data.value;
    data.value = {
      ...(previous || incoming),
      ...incoming,
      monitors: incoming.monitors.map((monitor) =>
        mergeMonitor(
          previous?.monitors.find((current) => current.id === monitor.id),
          monitor,
        ),
      ),
    };
    if (incoming.progress_cursor) progressCursor.value = incoming.progress_cursor;
  };

  const load = async (_summary = true) => {
    loading.value = true;
    try {
      const incoming = await newsService.getWorkspace();
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

  const mergeProgress = (payload: ProgressPayload) => {
    if (payload.cursor) progressCursor.value = payload.cursor;
    if (!data.value) return;
    if (payload.replace_news) {
      const currentIds = new Set(
        (payload.upsert_news || []).map((monitor) => monitor.id),
      );
      data.value.monitors = data.value.monitors.filter((monitor) =>
        currentIds.has(monitor.id),
      );
    }
    for (const monitor of payload.upsert_news || []) upsertMonitor(monitor);
    for (const incoming of payload.news || []) {
      const monitor = data.value.monitors.find((item) => item.id === incoming.id);
      if (monitor) monitor.state = mergeProgressState(monitor.state, incoming.state);
    }
    if (payload.removed_news_ids?.length) {
      const removed = new Set(payload.removed_news_ids);
      data.value.monitors = data.value.monitors.filter((item) => !removed.has(item.id));
    }
  };

  return {
    data,
    progressCursor,
    loading,
    load,
    merge,
    mergeProgress,
    upsertMonitor,
  };
}
