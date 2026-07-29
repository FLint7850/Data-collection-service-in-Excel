<script setup lang="ts">
defineProps<{
  icon: string;
  title: string;
  description: string;
}>();
</script>

<template>
  <UCard variant="subtle" class="empty-state" :ui="{ body: 'empty-state-body' }">
    <span class="empty-state-icon"><UIcon :name="icon" /></span>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <slot />
  </UCard>
</template>
