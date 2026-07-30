<script setup lang="ts">
import { scanStatusColor, scanStatusLabel } from "~/utils/format";

const props = withDefaults(
  defineProps<{
    status?: string;
    context?: "default" | "news";
    size?: "xs" | "sm" | "md" | "lg" | "xl";
  }>(),
  { context: "default", size: 'md' },
);

const newsLabels: Record<string, string> = {
  idle: "Ожидание",
  queued: "В работе",
  running: "В работе",
  pausing: "Приостанавливается",
  partial: "Приостановлено",
  stopping: "Останавливается",
  stopped: "Остановлено",
  complete: "Завершено",
  completed: "Завершено",
  error: "Ошибка",
};

const label = computed(() =>
  props.context === "news"
    ? newsLabels[props.status || "idle"] || props.status || "Ожидание"
    : scanStatusLabel(props.status),
);
</script>

<template>
  <UBadge
    :color="scanStatusColor(props.status)"
    variant="subtle"
    :size="size"
    class="status-badge"
  >
    <span class="status-dot-mini" />
    {{ label }}
  </UBadge>
</template>
