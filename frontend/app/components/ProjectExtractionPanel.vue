<script setup lang="ts">
import type { Project } from "~/types/api";

const project = defineModel<Project>({ required: true });
defineProps<{ disabled?: boolean }>();
</script>

<template>
  <UCard as="section" variant="outline" class="panel settings-stack">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ТОЧНАЯ НАСТРОЙКА</p>
        <h2><strong>Селекторы и правила модели</strong></h2>
      </div>
    </div>

    <SettingsCollapsible content-class="form-grid" class="mt-3">
      <template #label>CSS-селекторы карточек</template>
      <UFormField label="Карточка товара">
        <UInput v-model="project.extraction_rules.product_card_selector" placeholder=".product-card" class="w-full" :disabled="disabled" />
      </UFormField>
      <UFormField label="Ссылка товара">
        <UInput v-model="project.extraction_rules.product_url_selector" placeholder="a[href]" class="w-full" :disabled="disabled" />
      </UFormField>
      <UFormField label="Модель">
        <UInput v-model="project.extraction_rules.model_selector" placeholder=".product-title" class="w-full" :disabled="disabled" />
      </UFormField>
      <UFormField label="Цена">
        <UInput v-model="project.extraction_rules.price_selector" placeholder=".price" class="w-full" :disabled="disabled" />
      </UFormField>
    </SettingsCollapsible>

    <SettingsCollapsible content-class="form-grid">
      <template #label>Маркеры и поиск/замена</template>
      <UFormField label="Начальный маркер">
        <UInput v-model="project.extraction_rules.model_start_marker" placeholder="<h1 class=&quot;detail__title&quot;>" class="w-full" :disabled="disabled" />
      </UFormField>
      <UFormField label="Конечный маркер">
        <UInput v-model="project.extraction_rules.model_end_marker" placeholder="</h1>" class="w-full" :disabled="disabled" />
      </UFormField>
      <UFormField label="Правила замены" class="field-span-2">
        <UTextarea
          v-model="project.extraction_rules.model_replace_rules"
          :rows="5"
          class="w-full code-input"
          :disabled="disabled"
          placeholder="{reg[#[^A-Za-z0-9./\-\s]#]}|"
        />
      </UFormField>
    </SettingsCollapsible>
  </UCard>
</template>
