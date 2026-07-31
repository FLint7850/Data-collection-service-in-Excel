<script setup lang="ts">
defineProps<{
  status: string;
  actionLoading: string;
  active: boolean;
  startButtonLabel: string;
}>();

const emit = defineEmits<{
  start: [];
  action: [action: "pause" | "soft-pause" | "stop" | "restart"];
}>();
</script>

<template>
  <div class="run-actions">
    <UButton
      color="primary"
      icon="i-lucide-play"
      :loading="actionLoading === 'start' || actionLoading === 'resume'"
      :disabled="active && status !== 'paused'"
      @click="emit('start')"
    >
      {{ startButtonLabel }}
    </UButton>
    <UButton
      color="neutral"
      variant="soft"
      :icon="status === 'paused' ? 'i-lucide-play' : 'i-lucide-pause'"
      :loading="actionLoading === 'soft-pause'"
      :disabled="!['running', 'paused'].includes(status)"
      @click="status === 'paused' ? emit('start') : emit('action', 'soft-pause')"
    >
      {{ status === "paused" ? "Продолжить" : "Пауза" }}
    </UButton>
    <UButton
      color="warning"
      variant="soft"
      icon="i-lucide-file-check-2"
      :loading="actionLoading === 'pause'"
      :disabled="status !== 'running'"
      @click="emit('action', 'pause')"
    >
      Пауза с результатом
    </UButton>
    <UButton
      color="neutral"
      variant="soft"
      icon="i-lucide-rotate-cw"
      :loading="actionLoading === 'restart'"
      :disabled="active"
      @click="emit('action', 'restart')"
    >
      Перезапустить
    </UButton>
    <UButton
      color="error"
      variant="soft"
      icon="i-lucide-square"
      :loading="actionLoading === 'stop'"
      :disabled="!active && status === 'idle'"
      @click="emit('action', 'stop')"
    >
      Остановить
    </UButton>
  </div>
</template>
