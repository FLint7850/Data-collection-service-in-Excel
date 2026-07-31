<script setup lang="ts">
import type { NewsBrandSearchResult } from "~/types/api";

const emit = defineEmits<{
  select: [brand: NewsBrandSearchResult];
  create: [];
}>();

const selected = ref<NewsBrandSearchResult>();
const {
  searchTerm,
  results,
  loading,
  error,
} = useNewsBrandSearch();

function selectBrand(brand: NewsBrandSearchResult | undefined) {
  if (!brand) return;
  emit("select", brand);
  selected.value = undefined;
  searchTerm.value = "";
  results.value = [];
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <UInputMenu
      v-model="selected"
      v-model:search-term="searchTerm"
      :items="results"
      :loading="loading"
      label-key="name"
      by="id"
      ignore-filter
      icon="i-lucide-search"
      placeholder="Найти бренд…"
      class="w-72 max-w-full"
      :ui="{ item: 'cursor-pointer' }"
      @update:model-value="selectBrand"
    >
      <template #empty>
        <span v-if="searchTerm.trim().length < 2">
          Введите минимум 2 символа
        </span>
        <span v-else-if="loading">Ищем бренды…</span>
        <span v-else-if="error">{{ error }}</span>
        <span v-else>Совпадений не найдено</span>
      </template>
    </UInputMenu>
    <UButton color="primary" icon="i-lucide-plus" @click="emit('create')">
      Добавить бренд
    </UButton>
  </div>
</template>
