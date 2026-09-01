<script setup lang="ts">
interface AppDialogOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  color?: "primary" | "error";
}

interface AppPromptOptions extends AppDialogOptions {
  defaultValue?: string;
  label?: string;
  placeholder?: string;
  multiline?: boolean;
  required?: boolean;
}

const open = ref(false);
const mode = ref<"confirm" | "prompt">("confirm");
const title = ref("");
const description = ref("");
const confirmLabel = ref("Подтвердить");
const cancelLabel = ref("Отмена");
const color = ref<"primary" | "error">("primary");
const inputLabel = ref("");
const inputValue = ref("");
const inputPlaceholder = ref("");
const multiline = ref(false);
const required = ref(false);
let resolver: ((value: boolean | string | null) => void) | null = null;

function prepare(options: AppDialogOptions) {
  if (resolver) resolver(mode.value === "confirm" ? false : null);
  title.value = options.title;
  description.value = options.description || "";
  confirmLabel.value = options.confirmLabel || "Подтвердить";
  cancelLabel.value = options.cancelLabel || "Отмена";
  color.value = options.color || "primary";
  open.value = true;
}

function confirm(options: AppDialogOptions): Promise<boolean> {
  mode.value = "confirm";
  prepare(options);
  return new Promise((resolve) => {
    resolver = (value) => resolve(value === true);
  });
}

function prompt(options: AppPromptOptions): Promise<string | null> {
  mode.value = "prompt";
  inputValue.value = options.defaultValue || "";
  inputLabel.value = options.label || "Значение";
  inputPlaceholder.value = options.placeholder || "";
  multiline.value = Boolean(options.multiline);
  required.value = options.required !== false;
  prepare(options);
  return new Promise((resolve) => {
    resolver = (value) => resolve(typeof value === "string" ? value : null);
  });
}

function settle(value: boolean | string | null) {
  const currentResolver = resolver;
  resolver = null;
  open.value = false;
  currentResolver?.(value);
}

function submit() {
  if (mode.value === "prompt") {
    if (required.value && !inputValue.value.trim()) return;
    settle(inputValue.value);
    return;
  }
  settle(true);
}

function cancel() {
  settle(mode.value === "confirm" ? false : null);
}

function updateOpen(value: boolean) {
  open.value = value;
  if (!value && resolver) cancel();
}

onBeforeUnmount(cancel);
defineExpose({ confirm, prompt });
</script>

<template>
  <UModal
    :open="open"
    :title="title"
    :description="description"
    :dismissible="true"
    @update:open="updateOpen"
  >
    <template v-if="mode === 'prompt'" #body>
      <UFormField :label="inputLabel">
        <UTextarea
          v-if="multiline"
          v-model="inputValue"
          :placeholder="inputPlaceholder"
          :rows="5"
          autofocus
          class="w-full"
        />
        <UInput
          v-else
          v-model="inputValue"
          :placeholder="inputPlaceholder"
          autofocus
          class="w-full"
          @keydown.enter.prevent="submit"
        />
      </UFormField>
    </template>

    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton color="neutral" variant="soft" @click="cancel">
          {{ cancelLabel }}
        </UButton>
        <UButton
          :color="color"
          :disabled="mode === 'prompt' && required && !inputValue.trim()"
          @click="submit"
        >
          {{ confirmLabel }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>