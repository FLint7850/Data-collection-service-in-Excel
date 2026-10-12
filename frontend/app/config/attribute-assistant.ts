/**
 * UI-only behavior for Attribute Assistant.
 *
 * Data limits come from the workspace API. These values control interaction
 * timing and presentation only, so operational tuning is no longer scattered
 * through components and composables.
 */
export const ATTRIBUTE_ASSISTANT_UI = Object.freeze({
  searchDebounceMs: 250,
  routeSyncDebounceMs: 180,
  authPollMs: 3_000,
  operationPollMs: 1_400,
  operationRetryMs: 5_000,
  infiniteScrollThresholdPx: 48,
  recentBatchCount: 5,
  recommendedDonorCount: 4,
  skeletonItemCount: 4,
  shopSyncTimeoutMs: 180_000,
});

export const ATTRIBUTE_ASSISTANT_API_BASE = "/api/attribute-assistant";

export const DEFAULT_DASH_REASON = "Не найдено после проверки источников";
