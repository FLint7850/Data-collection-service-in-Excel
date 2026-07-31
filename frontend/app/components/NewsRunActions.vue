<script setup lang="ts">
import type { ScanState } from "~/types/api";

defineProps<{
  state: ScanState;
  monitorId: string;
  actionLoading: string;
  active: boolean;
  canResume: boolean;
}>();

const enabled = defineModel<boolean>("enabled", { required: true });

const emit = defineEmits<{
  action: [action: "scan" | "pause" | "resume" | "stop" | "reset-visual"];
}>();
</script>

<template>
  <div class="news-run-actions flex-1 justify-between">
    <div class="flex gap-1 items-center">
      <USwitch v-model="enabled" />
      <StatusBadge :status="state.status" context="news" size="xl" />
    </div>
    <div class="flex gap-1">
      <UButton
        v-if="state.csv_ready"
        :to="`/api/news/monitors/${monitorId}/download`"
        external
        color="primary"
        variant="soft"
        icon="i-lucide-download"
      >
        Скачать CSV
      </UButton>
      <UButton
        v-if="!active && !canResume"
        icon="i-lucide-radar"
        :loading="actionLoading === 'scan'"
        @click="emit('action', 'scan')"
      >
        Проверить новинки
      </UButton>
      <UButton
        v-if="canResume"
        color="primary"
        icon="i-lucide-play"
        :loading="actionLoading === 'resume'"
        @click="emit('action', 'resume')"
      >
        Продолжить
      </UButton>
      <UButton
        v-if="['running', 'queued'].includes(state.status)"
        color="warning"
        variant="soft"
        icon="i-lucide-pause"
        :loading="actionLoading === 'pause'"
        @click="emit('action', 'pause')"
      >
        Пауза
      </UButton>
      <UButton
        v-if="active"
        color="error"
        variant="soft"
        icon="i-lucide-square"
        :loading="actionLoading === 'stop'"
        @click="emit('action', 'stop')"
      >
        Стоп
      </UButton>
      <UButton
        v-if="!active"
        color="neutral"
        variant="ghost"
        icon="i-lucide-rotate-ccw"
        @click="emit('action', 'reset-visual')"
      >
        Сбросить
      </UButton>
    </div>
  </div>
</template>
