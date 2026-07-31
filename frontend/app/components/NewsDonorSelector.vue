<script setup lang="ts">
import type { NewsMonitor } from "~/types/api";
import { hostFromUrl } from "~/utils/format";

defineProps<{
  monitors: NewsMonitor[];
  adding: boolean;
}>();

const emit = defineEmits<{
  add: [];
}>();

const selectedId = defineModel<string>("selectedId", { required: true });
const addUrl = defineModel<string>("addUrl", { required: true });
</script>

<template>
  <UCard as="section" variant="outline" class="panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ДОНОРЫ</p>
        <h2><strong>Добавить сайт</strong></h2>
      </div>
    </div>
    <div class="add-donor-form">
      <UInput
        v-model="addUrl"
        placeholder="https://supplier.ru"
        class="w-full"
      />
      <UButton
        color="neutral"
        variant="soft"
        icon="i-lucide-plus"
        :loading="adding"
        :disabled="!addUrl.trim()"
        @click="emit('add')"
      >
        Добавить
      </UButton>
    </div>
    <div class="donor-mini-list">
      <button
        v-for="monitor in monitors"
        :key="monitor.id"
        type="button"
        :class="{ active: monitor.id === selectedId }"
        @click="selectedId = monitor.id"
      >
        <span class="tiny-dot" />
        <span>
          <strong>
            {{ hostFromUrl(monitor.site_url || monitor.start_urls?.[0]) }}
          </strong>
          <small>{{ monitor.start_urls.length }} стартовых URL</small>
        </span>
      </button>
    </div>
  </UCard>
</template>
