import type { NewsMonitor, ProgressPayload } from "../types/api";
import { mergeProgressState } from "./progress-state";

export function mergeNewsMonitor(
  current: NewsMonitor | undefined,
  incoming: NewsMonitor,
): NewsMonitor {
  if (!current) return incoming;
  return {
    ...current,
    ...incoming,
    state: mergeProgressState(current.state, incoming.state),
  };
}

export function upsertNewsMonitor(
  monitors: NewsMonitor[],
  incoming: NewsMonitor,
): NewsMonitor[] {
  const index = monitors.findIndex((monitor) => monitor.id === incoming.id);
  if (index === -1) return [...monitors, incoming];
  return monitors.map((monitor, currentIndex) =>
    currentIndex === index ? mergeNewsMonitor(monitor, incoming) : monitor,
  );
}

export function mergeNewsProgress(
  current: NewsMonitor[],
  payload: ProgressPayload,
): NewsMonitor[] {
  const hasChanges = Boolean(
    payload.replace_news ||
      payload.upsert_news?.length ||
      payload.news?.length ||
      payload.removed_news_ids?.length,
  );
  if (!hasChanges) return current;

  const monitors = new Map(current.map((monitor) => [monitor.id, monitor]));

  if (payload.replace_news) {
    const currentIds = new Set(
      (payload.upsert_news || []).map((monitor) => monitor.id),
    );
    for (const id of monitors.keys()) {
      if (!currentIds.has(id)) monitors.delete(id);
    }
  }

  for (const incoming of payload.upsert_news || []) {
    monitors.set(
      incoming.id,
      mergeNewsMonitor(monitors.get(incoming.id), incoming),
    );
  }

  for (const incoming of payload.news || []) {
    const monitor = monitors.get(incoming.id);
    if (monitor) {
      monitors.set(incoming.id, {
        ...monitor,
        state: mergeProgressState(monitor.state, incoming.state),
      });
    }
  }

  for (const id of payload.removed_news_ids || []) monitors.delete(id);

  return [...monitors.values()];
}
