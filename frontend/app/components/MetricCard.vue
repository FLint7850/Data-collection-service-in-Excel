<script setup lang="ts">
defineProps<{
  label: string;
  value: string | number;
  hint?: string;
  icon: string;
  tone?: "mint" | "blue" | "amber" | "red" | "purple";
}>();
</script>

<template>
  <UCard
    as="article"
    variant="subtle"
    class="metric-card"
    :ui="{ body: 'metric-card-body' }"
  >
    <span class="metric-icon" :class="`${tone || 'mint'}-icon`">
      <UIcon :name="icon" />
    </span>
    <div>
      <span>{{ label }}</span>
      <strong>{{ value }}</strong>
    </div>
    <small v-if="hint" class="metric-hint">{{ hint }}</small>
  </UCard>
</template>
