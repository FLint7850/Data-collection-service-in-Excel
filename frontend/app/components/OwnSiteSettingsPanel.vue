<script setup lang="ts">
import type { OwnSite } from "~/types/api";

const sites = defineModel<OwnSite[]>({ required: true });

function addSite() {
  sites.value.push({ name: "", feed_url: "", feed_generate_url: "" });
}
</script>

<template>
  <UCard as="section" variant="outline" class="panel settings-main-panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ИСТОЧНИКИ ДАННЫХ</p>
        <h2><strong>Фиды моих сайтов</strong></h2>
        <p>Используются в мониторинге новинок, импорте файлов и сравнении поставщиков.</p>
      </div>
      <UButton color="neutral" variant="soft" icon="i-lucide-plus" @click="addSite">
        Добавить фид
      </UButton>
    </div>

    <div v-if="sites.length" class="site-settings-list">
      <UCard
        v-for="(site, index) in sites"
        :key="site.id || index"
        as="article"
        variant="subtle"
        class="site-settings-card"
        :ui="{ body: 'site-settings-card-body' }"
      >
        <span class="feed-card-icon mint-icon"><UIcon name="i-lucide-store" /></span>
        <div class="site-settings-fields">
          <UFormField label="Название">
            <UInput v-model="site.name" placeholder="Мой магазин" class="w-full" />
          </UFormField>
          <UFormField label="XML-фид">
            <UInput v-model="site.feed_url" type="url" placeholder="https://example.ru/feed.xml" class="w-full" />
          </UFormField>
          <UFormField label="Ссылка генерации">
            <UInput v-model="site.feed_generate_url" type="url" placeholder="https://example.ru/index.php" class="w-full" />
          </UFormField>
        </div>
        <UButton
          color="error"
          variant="ghost"
          icon="i-lucide-trash-2"
          aria-label="Удалить фид"
          @click="sites.splice(index, 1)"
        />
      </UCard>
    </div>

    <EmptyState
      v-else
      icon="i-lucide-store"
      title="Нет фидов сайтов"
      description="Добавьте XML-фид хотя бы одного собственного магазина."
    >
      <UButton color="primary" variant="soft" icon="i-lucide-plus" @click="addSite">
        Добавить фид
      </UButton>
    </EmptyState>
  </UCard>
</template>
