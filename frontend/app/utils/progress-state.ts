const ACTIVE_PROGRESS_STATUSES = new Set([
  "running",
  "queued",
  "pausing",
  "stopping",
]);

const RESUMABLE_PROGRESS_STATUSES = new Set([
  ...ACTIVE_PROGRESS_STATUSES,
  "partial",
  "paused",
]);

const STABLE_PROGRESS_FIELDS = [
  "stage",
  "percent",
  "currenturl",
  "totalprocessed",
  "processed_products",
  "processed",
  "found_products",
  "candidate_products",
  "compared_products",
  "in_memory_products",
  "queue_size",
  "active_tasks",
  "active_urls",
  "skipped",
  "failed_pages",
  "availability_skipped",
  "stall_seconds",
  "new_count",
  "missing_by_feed",
  "last_event",
  "last_warning",
  "last_scan_at",
  "last_csv",
  "filename",
  "started_at",
  "elapsed_seconds",
  "current_row",
  "total_rows",
  "processed_rows",
  "excluded_rows",
  "found_rows",
  "missing_rows",
  "model_not_found_rows",
  "current_supplier",
  "suppliers_done",
  "suppliers_total",
  "result_filename",
] as const;

function statusOf(state: Record<string, unknown>) {
  return String(state.status || "");
}

function isSameProgressRun(
  previous: Record<string, unknown>,
  incoming: Record<string, unknown>,
) {
  const previousStatus = statusOf(previous);
  const incomingStatus = statusOf(incoming);
  if (
    !ACTIVE_PROGRESS_STATUSES.has(incomingStatus) ||
    !RESUMABLE_PROGRESS_STATUSES.has(previousStatus)
  ) {
    return false;
  }

  const previousStartedAt = String(previous.started_at || "");
  const incomingStartedAt = String(incoming.started_at || "");
  if (previousStartedAt && incomingStartedAt) {
    return previousStartedAt === incomingStartedAt;
  }

  return ACTIVE_PROGRESS_STATUSES.has(previousStatus);
}

function isTransientEmpty(value: unknown, previous: unknown) {
  if (previous === undefined || previous === null || previous === "") return false;
  if (typeof value === "number") return value === 0 && Number(previous) > 0;
  if (typeof value === "string") return value === "" && String(previous) !== "";
  if (Array.isArray(value)) return value.length === 0 && Array.isArray(previous) && previous.length > 0;
  return value === null;
}

export function mergeProgressState<T extends object>(
  previous: T | null | undefined,
  incoming: T,
): T {
  if (!previous) return incoming;

  const previousRecord = previous as Record<string, unknown>;
  const incomingRecord = incoming as Record<string, unknown>;
  const merged = { ...previousRecord, ...incomingRecord };
  if (!isSameProgressRun(previousRecord, incomingRecord)) return merged as T;

  for (const field of STABLE_PROGRESS_FIELDS) {
    if (
      field in incomingRecord &&
      isTransientEmpty(incomingRecord[field], previousRecord[field])
    ) {
      merged[field] = previousRecord[field];
    }
  }
  return merged as T;
}
