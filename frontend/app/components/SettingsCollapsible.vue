<script setup lang="ts">
withDefaults(
  defineProps<{
    defaultOpen?: boolean;
    disabled?: boolean;
    contentClass?: string;
  }>(),
  {
    defaultOpen: false,
    disabled: false,
    contentClass: "",
  },
);
</script>

<template>
  <UCollapsible
    :default-open="defaultOpen"
    :disabled="disabled"
    class="settings-details"
  >
    <template #default="{ open }">
      <UButton
        type="button"
        color="neutral"
        variant="ghost"
        block
        class="settings-details-trigger"
      >
        <span class="settings-details-label">
          <slot name="label" />
        </span>
        <UIcon
          name="i-lucide-chevron-down"
          class="settings-details-chevron"
          :class="{ open }"
        />
      </UButton>
    </template>

    <template #content>
      <div :class="['settings-details-content', contentClass]">
        <slot />
      </div>
    </template>
  </UCollapsible>
</template>
