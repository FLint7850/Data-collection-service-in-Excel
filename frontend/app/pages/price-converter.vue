<script setup lang="ts">
import { priceConverterService } from "~/services/price-converter.service";
import type {
  PriceConverterData,
  PriceConverterRuntime,
  PriceConverterSettings,
} from "~/types/api";
import { errorMessage, formatFileSize } from "~/utils/format";

definePageMeta({
  title: "Конвертер прайсов",
  eyebrow: "CSV · XLS · XLSX",
});

const toast = useToast();
const data = ref<PriceConverterData | null>(null);
const loading = ref(true);
const uploading = ref(false);
const saving = ref(false);
const actionLoading = ref("");
const error = ref("");
let lastSavedSettings: PriceConverterSettings | null = null;

const form = reactive<{
  model_field: string;
  price_field: string;
  promo_field: string;
  promo_date: string;
  sheet_number: string;
}>({
  model_field: "",
  price_field: "",
  promo_field: "",
  promo_date: "",
  sheet_number: "",
});

const sheetNumberModel = computed<string>({
  get: () => String(form.sheet_number ?? ""),
  set: (value) => {
    form.sheet_number = String(value ?? "");
  },
});

const isRunning = computed(() => data.value?.state.status === "running");
const hasFile = computed(() => Boolean(data.value?.file));
const conversionBusy = computed(
  () => actionLoading.value === "convert" || isRunning.value,
);
const conversionProgress = computed<number | null>(() => {
  if (conversionBusy.value) return null;
  return data.value?.state.status === "completed" ? 100 : 0;
});
const conversionProgressLabel = computed(() => {
  if (conversionBusy.value) return "В процессе";
  return data.value?.state.status === "completed" ? "100%" : "0%";
});
const promoSettingsComplete = computed(
  () => Boolean(form.promo_field.trim()) === Boolean(form.promo_date),
);
const canConvert = computed(
  () =>
    hasFile.value &&
    Boolean(form.model_field.trim()) &&
    Boolean(form.price_field.trim()) &&
    promoSettingsComplete.value,
);

function normalizedSheetNumber(value: unknown): number | null {
  if (value === null || value === undefined || String(value).trim() === "") {
    return null;
  }
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function settingsFrom(value: PriceConverterSettings): PriceConverterSettings {
  return {
    model_field: value.model_field || "",
    price_field: value.price_field || "",
    promo_field: value.promo_field || "",
    promo_date: value.promo_date || "",
    sheet_number: normalizedSheetNumber(value.sheet_number),
  };
}

function currentSettings(): PriceConverterSettings {
  return {
    model_field: form.model_field,
    price_field: form.price_field,
    promo_field: form.promo_field,
    promo_date: form.promo_date,
    sheet_number: normalizedSheetNumber(form.sheet_number),
  };
}

function setForm(value: PriceConverterSettings) {
  form.model_field = value.model_field;
  form.price_field = value.price_field;
  form.promo_field = value.promo_field;
  form.promo_date = value.promo_date;
  form.sheet_number = value.sheet_number ? String(value.sheet_number) : "";
}

function replaceData(value: PriceConverterData) {
  const settings = settingsFrom(value);
  data.value = value;
  setForm(settings);
  lastSavedSettings = { ...settings };
}

function applySettings(value: PriceConverterSettings) {
  const settings = settingsFrom(value);
  setForm(settings);
  lastSavedSettings = { ...settings };
  if (data.value) {
    Object.assign(data.value, settings);
    if (value.revision) data.value.revision = value.revision;
  }
}

function applyRuntime(value: PriceConverterRuntime) {
  if (!data.value) return;
  data.value = {
    ...data.value,
    revision: value.revision,
    file: value.file,
    result_filename: value.result_filename,
    result_ready: value.result_ready,
    state: value.state,
  };
}

function changedSettings(
  current: PriceConverterSettings,
): Partial<PriceConverterSettings> {
  if (!lastSavedSettings) return current;
  return Object.fromEntries(
    Object.entries(current).filter(
      ([key, value]) =>
        value !== lastSavedSettings?.[key as keyof PriceConverterSettings],
    ),
  ) as Partial<PriceConverterSettings>;
}

async function load() {
  try {
    replaceData(await priceConverterService.get());
  } catch (caught) {
    error.value = errorMessage(caught, "Не удалось загрузить настройки конвертера");
  } finally {
    loading.value = false;
  }
}

async function saveSettings(showToast = true) {
  if (!promoSettingsComplete.value) {
    error.value = "Название столбца промо и дата промо должны быть заполнены вместе или оставлены пустыми.";
    return false;
  }
  const sheetNumberText = String(form.sheet_number ?? "").trim();
  if (sheetNumberText !== "") {
    const number = Number(sheetNumberText);
    if (!Number.isInteger(number) || number < 1) {
      error.value = "Номер листа должен быть целым положительным числом.";
      return false;
    }
  }
  const current = currentSettings();
  const changes = changedSettings(current);
  if (!Object.keys(changes).length) return true;
  saving.value = true;
  error.value = "";
  try {
    applySettings(await priceConverterService.saveSettings(changes));
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
    const value = await priceConverterService.upload(file);
    if (!data.value) replaceData(value);
    else applyRuntime(value);
    toast.add({ title: `Файл «${file.name}» загружен`, color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    uploading.value = false;
  }
}

function handleFileSelection(file: File | null | undefined) {
  if (file) void upload(file);
}

async function removeFile() {
  actionLoading.value = "remove";
  error.value = "";
  try {
    const value = await priceConverterService.remove();
    if (!data.value) replaceData(value);
    else applyRuntime(value);
    toast.add({ title: "Файл откреплён", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

async function convert() {
  if (!(await saveSettings(false))) return;
  actionLoading.value = "convert";
  error.value = "";
  try {
    applyRuntime(await priceConverterService.convert());
    toast.add({ title: "CSV сформирован", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
    void refreshRuntime();
  } finally {
    actionLoading.value = "";
  }
}

const { refresh: refreshRuntime } = useProgressPolling(
  async () => {
    if (!data.value) return;
    applyRuntime(await priceConverterService.getRuntime());
  },
  computed(() => Boolean(data.value)),
);

onMounted(load);
</script>

<template>
  <div>
    <SectionHeader
      eyebrow="КОНВЕРТАЦИЯ ПРАЙСОВ"
      title="Прайс поставщика в CSV"
      description="Выберите столбцы модели и цены. Если настроено промо, сервис дополнительно сформирует данные"
    >
      <template #actions>
        <UButton
          color="primary"
          icon="i-lucide-save"
          :loading="saving"
          :disabled="isRunning"
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
      <span class="loading-logo"><UIcon name="i-lucide-file-output" /></span>
      <p>Загружаем настройки…</p>
    </div>

    <template v-else-if="data">
      <div class="metrics-grid">
        <MetricCard label="Строк в CSV" :value="data.state.rows_written" icon="i-lucide-rows-3" tone="mint" />
        <MetricCard label="Обработано листов" :value="data.state.matched_sheets" icon="i-lucide-files" tone="blue" />
        <MetricCard label="Пропущено листов" :value="data.state.skipped_sheets" icon="i-lucide-file-x-2" tone="amber" />
      </div>

      <div class="file-import-layout">
        <UCard as="section" variant="outline" class="panel">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ШАГ 1</p>
              <h2><strong>Столбцы и листы</strong></h2>
            </div>
            <UBadge color="neutral" variant="subtle">Настройки</UBadge>
          </div>

          <div class="form-grid import-form-grid">
            <UFormField label="Название столбца модели">
              <UInput v-model="form.model_field" :disabled="isRunning" placeholder="Модель" class="w-full" />
            </UFormField>
            <UFormField label="Название столбца цены">
              <UInput v-model="form.price_field" :disabled="isRunning" placeholder="Цена" class="w-full" />
            </UFormField>
            <UFormField label="Название столбца промо">
              <UInput v-model="form.promo_field" :disabled="isRunning" placeholder="Промо цена" class="w-full" />
            </UFormField>
            <UFormField label="Дата промо">
              <UInput
                v-model="form.promo_date"
                :disabled="isRunning"
                type="date"
                class="w-full"
              />
            </UFormField>
            <p class="converter-field-hint">
              Оставьте поля пустыми если нет промо цены
            </p>
            <UFormField label="Номер листа" class="field-span-2">
              <UInput
                v-model="sheetNumberModel"
                :disabled="isRunning"
                type="number"
                min="1"
                step="1"
                placeholder="Все листы"
                class="w-full"
              />
            </UFormField>
            <p class="converter-field-hint">
              Оставьте поле пустым, чтобы собрать данные всех листов.
            </p>
          </div>
        </UCard>

        <UCard as="section" variant="outline" class="panel upload-panel">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ШАГ 2</p>
              <h2><strong>Исходный прайс</strong></h2>
            </div>
            <UBadge :color="hasFile ? 'success' : 'neutral'" variant="subtle">
              {{ hasFile ? "Загружен" : "Не выбран" }}
            </UBadge>
          </div>

          <UFileUpload
            v-if="!data.file"
            class="file-dropzone"
            accept=".csv,.xls,.xlsx"
            :icon="uploading ? 'i-lucide-loader-circle' : 'i-lucide-cloud-upload'"
            :label="uploading ? 'Загружаем файл…' : 'Перетащите файл сюда'"
            description="или нажмите, чтобы выбрать CSV, XLS или XLSX · При загрузке нового файла предыдущий будет удалён"
            :disabled="uploading || isRunning"
            :preview="false"
            reset
            @update:model-value="handleFileSelection"
          />

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
              :disabled="isRunning"
              aria-label="Открепить файл"
              @click="removeFile"
            />
          </UCard>
        </UCard>

        <UCard
          variant="subtle"
          class="import-action-card converter-action-card"
          :ui="{ body: 'h-full flex flex-col' }"
        >
          <div class="progress-value-row">
            <div>
              <span class="eyebrow">ШАГ 3</span>
              <strong>{{ data.state.stage || "Готово к конвертации" }}</strong>
            </div>
            <strong>{{ conversionProgressLabel }}</strong>
          </div>

          <UProgress :model-value="conversionProgress" color="primary" size="sm" />

          <div class="file-progress-stats">
            <span>{{ data.state.rows_written }} строк записано</span>
            <span>
              {{ data.state.matched_sheets }} обработано ·
              {{ data.state.skipped_sheets }} пропущено
            </span>
          </div>

          <UAlert
            v-if="data.state.error"
            color="error"
            variant="subtle"
            icon="i-lucide-triangle-alert"
            :description="data.state.error"
          />

          <div class="run-actions">
            <UButton
              color="primary"
              icon="i-lucide-file-output"
              :loading="actionLoading === 'convert' || isRunning"
              :disabled="!canConvert"
              @click="convert"
            >
              Конвертировать
            </UButton>
            <UButton
              v-if="data.result_ready"
              to="/api/price-converter/download"
              external
              color="primary"
              variant="soft"
              icon="i-lucide-download"
            >
              Скачать CSV
            </UButton>
          </div>
        </UCard>
      </div>
    </template>
  </div>
</template>

<style src="../assets/css/file-import.css"></style>
