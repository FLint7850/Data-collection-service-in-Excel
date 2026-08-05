<script setup lang="ts">
import type { ScanState } from "~/types/api";
import { formatDateTime, formatDuration } from "~/utils/format";

const props = withDefaults(
  defineProps<{
    state: ScanState;
    downloadUrl?: string;
    showStatus?: boolean;
    showActiveUrls?: boolean;
    showNewsSummary?: boolean;
  }>(),
  { showNewsSummary: true },
);

const ACTIVE_ELAPSED_STATUSES = new Set([
  "running",
  "queued",
  "pausing",
  "stopping",
]);

const percent = computed(() => Math.max(0, Math.min(100, Number(props.state.percent || 0))));
const elapsedClock = ref(Date.now());
const elapsedAnchorSeconds = ref(Math.max(0, Number(props.state.elapsed_seconds || 0)));
const elapsedAnchorAt = ref(Date.now());
let elapsedRun = String(props.state.started_at || "");
let elapsedWasActive = ACTIVE_ELAPSED_STATUSES.has(props.state.status);
let elapsedTimer: ReturnType<typeof setInterval> | undefined;

function activeElapsedStatus(status: string) {
  return ACTIVE_ELAPSED_STATUSES.has(status);
}

function anchoredElapsed(now: number) {
  if (!elapsedWasActive) return elapsedAnchorSeconds.value;
  return elapsedAnchorSeconds.value + Math.max(
    0,
    Math.floor((now - elapsedAnchorAt.value) / 1000),
  );
}

const displayedElapsedSeconds = computed(() => {
  const incoming = Math.max(0, Number(props.state.elapsed_seconds || 0));
  if (!activeElapsedStatus(props.state.status)) return incoming;
  return Math.max(incoming, anchoredElapsed(elapsedClock.value));
});

watch(
  [
    () => props.state.elapsed_seconds,
    () => props.state.started_at,
    () => props.state.status,
  ],
  ([elapsedValue, startedAt, status]) => {
    const now = Date.now();
    const incoming = Math.max(0, Number(elapsedValue || 0));
    const run = String(startedAt || "");
    const active = activeElapsedStatus(String(status || ""));
    const current = anchoredElapsed(now);

    if (run !== elapsedRun || (!elapsedWasActive && active) || !active || incoming > current) {
      elapsedAnchorSeconds.value = incoming;
      elapsedAnchorAt.value = now;
    }

    elapsedRun = run;
    elapsedWasActive = active;
    elapsedClock.value = now;
  },
);

onMounted(() => {
  elapsedTimer = setInterval(() => {
    if (activeElapsedStatus(props.state.status)) elapsedClock.value = Date.now();
  }, 1000);
});

onBeforeUnmount(() => {
  if (elapsedTimer) clearInterval(elapsedTimer);
});

const activeUrls = computed(() =>
  (props.state.active_urls || []).filter((url): url is string => Boolean(url?.trim())),
);
const hasNewsSummary = computed(() =>
  props.showNewsSummary && [
    props.state.new_count,
    props.state.candidate_products,
    props.state.compared_products,
    props.state.in_memory_products,
    props.state.last_csv,
  ].some((value) => value !== undefined && value !== ""),
);
const hasDiagnostics = computed(() =>
  [
    props.state.queue_size,
    props.state.active_tasks,
    props.state.failed_pages,
    props.state.availability_skipped,
    props.state.stall_seconds,
  ].some((value) => value !== undefined),
);
</script>

<template>
  <UCard as="section" variant="outline" class="panel progress-panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ТЕКУЩАЯ СЕССИЯ</p>
        <h2><strong>Ход сбора</strong></h2>
      </div>
      <div class="progress-actions">
        <StatusBadge v-if="showStatus !== false" :status="state.status" />
        <UButton
          v-if="state.download_ready && downloadUrl"
          :to="downloadUrl"
          external
          icon="i-lucide-download"
          color="primary"
          variant="soft"
          size="sm"
        >
          Скачать CSV
        </UButton>
      </div>
    </div>

    <div class="progress-block">
      <div class="progress-value-row">
        <strong>{{ percent }}%</strong>
        <span>{{ state.stage || state.filename || "Ожидание запуска" }}</span>
      </div>
      <UProgress :model-value="percent" color="primary" size="sm" />
    </div>

    <div v-if="hasNewsSummary" class="news-result-grid">
      <UCard variant="subtle" :ui="{ body: 'news-result-card-body' }">
        <span>Новинок</span>
        <strong>{{ state.new_count || 0 }}</strong>
      </UCard>
      <UCard variant="subtle" :ui="{ body: 'news-result-card-body' }">
        <span>Сравнено</span>
        <strong>
          {{ state.compared_products || 0 }}
          <small>/ {{ state.candidate_products || state.found_products || 0 }}</small>
        </strong>
      </UCard>
      <UCard variant="subtle" :ui="{ body: 'news-result-card-body' }">
        <span>В памяти</span>
        <strong>{{ state.in_memory_products || state.found_products || 0 }}</strong>
      </UCard>
      <UCard
        variant="subtle"
        class="news-result-file"
        :ui="{ body: 'news-result-card-body' }"
      >
        <span>Последний CSV</span>
        <strong :title="state.last_csv || ''">{{ state.last_csv || "—" }}</strong>
      </UCard>
    </div>

    <div class="progress-time-grid">
      <div>
        <span>Прошло</span>
        <strong>{{ formatDuration(displayedElapsedSeconds) }}</strong>
      </div>
      <div v-if="state.last_scan_at">
        <span class="flex gap-1 align-center items-center">
          <UIcon name="i-lucide-calendar-check-2" />
          <span>Последнее сканирование</span>
        </span>
        <strong>{{ formatDateTime(state.last_scan_at) }}</strong>
      </div>
    </div>

    <div class="current-url">
      <UIcon name="i-lucide-link-2" />
      <span>{{ state.currenturl || "Текущий URL появится после запуска." }}</span>
    </div>

    <div v-if="showActiveUrls !== false && activeUrls.length" class="active-url-list">
      <div class="active-url-list-title">
        <span>Сейчас собираются</span>
        <UBadge color="primary" variant="subtle">{{ activeUrls.length }}</UBadge>
      </div>
      <div v-for="url in activeUrls" :key="url" class="active-url-item">
        <span class="tiny-dot" />
        <span>{{ url }}</span>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat flex gap-1">
        <span class="stat-value">{{ state.totalprocessed || state.processed || 0 }}</span>
        <span class="stat-label">Обработано страниц</span>
      </div>
      <div class="stat flex gap-1">
        <span class="stat-value">{{ state.found_products || 0 }}</span>
        <span class="stat-label">Найдено товаров</span>
      </div>
      <div v-if="state.skipped !== undefined" class="stat flex gap-1">
        <span class="stat-value">{{ state.skipped || 0 }}</span>
        <span class="stat-label">Пропущено</span>
      </div>
    </div>

    <div v-if="hasDiagnostics" class="progress-diagnostics-grid">
      <div>
        <span>В очереди</span>
        <strong>{{ state.queue_size || 0 }}</strong>
      </div>
      <div>
        <span>Активных задач</span>
        <strong>{{ state.active_tasks || 0 }}</strong>
      </div>
      <div>
        <span>Ошибок страниц</span>
        <strong>{{ state.failed_pages || 0 }}</strong>
      </div>
      <div>
        <span>Исключено по статусу</span>
        <strong>{{ state.availability_skipped || 0 }}</strong>
      </div>
      <div v-if="state.stall_seconds !== undefined">
        <span>Без прогресса</span>
        <strong>{{ formatDuration(state.stall_seconds) }}</strong>
      </div>
    </div>

    <div v-if="state.last_event || state.last_warning" class="progress-events">
      <div v-if="state.last_event">
        <span>Последнее событие</span>
        <p>{{ state.last_event }}</p>
      </div>
      <div v-if="state.last_warning" class="progress-event-warning">
        <span>Предупреждение</span>
        <p>{{ state.last_warning }}</p>
      </div>
    </div>

    <div v-if="hasNewsSummary" class="missing-feed-list">
      <div class="active-url-list-title">
        <span>Результат по фидам</span>
        <UBadge color="primary" variant="subtle">
          {{ state.new_count || 0 }} всего
        </UBadge>
      </div>
      <p v-if="!state.new_count" class="missing-feed-empty">Новинок не найдено</p>
      <div
        v-for="feed in state.missing_by_feed || []"
        :key="feed.source || feed.url"
        class="missing-feed-item"
      >
        <span>Нет на {{ feed.source_label || feed.name || feed.source || "фиде" }}</span>
        <strong>{{ feed.count || 0 }}</strong>
      </div>
    </div>

    <UAlert
      v-if="state.error"
      color="error"
      variant="subtle"
      icon="i-lucide-triangle-alert"
      :description="state.error"
      class="error-banner"
    />
  </UCard>
</template>
