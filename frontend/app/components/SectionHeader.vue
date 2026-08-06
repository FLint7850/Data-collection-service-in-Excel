<script setup lang="ts">
defineProps<{
  eyebrow?: string;
  title: string;
  description?: string;
}>();
</script>

<template>
  <UPageHeader
    :headline="eyebrow"
    :title="title"
    :description="description"
    class="page-heading"
    :ui="{
      root: 'border-0 py-0',
      headline: 'eyebrow mint',
      description: 'text-base sm:text-lg leading-7 text-muted',
      links: 'heading-actions',
    }"
  >
    <template v-if="$slots.actions" #links>
      <slot name="actions" />
    </template>
  </UPageHeader>
</template>
