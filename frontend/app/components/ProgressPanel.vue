<script setup lang="ts">
import type { ScanState } from "~/types/api";
import { formatDuration } from "~/utils/format";

const props = defineProps<{
  state: ScanState;
  downloadUrl?: string;
}>();

const percent = computed(() => Math.max(0, Math.min(100, Number(props.state.percent || 0))));
</script>

<template>
  <UCard as="section" variant="outline" class="panel progress-panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ТЕКУЩАЯ СЕССИЯ</p>
        <h3>Ход сбора</h3>
      </div>
      <div class="progress-actions">
        <StatusBadge :status="state.status" />
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

    <div class="progress-time-grid">
      <div>
        <span>Прошло</span>
        <strong>{{ formatDuration(state.elapsed_seconds) }}</strong>
      </div>
      <div>
        <span>Осталось</span>
        <strong>{{ state.eta_seconds == null ? "—" : formatDuration(state.eta_seconds) }}</strong>
      </div>
    </div>

    <div class="current-url">
      <UIcon name="i-lucide-link-2" />
      <span>{{ state.currenturl || "Текущий URL появится после запуска." }}</span>
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
      <div class="stat flex gap-1">
        <span class="stat-value">{{ state.skipped || 0 }}</span>
        <span class="stat-label">Пропущено</span>
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
