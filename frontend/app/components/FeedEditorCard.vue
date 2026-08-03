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
const summary = computed(() =>
  "id" in props.item && props.item.id ? props.item : draft.value,
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
    <UCollapsible v-model:open="open">
      <template #default="{ open: isOpen }">
        <UButton
          type="button"
          color="neutral"
          variant="ghost"
          block
          class="feed-card-summary"
        >
          <span class="feed-card-icon" :class="isSupplier ? 'blue-icon' : 'mint-icon'">
            <UIcon :name="isSupplier ? 'i-lucide-truck' : 'i-lucide-store'" />
          </span>
          <span>
            <strong>{{ summary.name || (isSupplier ? "Новый поставщик" : "Новый фид") }}</strong>
            <small>{{ summary.feed_url || "Ссылка не указана" }}</small>
          </span>
          <UIcon
            name="i-lucide-chevron-down"
            class="settings-details-chevron"
            :class="{ open: isOpen }"
          />
        </UButton>
      </template>

      <template #content>
        <div class="feed-card-body">
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
              <div class="supplier-fields-row">
                <UFormField label="Поле модели">
                  <UInput
                    v-model="(draft as SupplierFeed).model_field"
                    :disabled="disabled"
                    placeholder="model или param:Модель"
                    class="w-full"
                  />
                </UFormField>
                <UFormField label="Поле названия">
                  <UInput
                    v-model="(draft as SupplierFeed).name_field"
                    :disabled="disabled"
                    placeholder="name"
                    class="w-full"
                  />
                </UFormField>
                <UFormField label="Поле цены">
                  <UInput
                    v-model="(draft as SupplierFeed).price_field"
                    :disabled="disabled"
                    placeholder="price"
                    class="w-full"
                  />
                </UFormField>
                <UFormField label="Поле бренда">
                  <UInput
                    v-model="(draft as SupplierFeed).brand_field"
                    :disabled="disabled"
                    placeholder="vendor"
                    class="w-full"
                  />
                </UFormField>
                <UFormField label="Поле URL">
                  <UInput
                    v-model="(draft as SupplierFeed).url_field"
                    :disabled="disabled"
                    placeholder="url"
                    class="w-full"
                  />
                </UFormField>
              </div>
              <SettingsCollapsible content-class="form-stack">
                <template #label>Исключения и правила</template>
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
              </SettingsCollapsible>
            </template>
          </div>

          <div class="feed-card-actions">
            <UButton
              color="primary"
              variant="soft"
              icon="i-lucide-save"
              :loading="saving"
              :disabled="disabled || !draft.name.trim() || !draft.feed_url.trim() || (isSupplier && !(draft as SupplierFeed).model_field.trim())"
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
      </template>
    </UCollapsible>
  </UCard>
</template>
