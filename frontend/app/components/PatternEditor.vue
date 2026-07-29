<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: string[];
    placeholder: string;
    addLabel?: string;
    disabled?: boolean;
  }>(),
  { addLabel: "Добавить", disabled: false },
);

const emit = defineEmits<{
  add: [pattern: string];
  remove: [index: number];
}>();

const pattern = ref("");

function add() {
  const value = pattern.value.trim();
  if (!value) return;
  emit("add", value);
  pattern.value = "";
}
</script>

<template>
  <div class="pattern-editor">
    <form class="pattern-form" @submit.prevent="add">
      <UInput
        v-model="pattern"
        :placeholder="placeholder"
        :disabled="disabled"
        class="flex-1"
      />
      <UButton
        type="submit"
        color="neutral"
        variant="soft"
        icon="i-lucide-plus"
        :disabled="disabled || !pattern.trim()"
      >
        {{ addLabel }}
      </UButton>
    </form>
    <div v-if="props.modelValue.length" class="tag-list">
      <UBadge
        v-for="(item, index) in props.modelValue"
        :key="`${item}-${index}`"
        color="neutral"
        variant="subtle"
        size="md"
        class="tag"
      >
        <code>{{ item }}</code>
        <UButton
          :disabled="disabled"
          icon="i-lucide-x"
          color="neutral"
          variant="ghost"
          size="xs"
          :aria-label="`Удалить ${item}`"
          @click="emit('remove', index)"
        />
      </UBadge>
    </div>
    <p v-else class="inline-empty">Список пуст</p>
  </div>
</template>
