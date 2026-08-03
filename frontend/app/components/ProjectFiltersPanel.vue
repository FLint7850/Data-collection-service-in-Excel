<script setup lang="ts">
import type { Project } from "~/types/api";

const project = defineModel<Project>({ required: true });
defineProps<{ disabled?: boolean }>();
</script>

<template>
  <UCard as="section" variant="outline" class="panel settings-stack">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ФИЛЬТРАЦИЯ</p>
        <h2><strong>Исключения и URL-фильтры</strong></h2>
      </div>
    </div>

    <SettingsCollapsible class="mt-3">
      <template #label>
        Исключения разделов
        <UBadge color="neutral" variant="subtle">{{ project.exclusions.length }}</UBadge>
      </template>
      <PatternEditor
        :model-value="project.exclusions"
        placeholder="/catalog/rasprodazha/"
        :disabled="disabled"
        @add="project.exclusions.push($event)"
        @remove="project.exclusions.splice($event, 1)"
      />
    </SettingsCollapsible>

    <SettingsCollapsible>
      <template #label>
        Фильтр товарных URL
        <UBadge color="neutral" variant="subtle">{{ project.product_url_filters.length }}</UBadge>
      </template>
      <PatternEditor
        :model-value="project.product_url_filters"
        placeholder="-qyron-"
        :disabled="disabled"
        @add="project.product_url_filters.push($event)"
        @remove="project.product_url_filters.splice($event, 1)"
      />
    </SettingsCollapsible>

    <SettingsCollapsible>
      <template #label>
        Исключения товарных ссылок
        <UBadge color="neutral" variant="subtle">{{ project.product_url_exclusions.length }}</UBadge>
      </template>
      <PatternEditor
        :model-value="project.product_url_exclusions"
        placeholder="/recommend"
        :disabled="disabled"
        @add="project.product_url_exclusions.push($event)"
        @remove="project.product_url_exclusions.splice($event, 1)"
      />
    </SettingsCollapsible>
  </UCard>
</template>
