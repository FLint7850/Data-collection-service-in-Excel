<script setup lang="ts">
import type { NewsBrandSearchResult } from "~/types/api";

const props = defineProps<{
  brands: NewsBrandSearchResult[];
}>();

const emit = defineEmits<{
  select: [brand: NewsBrandSearchResult];
  create: [];
}>();

const selected = ref<NewsBrandSearchResult>();
const searchTerm = ref("");
const results = computed(() => {
  const query = searchTerm.value.trim().toLocaleLowerCase("ru");
  if (query.length < 2) return [];
  return props.brands
    .filter((brand) => brand.name.toLocaleLowerCase("ru").includes(query))
    .slice(0, 20);
});

function selectBrand(brand: NewsBrandSearchResult | undefined) {
  if (!brand) return;
  emit("select", brand);
  selected.value = undefined;
  searchTerm.value = "";
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <UInputMenu
      v-model="selected"
      v-model:search-term="searchTerm"
      :items="results"
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
        <span v-else>Совпадений не найдено</span>
      </template>
    </UInputMenu>
    <UButton color="primary" icon="i-lucide-plus" @click="emit('create')">
      Добавить бренд
    </UButton>
  </div>
</template>
