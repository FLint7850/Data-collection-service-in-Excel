<script setup lang="ts">
defineProps<{
  creating: boolean;
}>();

const emit = defineEmits<{
  create: [];
  remove: [];
}>();

const createOpen = defineModel<boolean>("createOpen", { required: true });
const deleteOpen = defineModel<boolean>("deleteOpen", { required: true });
const createGroup = defineModel<string>("createGroup", { required: true });
const createBrand = defineModel<string>("createBrand", { required: true });
</script>

<template>
  <UModal
    v-model:open="createOpen"
    title="Новый бренд"
    description="Создайте мониторинг бренда и затем добавьте сайты-доноры."
    :ui="{ content: 'max-w-md' }"
  >
    <template #body>
      <div class="form-stack">
        <UFormField label="Группа">
          <UInput
            v-model="createGroup"
            placeholder="Например, Маржа"
            class="w-full"
          />
        </UFormField>
        <UFormField label="Название бренда">
          <UInput
            v-model="createBrand"
            autofocus
            placeholder="Например, MAUNFELD"
            class="w-full"
            @keyup.enter="emit('create')"
          />
        </UFormField>
      </div>
    </template>
    <template #footer>
      <UButton color="neutral" variant="soft" @click="createOpen = false">
        Отмена
      </UButton>
      <UButton color="primary" :loading="creating" @click="emit('create')">
        Добавить
      </UButton>
    </template>
  </UModal>

  <UModal
    v-model:open="deleteOpen"
    title="Удалить бренд?"
    description="Будут удалены бренд и все привязанные к нему доноры."
    :ui="{ content: 'max-w-md' }"
  >
    <template #footer>
      <UButton color="neutral" variant="soft" @click="deleteOpen = false">
        Отмена
      </UButton>
      <UButton color="error" @click="emit('remove')">Удалить</UButton>
    </template>
  </UModal>
</template>
