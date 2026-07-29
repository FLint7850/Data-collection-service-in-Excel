<script setup lang="ts">
import type { OwnSite, SupplierFeed } from "~/types/api";

const props = defineProps<{
  kind: "own-site" | "supplier";
  item: OwnSite | SupplierFeed;
  disabled?: boolean;
  saving?: boolean;
}>();

const emit = defineEmits<{
  save: [item: OwnSite | SupplierFeed];
  remove: [item: OwnSite | SupplierFeed];
}>();

function cloneFeed<T extends OwnSite | SupplierFeed>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const open = ref(!("id" in props.item) || !props.item.id);
const draft = ref<OwnSite | SupplierFeed>(cloneFeed(props.item));

watch(
  () => props.item,
  (value) => {
    draft.value = cloneFeed(value);
  },
  { deep: true },
);

const isSupplier = computed(() => props.kind === "supplier");

function submit() {
  emit("save", cloneFeed(draft.value));
}
</script>

<template>
  <UCard
    as="article"
    variant="subtle"
    class="feed-card"
    :class="{ open }"
    :ui="{ body: 'p-0' }"
  >
    <button type="button" class="feed-card-summary" @click="open = !open">
      <span class="feed-card-icon" :class="isSupplier ? 'blue-icon' : 'mint-icon'">
        <UIcon :name="isSupplier ? 'i-lucide-truck' : 'i-lucide-store'" />
      </span>
      <span>
        <strong>{{ draft.name || (isSupplier ? "Новый поставщик" : "Новый фид") }}</strong>
        <small>{{ draft.feed_url || "Ссылка не указана" }}</small>
      </span>
      <UIcon :name="open ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'" />
    </button>

    <div v-if="open" class="feed-card-body">
      <div class="form-stack">
        <UFormField label="Название">
          <UInput v-model="draft.name" :disabled="disabled" class="w-full" />
        </UFormField>
        <UFormField label="URL фида">
          <UInput
            v-model="draft.feed_url"
            :disabled="disabled"
            type="url"
            placeholder="https://example.ru/feed.xml"
            class="w-full"
          />
        </UFormField>
        <UFormField v-if="!isSupplier" label="Ссылка генерации фида">
          <UInput
            v-model="(draft as OwnSite).feed_generate_url"
            :disabled="disabled"
            type="url"
            placeholder="https://example.ru/index.php"
            class="w-full"
          />
        </UFormField>
        <template v-else>
          <UFormField label="Поле модели в XML">
            <UInput
              v-model="(draft as SupplierFeed).model_field"
              :disabled="disabled"
              placeholder="model или param:Модель"
              class="w-full"
            />
          </UFormField>
          <details class="settings-details">
            <summary>Исключения и правила</summary>
            <div class="settings-details-content form-stack">
              <UFormField label="Исключения">
                <UTextarea
                  v-model="(draft as SupplierFeed).exclusions"
                  :disabled="disabled"
                  :rows="4"
                  class="w-full"
                />
              </UFormField>
              <UFormField label="Поиск/замена">
                <UTextarea
                  v-model="(draft as SupplierFeed).replace_rules"
                  :disabled="disabled"
                  :rows="4"
                  class="w-full code-input"
                />
              </UFormField>
            </div>
          </details>
        </template>
      </div>

      <div class="feed-card-actions">
        <UButton
          color="primary"
          variant="soft"
          icon="i-lucide-save"
          :loading="saving"
          :disabled="disabled || !draft.name.trim() || !draft.feed_url.trim()"
          @click="submit"
        >
          Сохранить
        </UButton>
        <UButton
          v-if="'id' in draft && draft.id"
          color="error"
          variant="ghost"
          icon="i-lucide-trash-2"
          :disabled="disabled"
          @click="emit('remove', draft)"
        >
          Удалить
        </UButton>
      </div>
    </div>
  </UCard>
</template>
