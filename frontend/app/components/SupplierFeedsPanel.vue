<script setup lang="ts">
import type { SupplierFeed } from "~/types/api";

defineProps<{
  suppliers: SupplierFeed[];
  disabled?: boolean;
  savingKey?: string;
}>();

const pending = defineModel<SupplierFeed[]>("pending", { required: true });
const emit = defineEmits<{
  save: [supplier: SupplierFeed, pendingIndex?: number];
  remove: [supplier: SupplierFeed];
}>();
const open = ref(false);

function addSupplier() {
  pending.value.push({
    name: "",
    feed_url: "",
    model_field: "",
    exclusions: "",
    replace_rules: "",
  });
}
</script>

<template>
  <UCard as="section" variant="outline" class="panel feed-column">
    <UCollapsible v-model:open="open">
      <template #default>
        <div class="panel-header">
          <div>
            <p class="eyebrow">ИСТОЧНИКИ</p>
            <h2><strong>Фиды поставщиков</strong></h2>
            <p>Для каждого поставщика укажите точное имя XML-поля с моделью.</p>
          </div>
          <div class="flex flex-col gap-3">
            <UIcon
              name="i-lucide-chevron-down"
              class="settings-details-chevron"
              :class="{ open }"
            />
            <UButton
              color="neutral"
              variant="soft"
              icon="i-lucide-plus"
              :disabled="disabled"
              @click.stop="addSupplier"
            >
              Поставщик
            </UButton>
          </div>
        </div>
      </template>

      <template #content>
        <div class="feed-list">
          <FeedEditorCard
            v-for="supplier in suppliers"
            :key="`supplier-${supplier.id}`"
            kind="supplier"
            :item="supplier"
            :disabled="disabled"
            :saving="savingKey === `supplier-${supplier.id}`"
            @save="emit('save', $event as SupplierFeed)"
            @remove="emit('remove', $event as SupplierFeed)"
          />
          <FeedEditorCard
            v-for="(supplier, index) in pending"
            :key="`new-supplier-${index}`"
            kind="supplier"
            :item="supplier"
            :disabled="disabled"
            :saving="savingKey === `supplier-${index}`"
            @save="emit('save', $event as SupplierFeed, index)"
            @remove="pending.splice(index, 1)"
          />
        </div>
      </template>
    </UCollapsible>

    <EmptyState
      v-if="!suppliers.length && !pending.length"
      icon="i-lucide-truck"
      title="Нет поставщиков"
      description="Добавьте XML-фид поставщика для сравнения."
    >
      <UButton color="primary" variant="soft" icon="i-lucide-plus" @click="addSupplier">
        Добавить
      </UButton>
    </EmptyState>
  </UCard>
</template>
