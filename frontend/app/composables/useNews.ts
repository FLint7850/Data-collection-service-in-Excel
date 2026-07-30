import { newsService } from "~/services/news.service";
import type {
  NewsMonitor,
  NewsWorkspaceData,
  ProgressPayload,
} from "~/types/api";
import {
  mergeNewsMonitor,
  mergeNewsProgress,
  upsertNewsMonitor,
} from "~/utils/news-progress";

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
        mergeNewsMonitor(
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
    data.value.monitors = upsertNewsMonitor(data.value.monitors, monitor);
  };

  const mergeProgress = (payload: ProgressPayload) => {
    if (payload.cursor) progressCursor.value = payload.cursor;
    if (!data.value) return;
    data.value.monitors = mergeNewsProgress(data.value.monitors, payload);
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
