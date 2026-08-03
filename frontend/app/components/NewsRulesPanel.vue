<script setup lang="ts">
import type { NewsMonitor } from "~/types/api";

const monitor = defineModel<NewsMonitor>({ required: true });
</script>

<template>
  <UCard as="section" variant="outline" class="panel settings-stack">
    <div class="panel-header"><div><p class="eyebrow">ФИЛЬТРЫ</p><h2><strong>Правила обхода</strong></h2></div></div>
    <SettingsCollapsible class="mt-3">
      <template #label>Исключения разделов <UBadge color="neutral" variant="subtle">{{ monitor.exclusions.length }}</UBadge></template>
      <PatternEditor :model-value="monitor.exclusions" placeholder="/catalog/sale/" @add="monitor.exclusions.push($event)" @remove="monitor.exclusions.splice($event, 1)" />
    </SettingsCollapsible>
    <SettingsCollapsible>
      <template #label>Фильтр товарных URL <UBadge color="neutral" variant="subtle">{{ monitor.product_url_filters.length }}</UBadge></template>
      <PatternEditor :model-value="monitor.product_url_filters" placeholder="-model-" @add="monitor.product_url_filters.push($event)" @remove="monitor.product_url_filters.splice($event, 1)" />
    </SettingsCollapsible>
    <SettingsCollapsible>
      <template #label>Исключения товарных URL <UBadge color="neutral" variant="subtle">{{ monitor.product_url_exclusions.length }}</UBadge></template>
      <PatternEditor :model-value="monitor.product_url_exclusions" placeholder="/recommend" @add="monitor.product_url_exclusions.push($event)" @remove="monitor.product_url_exclusions.splice($event, 1)" />
    </SettingsCollapsible>
    <SettingsCollapsible content-class="form-grid">
      <template #label>Селекторы и правила модели</template>
      <UFormField label="Селектор названия"><UInput v-model="monitor.selector_settings.name_selector" placeholder="h1" class="w-full" /></UFormField>
      <UFormField label="Селектор наличия"><UInput v-model="monitor.selector_settings.availability_selector" placeholder=".stock" class="w-full" /></UFormField>
      <UFormField label="Карточка товара"><UInput v-model="monitor.extraction_rules.product_card_selector" placeholder=".product-card" class="w-full" /></UFormField>
      <UFormField label="Ссылка товара"><UInput v-model="monitor.extraction_rules.product_url_selector" placeholder="a[href]" class="w-full" /></UFormField>
      <UFormField label="Селектор модели"><UInput v-model="monitor.extraction_rules.model_selector" placeholder=".model" class="w-full" /></UFormField>
      <UFormField label="Селектор цены"><UInput v-model="monitor.extraction_rules.price_selector" placeholder=".price" class="w-full" /></UFormField>
      <UFormField label="Начало парсинга модели" class="field-span-2"><UInput v-model="monitor.extraction_rules.model_start_marker" placeholder="<h1 class=&quot;detail__title&quot;>" class="w-full" /></UFormField>
      <UFormField label="Конец парсинга модели" class="field-span-2"><UInput v-model="monitor.extraction_rules.model_end_marker" placeholder="</h1>" class="w-full" /></UFormField>
      <UFormField label="Правила замены" class="field-span-2"><UTextarea v-model="monitor.extraction_rules.model_replace_rules" :rows="4" class="w-full code-input" /></UFormField>
    </SettingsCollapsible>
    <SettingsCollapsible>
      <template #label>Исключения по статусу <UBadge color="neutral" variant="subtle">{{ monitor.selector_settings.availability_exclusions?.length || 0 }}</UBadge></template>
      <UFormField label="Статусы, при которых товар не считается новинкой" description="По одному фрагменту статуса на строку.">
        <UTextarea
          :model-value="(monitor.selector_settings.availability_exclusions || []).join('\n')"
          :rows="4"
          class="w-full"
          placeholder="Снят с производства&#10;Нет в наличии"
          @update:model-value="monitor.selector_settings.availability_exclusions = String($event).split(/\r?\n/).map((item) => item.trim()).filter(Boolean)"
        />
      </UFormField>
    </SettingsCollapsible>
  </UCard>
</template>
