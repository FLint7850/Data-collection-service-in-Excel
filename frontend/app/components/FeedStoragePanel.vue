<script setup lang="ts">
import type { StoredFeed } from "~/types/api";
import { formatFileSize } from "~/utils/format";

defineProps<{ feeds: StoredFeed[] }>();
</script>

<template>
  <UCard as="section" variant="outline" class="panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ХРАНИЛИЩЕ</p>
        <h2><strong>Последние фиды</strong></h2>
      </div>
      <span class="settings-icon blue-icon"><UIcon name="i-lucide-database" /></span>
    </div>

    <div v-if="feeds.length" class="stored-feed-list">
      <UButton
        v-for="feed in feeds"
        as="a"
        color="neutral"
        variant="ghost"
        :key="`${feed.source}-${feed.filename}`"
        :href="`/api/news/feeds/${encodeURIComponent(feed.source || '')}/${encodeURIComponent(feed.filename || '')}`"
        class="stored-feed-item"
      >
        <span><UIcon name="i-lucide-file-code-2" /></span>
        <div>
          <strong>{{ feed.label || feed.filename }}</strong>
          <small>{{ formatFileSize(feed.size) }} · {{ feed.created_at || "сохранённый снимок" }}</small>
        </div>
        <UIcon name="i-lucide-download" />
      </UButton>
    </div>
    <p v-else class="inline-empty">Снимки фидов появятся после первого мониторинга.</p>
  </UCard>
</template>
