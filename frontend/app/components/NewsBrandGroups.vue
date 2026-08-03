<script setup lang="ts">
import type { NewsMonitorSummary, NewsSummaryState } from "~/types/api";

export interface NewsBrandGroupItem {
  key: string;
  group: string;
  brand: string;
  brandId?: number;
  monitors: NewsMonitorSummary[];
  state: NewsSummaryState;
}

defineProps<{
  groups: Array<{ group: string; items: NewsBrandGroupItem[] }>;
}>();

const emit = defineEmits<{
  open: [brand: NewsBrandGroupItem];
  action: [brand: NewsBrandGroupItem, action: "pause" | "resume" | "stop" | "reset-visual"];
  remove: [brand: NewsBrandGroupItem];
}>();
</script>

<template>
  <div class="news-groups">
    <UCard
      v-for="section in groups"
      :key="section.group"
      as="section"
      variant="outline"
      class="news-group-panel"
      :ui="{ body: 'p-3' }"
    >
      <UCollapsible default-open>
        <template #default="{ open }">
          <UButton
            type="button"
            color="neutral"
            variant="ghost"
            block
            class="news-group-header"
          >
            <span class="news-group-icon"><UIcon name="i-lucide-layers-3" /></span>
            <span>
              <strong>{{ section.group }}</strong>
              <small>{{ section.items.length }} брендов</small>
            </span>
            <UIcon
              name="i-lucide-chevron-down"
              class="settings-details-chevron"
              :class="{ open }"
            />
          </UButton>
        </template>

        <template #content>
          <div class="news-brand-grid">
            <NewsBrandCard
              v-for="brand in section.items"
              :key="brand.key"
              :brand="brand.brand"
              :group="brand.group"
              :monitors="brand.monitors"
              :state="brand.state"
              @open="emit('open', brand)"
              @action="emit('action', brand, $event)"
              @remove="emit('remove', brand)"
            />
          </div>
        </template>
      </UCollapsible>
    </UCard>
  </div>
</template>
