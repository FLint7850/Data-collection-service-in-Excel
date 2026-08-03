<script setup lang="ts">
import type { FileImportSettings } from "~/types/api";

defineProps<{ disabled?: boolean }>();
const form = defineModel<FileImportSettings>({ required: true });
</script>

<template>
  <UCard as="section" variant="outline" class="panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ШАГ 1</p>
        <h2><strong>Поля и правила</strong></h2>
      </div>
      <UBadge color="neutral" variant="subtle">Настройки</UBadge>
    </div>

    <div class="form-grid import-form-grid">
      <UFormField label="Столбец с моделью">
        <UInput v-model="form.model_field" :disabled="disabled" placeholder="name" class="w-full" />
      </UFormField>
      <UFormField label="Столбец с ценой">
        <UInput v-model="form.price_field" :disabled="disabled" placeholder="price" class="w-full" />
      </UFormField>
    </div>

    <SettingsCollapsible>
      <template #label>
        Исключения
        <span class="summary-hint">по одному значению на строку</span>
      </template>
      <UTextarea
        v-model="form.exclusions"
        :disabled="disabled"
        :rows="7"
        class="w-full"
        placeholder="Автомобильный холодильник&#10;Гриль из чугуна"
      />
    </SettingsCollapsible>

    <SettingsCollapsible>
      <template #label>
        Правила поиск/замены
        <span class="summary-hint">подготовка модели</span>
      </template>
      <UTextarea
        v-model="form.replace_rules"
        :disabled="disabled"
        :rows="7"
        class="w-full code-input"
        placeholder="{reg[#[^A-Za-z0-9./\-\s]#]}|"
      />
    </SettingsCollapsible>
  </UCard>
</template>
