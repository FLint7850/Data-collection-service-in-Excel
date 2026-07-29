<script setup lang="ts">
import type { NewsMonitor, ScanState } from "~/types/api";
import { formatDateTime, hostFromUrl } from "~/utils/format";

defineProps<{
  brand: string;
  group: string;
  monitors: NewsMonitor[];
  state: ScanState;
}>();

const emit = defineEmits<{
  open: [];
  action: [action: "pause" | "resume" | "stop" | "reset-visual"];
  remove: [];
}>();
</script>

<template>
  <UCard
    as="article"
    variant="subtle"
    class="news-brand-card"
    tabindex="0"
    :ui="{ body: 'news-brand-card-body' }"
    @click="emit('open')"
    @keyup.enter="emit('open')"
  >
    <div class="news-card-head">
      <div class="brand-avatar">{{ brand.slice(0, 2).toUpperCase() }}</div>
      <div class="news-card-title">
        <strong>{{ brand }}</strong>
        <span>{{ monitors.length }} {{ monitors.length === 1 ? "донор" : "донора" }}</span>
      </div>
      <UDropdownMenu
        :items="[
          [
            {
              label: 'Удалить бренд',
              icon: 'i-lucide-trash-2',
              color: 'error',
              onSelect: () => emit('remove'),
            },
          ],
        ]"
      >
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
      <StatusBadge :status="state.status" />
      <span>{{ state.stage || (state.last_scan_at ? `Проверка ${formatDateTime(state.last_scan_at)}` : "Ещё не запускался") }}</span>
    </div>

    <div class="news-card-progress">
      <div>
        <span>Прогресс</span>
        <strong>{{ state.percent || 0 }}%</strong>
      </div>
      <UProgress :model-value="state.percent || 0" color="primary" size="xs" />
    </div>

    <div class="news-card-metrics">
      <div>
        <strong>{{ state.new_count || 0 }}</strong>
        <span>новых</span>
      </div>
      <div>
        <strong>{{ state.found_products || 0 }}</strong>
        <span>товаров</span>
      </div>
      <div>
        <strong>{{ state.failed_pages || 0 }}</strong>
        <span>ошибок</span>
      </div>
    </div>

    <div class="news-card-actions" @click.stop>
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
      <UButton
        v-else
        color="neutral"
        variant="ghost"
        size="sm"
        icon="i-lucide-rotate-ccw"
        @click="emit('action', 'reset-visual')"
      >
        Сбросить
      </UButton>
      <UButton
        color="neutral"
        variant="ghost"
        size="sm"
        trailing-icon="i-lucide-arrow-up-right"
        @click="emit('open')"
      >
        Настроить
      </UButton>
    </div>
  </UCard>
</template>
