<script setup lang="ts">
import { fileImportService } from "~/services/file-import.service";
import type { FileImportData } from "~/types/api";
import { errorMessage, formatFileSize } from "~/utils/format";

definePageMeta({
  title: "Выгрузка из файла",
  eyebrow: "CSV · XLS · XLSX",
});

const toast = useToast();
const data = ref<FileImportData | null>(null);
const loading = ref(true);
const uploading = ref(false);
const saving = ref(false);
const actionLoading = ref("");
const dragActive = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const error = ref("");
const form = reactive({
  model_field: "",
  price_field: "",
  exclusions: "",
  replace_rules: "",
});

const isActive = computed(() =>
  ["running", "queued", "stopping"].includes(data.value?.state.status || ""),
);
const hasFile = computed(() => Boolean(data.value?.file));

function applyData(value: FileImportData) {
  data.value = value;
  form.model_field = value.model_field || "";
  form.price_field = value.price_field || "";
  form.exclusions = value.exclusions || "";
  form.replace_rules = value.replace_rules || "";
}

async function load() {
  try {
    applyData(await fileImportService.get());
  } catch (caught) {
    error.value = errorMessage(caught, "Не удалось загрузить настройки импорта");
  } finally {
    loading.value = false;
  }
}

async function saveSettings(showToast = true) {
  saving.value = true;
  try {
    applyData(await fileImportService.saveSettings(form));
    if (showToast) toast.add({ title: "Настройки сохранены", color: "success" });
    return true;
  } catch (caught) {
    error.value = errorMessage(caught);
    return false;
  } finally {
    saving.value = false;
  }
}

async function upload(file?: File) {
  if (!file) return;
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (!extension || !["csv", "xls", "xlsx"].includes(extension)) {
    error.value = "Можно загрузить только CSV, XLS или XLSX.";
    return;
  }
  uploading.value = true;
  error.value = "";
  try {
    applyData(await fileImportService.upload(file));
    toast.add({ title: `Файл «${file.name}» загружен`, color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    uploading.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}

function handleFiles(files?: FileList | null) {
  if (!files?.length) return;
  if (files.length > 1) {
    error.value = "Можно выбрать только один файл.";
    return;
  }
  void upload(files[0]);
}

function onDrop(event: DragEvent) {
  dragActive.value = false;
  handleFiles(event.dataTransfer?.files);
}

async function removeFile() {
  actionLoading.value = "remove";
  try {
    applyData(await fileImportService.remove());
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

async function compare() {
  if (!(await saveSettings(false))) return;
  actionLoading.value = "compare";
  try {
    const state = await fileImportService.compare();
    if (data.value) data.value.state = state;
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

async function stop() {
  actionLoading.value = "stop";
  try {
    applyData(await fileImportService.stop());
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

useProgressPolling(
  async () => {
    if (isActive.value) data.value = await fileImportService.get();
  },
  computed(() => isActive.value),
);

onMounted(load);
</script>

<template>
  <div>
    <SectionHeader
      eyebrow="СОПОСТАВЛЕНИЕ МОДЕЛЕЙ"
      title="Выгрузка из CSV или Excel"
      description="Загрузите прайс, задайте столбцы модели и цены — сервис сравнит их с фидами ваших сайтов."
    >
      <template #actions>
        <UButton
          color="neutral"
          variant="soft"
          icon="i-lucide-save"
          :loading="saving"
          :disabled="isActive"
          @click="saveSettings()"
        >
          Сохранить настройки
        </UButton>
      </template>
    </SectionHeader>

    <UAlert
      v-if="error"
      color="error"
      variant="subtle"
      icon="i-lucide-triangle-alert"
      :description="error"
      close
      class="page-error"
      @update:open="error = ''"
    />

    <div v-if="loading" class="loading-state">
      <span class="loading-logo"><UIcon name="i-lucide-file-spreadsheet" /></span>
      <p>Загружаем настройки…</p>
    </div>

    <template v-else-if="data">
      <div class="metrics-grid">
        <MetricCard label="Строк в файле" :value="data.state.total_rows" icon="i-lucide-rows-3" tone="blue" />
        <MetricCard label="Найдено" :value="data.state.found_rows" icon="i-lucide-circle-check" tone="mint" />
        <MetricCard label="Не найдено" :value="data.state.missing_rows" icon="i-lucide-circle-help" tone="amber" />
        <MetricCard label="Исключено" :value="data.state.excluded_rows" icon="i-lucide-filter-x" tone="red" />
      </div>

      <div class="file-import-layout">
        <UCard as="section" variant="outline" class="panel">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ШАГ 1</p>
              <h3>Поля и правила</h3>
            </div>
            <UBadge color="neutral" variant="subtle">Настройки</UBadge>
          </div>

          <div class="form-grid import-form-grid">
            <UFormField label="Столбец с моделью">
              <UInput v-model="form.model_field" :disabled="isActive" placeholder="name" class="w-full" />
            </UFormField>
            <UFormField label="Столбец с ценой">
              <UInput v-model="form.price_field" :disabled="isActive" placeholder="price" class="w-full" />
            </UFormField>
          </div>

          <details class="settings-details">
            <summary>
              Исключения
              <span class="summary-hint">по одному значению на строку</span>
            </summary>
            <div class="settings-details-content">
              <UTextarea
                v-model="form.exclusions"
                :disabled="isActive"
                :rows="7"
                class="w-full"
                placeholder="Автомобильный холодильник&#10;Гриль из чугуна"
              />
            </div>
          </details>

          <details class="settings-details">
            <summary>
              Правила поиск/замены
              <span class="summary-hint">подготовка модели</span>
            </summary>
            <div class="settings-details-content">
              <UTextarea
                v-model="form.replace_rules"
                :disabled="isActive"
                :rows="7"
                class="w-full code-input"
                placeholder="{reg[#[^A-Za-z0-9./\-\s]#]}|"
              />
            </div>
          </details>
        </UCard>

        <UCard as="section" variant="outline" class="panel upload-panel">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ШАГ 2</p>
              <h3>Исходный файл</h3>
            </div>
            <UBadge :color="hasFile ? 'success' : 'neutral'" variant="subtle">
              {{ hasFile ? "Загружен" : "Не выбран" }}
            </UBadge>
          </div>

          <input
            ref="fileInput"
            class="sr-only"
            type="file"
            accept=".csv,.xls,.xlsx"
            @change="handleFiles(($event.target as HTMLInputElement).files)"
          >

          <button
            v-if="!data.file"
            type="button"
            class="file-dropzone"
            :class="{ active: dragActive }"
            :disabled="uploading || isActive"
            @click="fileInput?.click()"
            @dragenter.prevent="dragActive = true"
            @dragover.prevent="dragActive = true"
            @dragleave.prevent="dragActive = false"
            @drop.prevent="onDrop"
          >
            <span class="dropzone-icon">
              <UIcon :name="uploading ? 'i-lucide-loader-circle' : 'i-lucide-cloud-upload'" :class="{ spin: uploading }" />
            </span>
            <strong>{{ uploading ? "Загружаем файл…" : "Перетащите файл сюда" }}</strong>
            <span>или нажмите, чтобы выбрать CSV, XLS или XLSX</span>
            <small>Только один файл</small>
          </button>

          <UCard
            v-else
            variant="subtle"
            class="selected-file-card"
            :ui="{ body: 'selected-file-card-body' }"
          >
            <span class="file-type-icon"><UIcon name="i-lucide-file-spreadsheet" /></span>
            <div>
              <strong>{{ data.file.filename }}</strong>
              <span>{{ formatFileSize(data.file.size) }} · загружен {{ data.file.uploaded_at }}</span>
            </div>
            <UButton
              color="error"
              variant="ghost"
              icon="i-lucide-trash-2"
              :loading="actionLoading === 'remove'"
              :disabled="isActive"
              @click="removeFile"
            />
          </UCard>

          <UCard variant="subtle" class="import-action-card">
            <div class="progress-value-row">
              <div>
                <span class="eyebrow">ШАГ 3</span>
                <strong>{{ data.state.stage || "Готово к сравнению" }}</strong>
              </div>
              <strong>{{ data.state.percent }}%</strong>
            </div>
            <UProgress :model-value="data.state.percent" color="primary" size="sm" />

            <div class="file-progress-stats">
              <span>{{ data.state.processed_rows }} обработано</span>
              <span>{{ data.state.current_row }} / {{ data.state.total_rows }}</span>
            </div>

            <UAlert
              v-if="data.state.error"
              color="error"
              variant="subtle"
              icon="i-lucide-triangle-alert"
              :description="data.state.error"
            />

            <div class="run-actions compact-run-actions">
              <UButton
                v-if="!isActive"
                color="primary"
                icon="i-lucide-git-compare-arrows"
                :loading="actionLoading === 'compare'"
                :disabled="!hasFile"
                @click="compare"
              >
                Сравнить
              </UButton>
              <UButton
                v-else
                color="error"
                variant="soft"
                icon="i-lucide-square"
                :loading="actionLoading === 'stop'"
                @click="stop"
              >
                Остановить
              </UButton>
              <UButton
                v-if="data.result_ready"
                to="/api/file-import/download"
                external
                color="primary"
                variant="soft"
                icon="i-lucide-download"
              >
                Скачать XLSX
              </UButton>
            </div>
          </UCard>
        </UCard>
      </div>
    </template>
  </div>
</template>
