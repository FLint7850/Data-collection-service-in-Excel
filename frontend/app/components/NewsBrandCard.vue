<script setup lang="ts">
import type { NewsMonitorSummary, NewsSummaryState } from "~/types/api";
import { formatDateTime, hostFromUrl } from "~/utils/format";

const props = defineProps<{
  brand: string;
  group: string;
  monitors: NewsMonitorSummary[];
  state: NewsSummaryState;
}>();

const emit = defineEmits<{
  open: [];
  action: [action: "pause" | "resume" | "stop" | "reset-visual"];
  remove: [];
}>();

const progress = computed(() =>
  Math.max(0, Math.min(100, Number(props.state.percent || 0))),
);
const missingFeeds = computed(() => props.state.missing_by_feed || []);
const isActive = computed(() =>
  ["running", "queued", "pausing", "stopping"].includes(props.state.status),
);
const menuItems = computed(() => [
  [
    ...(!isActive.value
      ? [
          {
            label: "Сбросить",
            icon: "i-lucide-rotate-ccw",
            onSelect: () => emit("action", "reset-visual"),
          },
        ]
      : []),
    {
      label: "Удалить бренд",
      icon: "i-lucide-trash-2",
      color: "error" as const,
      onSelect: () => emit("remove"),
    },
  ],
]);
const hasDiagnostics = computed(() =>
  [
    props.state.in_memory_products,
    props.state.queue_size,
    props.state.active_tasks,
    props.state.failed_pages,
    props.state.availability_skipped,
  ].some((value) => value !== undefined),
);
</script>

<template>
  <UCard
    as="article"
    variant="subtle"
    class="news-brand-card"
    tabindex="0"
    :ui="{ body: 'news-brand-card-body' }"
    @click="emit('open')"
  >
    <div class="news-card-head">
      <div class="brand-avatar">{{ brand.slice(0, 2).toUpperCase() }}</div>
      <div class="news-card-title">
        <strong>{{ brand }}</strong>
        <span>{{ monitors.length }} {{ monitors.length === 1 ? "донор" : "донора" }}</span>
      </div>
      <UDropdownMenu :items="menuItems">
        <UButton
          icon="i-lucide-ellipsis"
          color="neutral"
          variant="ghost"
          size="sm"
          @click.stop
        />
      </UDropdownMenu>
    </div>

    <div class="news-donor-list">
      <span v-for="monitor in monitors.slice(0, 3)" :key="monitor.id">
        <span class="tiny-dot" />
        {{ hostFromUrl(monitor.site_url || monitor.start_urls?.[0]) }}
      </span>
      <span v-if="monitors.length > 3">+ ещё {{ monitors.length - 3 }}</span>
    </div>

    <div class="news-card-status">
      <StatusBadge :status="state.status" context="news" />
    </div>

    <div class="news-card-progress">
      <div>
        <span>Прогресс</span>
        <strong>{{ progress }}%</strong>
      </div>
      <UProgress :model-value="progress" color="primary" size="xs" />
    </div>

    <div class="news-card-metrics">
      <div>
        <strong>{{ state.processed || 0 }}</strong>
        <span>страниц</span>
      </div>
      <div>
        <strong>{{ state.found_products || 0 }}</strong>
        <span>товаров</span>
      </div>
      <div>
        <strong>{{ state.compared_products || 0 }}</strong>
        <span>сравнено</span>
      </div>
      <div class="news-card-metric-accent">
        <strong>{{ state.new_count || 0 }}</strong>
        <span>новинок</span>
      </div>
    </div>

    <div v-if="hasDiagnostics" class="news-card-diagnostics">
      <UBadge color="neutral" variant="subtle">
        В памяти: {{ state.in_memory_products || 0 }}
      </UBadge>
      <UBadge color="neutral" variant="subtle">
        Очередь: {{ state.queue_size || 0 }}
      </UBadge>
      <UBadge color="neutral" variant="subtle">
        Активно: {{ state.active_tasks || 0 }}
      </UBadge>
      <UBadge
        v-if="state.failed_pages !== undefined"
        :color="state.failed_pages ? 'error' : 'neutral'"
        variant="subtle"
      >
        Ошибок: {{ state.failed_pages || 0 }}
      </UBadge>
      <UBadge
        v-if="state.availability_skipped !== undefined"
        color="neutral"
        variant="subtle"
      >
        По статусу: {{ state.availability_skipped || 0 }}
      </UBadge>
    </div>

    <UCard
      v-if="missingFeeds.length || state.new_count !== undefined"
      as="section"
      variant="subtle"
      class="news-card-missing"
      :ui="{ body: 'p-3 sm:p-3' }"
    >
      <div class="news-card-missing-head">
        <span>Результат по фидам</span>
        <UBadge color="primary" variant="subtle">
          {{ state.new_count || 0 }} всего
        </UBadge>
      </div>
      <div v-if="missingFeeds.length" class="news-card-missing-list">
        <div v-for="feed in missingFeeds" :key="feed.source || feed.url">
          <span>Нет на {{ feed.source_label || feed.name || feed.source || "фиде" }}</span>
          <strong>{{ feed.count || 0 }}</strong>
        </div>
      </div>
      <p v-else>Новинок не найдено</p>
    </UCard>

    <div
      v-if="state.last_event || state.last_warning || state.error"
      class="news-card-events"
    >
      <p v-if="state.last_warning" class="news-card-warning">
        <UIcon name="i-lucide-triangle-alert" />
        <span>{{ state.last_warning }}</span>
      </p>
      <p v-else-if="state.last_event">
        <UIcon name="i-lucide-activity" />
        <span>{{ state.last_event }}</span>
      </p>
      <p v-if="state.error" class="news-card-error">
        <UIcon name="i-lucide-circle-alert" />
        <span>{{ state.error }}</span>
      </p>
    </div>

    <div class="news-card-last-scan">
      <span>Последняя проверка</span>
      <strong>{{ state.last_scan_at ? formatDateTime(state.last_scan_at) : "—" }}</strong>
    </div>

    <div v-if="isActive || state.status === 'partial'" class="news-card-actions" @click.stop>
      <UButton
        v-if="['running', 'queued'].includes(state.status)"
        color="warning"
        variant="soft"
        size="sm"
        icon="i-lucide-pause"
        @click="emit('action', 'pause')"
      >
        Пауза
      </UButton>
      <UButton
        v-if="state.status === 'partial'"
        color="primary"
        variant="soft"
        size="sm"
        icon="i-lucide-play"
        @click="emit('action', 'resume')"
      >
        Продолжить
      </UButton>
      <UButton
        v-if="['running', 'queued', 'pausing', 'stopping'].includes(state.status)"
        color="error"
        variant="soft"
        size="sm"
        icon="i-lucide-square"
        @click="emit('action', 'stop')"
      >
        Стоп
      </UButton>
    </div>
  </UCard>
</template>
