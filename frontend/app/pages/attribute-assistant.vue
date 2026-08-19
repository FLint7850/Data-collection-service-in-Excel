<script setup lang="ts">
import { attributeAssistantService } from "~/services/attribute-assistant.service";
import type {
  AttributeAllowedValue,
  AttributeAssistantWorkspace,
  AttributeBatch,
  AttributeBatchReport,
  AttributeBatchSummary,
  AttributeChatGptAnalysis,
  AttributeChatGptStatus,
  AttributeDonor,
  AttributeProduct,
  AttributeParsedPage,
  AttributeProductLog,
  AttributeProductValue,
  AttributeTemplate,
  AttributeTemplateField,
  AttributeTemplateImportReport,
  AttributeTemplateRevision,
} from "~/types/api";
import { errorMessage, formatDateTime } from "~/utils/format";

definePageMeta({
  title: "Помощник атрибутов",
  eyebrow: "OPENCART · OCSTORE",
});

type WorkspaceTab = "dashboard" | "upload" | "templates" | "donors" | "review";
type UploadMode = "csv" | "url";

const toast = useToast();
const workspace = ref<AttributeAssistantWorkspace | null>(null);
const activeTab = ref<WorkspaceTab>("dashboard");
const loading = ref(true);
const action = ref("");
const error = ref("");

const activeTemplate = ref<AttributeTemplate | null>(null);
const templateRevisions = ref<AttributeTemplateRevision[]>([]);
const templatePreview = ref<AttributeTemplateImportReport | null>(null);
const templateFileInput = ref<HTMLInputElement | null>(null);
const templateFile = ref<File | null>(null);
const newAllowedValue = reactive<Record<number, string>>({});
const newSynonym = reactive<Record<number, string>>({});
const dictionarySearch = ref("");
const newField = reactive({
  group_name: "",
  name: "",
  value_type: "select",
  is_required: true,
  is_composite: false,
  separator: "/",
});

const activeBatch = ref<AttributeBatch | null>(null);
const activeProduct = ref<AttributeProduct | null>(null);
const productLogs = ref<AttributeProductLog[]>([]);
const activeReport = ref<AttributeBatchReport | null>(null);
const batchFileInput = ref<HTMLInputElement | null>(null);
const batchFile = ref<File | null>(null);
const uploadMode = ref<UploadMode>("csv");
const productUrls = ref("");
const productSearch = ref("");
const productStatus = ref("all");
const valueSearch = ref("");
const valueStatus = ref("all");
const valueGroup = ref("all");
const valueSource = ref("all");
const valueConfidence = ref("all");
const selectedValueIds = ref<number[]>([]);
const allowedValuesCache = new Map<number, AttributeAllowedValue[]>();
const allowedValuesLoading = reactive<Record<number, boolean>>({});

const donorUrl = ref("");
const productDonorId = ref<number | undefined>();
const donorPriority = ref(0);
const donorTestUrl = ref("");
const donorTestResult = ref<AttributeParsedPage | null>(null);
const donorChatGptResult = ref<AttributeChatGptAnalysis | null>(null);
const donorTestTemplateId = ref<number | undefined>();
const mappingFields = ref<AttributeTemplateField[]>([]);
const chatGptStatus = ref<AttributeChatGptStatus | null>(null);

const templateForm = reactive({
  category_name: "",
  category_path: "",
  template_name: "",
  product_type: "",
  external_key: "",
  is_default: false,
  mode: "merge" as "merge" | "replace" | "update_values",
});

const batchForm = reactive({
  template_id: undefined as number | undefined,
  processing_mode: "suggest",
});

const donorForm = reactive({
  name: "",
  domain: "",
  base_url: "",
  is_active: true,
  selectors: {
    name_selector: "",
    model_selector: "",
    breadcrumb_selector: "",
    attribute_row_selector: "",
    attribute_name_selector: "",
    attribute_value_selector: "",
    attribute_group_selector: "",
  },
});

const mappingForm = reactive({
  donor_id: undefined as number | undefined,
  template_id: undefined as number | undefined,
  template_field_id: undefined as number | undefined,
  donor_attribute_name: "",
});

const workspaceTabs = [
  { value: "dashboard", label: "Обзор", icon: "i-lucide-layout-dashboard" },
  { value: "upload", label: "Добавить товары", icon: "i-lucide-file-up" },
  { value: "templates", label: "Шаблоны и справочник", icon: "i-lucide-library" },
  { value: "donors", label: "Источники и ИИ", icon: "i-lucide-sparkles" },
  { value: "review", label: "Проверка и экспорт", icon: "i-lucide-list-checks" },
] as const;

const templateModeItems = [
  { label: "Безопасно дополнить", value: "merge" },
  { label: "Обновить значения существующих", value: "update_values" },
  { label: "Полностью заменить", value: "replace" },
];

const processingModeItems = [
  { label: "Только проверить", value: "check" },
  { label: "Предложить заполнение", value: "suggest" },
  { label: "Автопринять только ≥95%", value: "auto_high" },
  { label: "Заполнить всё уверенное", value: "auto_all" },
];

const productStatusItems = [
  { label: "Все товары", value: "all" },
  { label: "Требуют проверки", value: "needs_review" },
  { label: "Готовы", value: "ready" },
];

const valueStatusItems = [
  { label: "Все статусы", value: "all" },
  { label: "Конфликты", value: "conflict" },
  { label: "Предложения", value: "proposed" },
  { label: "Значение —", value: "dash" },
  { label: "Вне шаблона", value: "extra" },
  { label: "Заполнено", value: "filled" },
];

const valueTypeItems = [
  { label: "Список", value: "select" },
  { label: "Текст", value: "text" },
  { label: "Число", value: "number" },
  { label: "Да/нет", value: "boolean" },
  { label: "Составное", value: "composite" },
  { label: "Габариты", value: "dimensions" },
];

const templateItems = computed(() =>
  (workspace.value?.templates || []).map((template) => ({
    label: `${template.category.name} · ${template.name}`,
    value: template.id,
  })),
);

const uploadTemplateItems = computed(() =>
  uploadMode.value === "url"
    ? [{ label: "Определить автоматически по категории страницы", value: 0 }, ...templateItems.value]
    : templateItems.value,
);

const donorItems = computed(() =>
  (workspace.value?.donors || []).map((donor) => ({ label: donor.name, value: donor.id })),
);

const mappingFieldItems = computed(() =>
  mappingFields.value.map((field) => ({
    label: `${field.group_name} · ${field.name}`,
    value: field.id,
  })),
);

const filteredProducts = computed(() => {
  const search = productSearch.value.trim().toLocaleLowerCase("ru");
  return (activeBatch.value?.products || []).filter((product) => {
    if (productStatus.value !== "all" && product.status !== productStatus.value) return false;
    return !search || `${product.model} ${product.name}`.toLocaleLowerCase("ru").includes(search);
  });
});

const groupItems = computed(() => [
  { label: "Все группы", value: "all" },
  ...Array.from(new Set((activeProduct.value?.values || []).map((value) => value.group_name)))
    .sort((a, b) => a.localeCompare(b, "ru"))
    .map((group) => ({ label: group, value: group })),
]);

const valueSourceItems = computed(() => [
  { label: "Все источники", value: "all" },
  ...Array.from(new Set((activeProduct.value?.values || []).map((value) => value.source || "not_found")))
    .sort((a, b) => a.localeCompare(b, "ru"))
    .map((source) => ({ label: sourceLabel(source), value: source })),
]);

const groupedValues = computed(() => {
  const groups = new Map<string, AttributeProductValue[]>();
  const search = valueSearch.value.trim().toLocaleLowerCase("ru");
  for (const value of activeProduct.value?.values || []) {
    const displayStatus = value.is_extra_attribute ? "extra" : value.status;
    if (valueStatus.value !== "all" && displayStatus !== valueStatus.value) continue;
    if (valueGroup.value !== "all" && value.group_name !== valueGroup.value) continue;
    if (valueSource.value !== "all" && (value.source || "not_found") !== valueSource.value) continue;
    if (valueConfidence.value === "high" && value.confidence < 95) continue;
    if (valueConfidence.value === "low" && value.confidence >= 95) continue;
    if (
      search &&
      !`${value.group_name} ${value.attribute_name} ${value.current_value} ${value.proposed_value} ${value.final_value}`
        .toLocaleLowerCase("ru")
        .includes(search)
    ) continue;
    const values = groups.get(value.group_name) || [];
    values.push(value);
    groups.set(value.group_name, values);
  }
  return Array.from(groups.entries()).map(([name, values]) => ({ name, values }));
});

function statusLabel(status: string) {
  return ({
    filled: "Заполнено",
    accepted: "Подтверждено",
    proposed: "Предложено",
    conflict: "Конфликт",
    dash: "Будет —",
    missing: "Не найдено",
    needs_review: "Проверить",
    ready: "Готово",
    extra: "Вне шаблона",
    exported: "Экспортирован",
  } as Record<string, string>)[status] || status;
}

function statusColor(value: AttributeProductValue) {
  if (value.is_extra_attribute) return "neutral";
  if (["filled", "accepted"].includes(value.status)) return "success";
  if (value.status === "conflict") return "error";
  if (value.status === "proposed") return "info";
  return "warning";
}

function sourceLabel(source: string) {
  return ({
    current: "Текущее значение",
    manual: "Пользователь",
    primary_donor: "Основной донор",
    additional_donor: "Дополнительный донор",
    donors: "Несколько доноров",
    similar_products: "Похожие товары",
    chatgpt: "ChatGPT Plus",
    ai: "ИИ-помощник (старое)",
  } as Record<string, string>)[source] || source || "Источник не найден";
}

function valueSelectItems(value: AttributeProductValue) {
  const options = value.allowed_values.map((item) => ({ label: item.value, value: item.value }));
  if (value.current_value && !options.some((item) => item.value === value.current_value)) {
    options.unshift({ label: `${value.current_value} · текущее`, value: value.current_value });
  }
  if (!options.some((item) => item.value === "-")) {
    options.unshift({ label: "— оставить технический пропуск", value: "-" });
  }
  return options;
}

function filteredDictionaryValues(field: AttributeTemplateField) {
  const search = dictionarySearch.value.trim().toLocaleLowerCase("ru");
  if (!search) return field.allowed_values;
  return field.allowed_values.filter((value) =>
    `${value.value} ${(value.synonyms || []).map((item) => item.synonym).join(" ")}`
      .toLocaleLowerCase("ru")
      .includes(search),
  );
}

function hydrateAllowedValues(product: AttributeProduct) {
  for (const value of product.values) {
    if (!value.template_field_id) continue;
    const cached = allowedValuesCache.get(value.template_field_id);
    if (cached) value.allowed_values = cached;
  }
  return product;
}

async function ensureAllowedValues(value: AttributeProductValue) {
  const fieldId = value.template_field_id;
  if (!fieldId || !value.has_allowed_values || value.allowed_values.length) return;
  const cached = allowedValuesCache.get(fieldId);
  if (cached) {
    value.allowed_values = cached;
    return;
  }
  if (allowedValuesLoading[fieldId]) return;
  allowedValuesLoading[fieldId] = true;
  try {
    const result = await attributeAssistantService.getFieldAllowedValues(fieldId);
    allowedValuesCache.set(fieldId, result.allowed_values);
    value.allowed_values = result.allowed_values;
  } catch (caught) {
    error.value = errorMessage(caught, "Не удалось загрузить значения атрибута");
  } finally {
    allowedValuesLoading[fieldId] = false;
  }
}

function selectCsv(event: Event, target: "template" | "batch") {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  if (file && file.name.split(".").pop()?.toLowerCase() !== "csv") {
    error.value = "Нужен CSV-файл.";
    input.value = "";
    return;
  }
  if (target === "template") templateFile.value = file;
  else batchFile.value = file;
}

function replaceBatchSummary(summary: AttributeBatchSummary) {
  const currentWorkspace = workspace.value;
  if (currentWorkspace) {
    const index = currentWorkspace.batches.findIndex((item) => item.id === summary.id);
    if (index >= 0) currentWorkspace.batches[index] = summary;
  }
  if (activeBatch.value?.id === summary.id) activeBatch.value = { ...activeBatch.value, ...summary };
}

async function loadWorkspace(silent = false) {
  if (!silent) loading.value = true;
  try {
    const next = await attributeAssistantService.getWorkspace();
    workspace.value = next;
    if (
      !(uploadMode.value === "url" && batchForm.template_id === 0) &&
      !next.templates.some((item) => item.id === batchForm.template_id)
    ) {
      batchForm.template_id = next.templates.find((item) => item.is_default)?.id || next.templates[0]?.id;
    }
    if (activeBatch.value && !next.batches.some((item) => item.id === activeBatch.value?.id)) {
      activeBatch.value = null;
      activeProduct.value = null;
      activeReport.value = null;
    }
  } catch (caught) {
    if (!silent) error.value = errorMessage(caught, "Не удалось загрузить помощник атрибутов");
  } finally {
    if (!silent) loading.value = false;
  }
}

async function previewTemplate() {
  if (!templateFile.value || !templateForm.category_name.trim() || !templateForm.template_name.trim()) {
    error.value = "Выберите CSV и заполните категорию и название шаблона.";
    return;
  }
  action.value = "template-preview";
  error.value = "";
  try {
    templatePreview.value = (
      await attributeAssistantService.previewTemplate(templateFile.value, {
        ...templateForm,
        category_path: templateForm.category_path.trim() || templateForm.category_name.trim(),
      })
    ).report;
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function importTemplate() {
  if (!templateFile.value) return;
  if (templateForm.mode === "replace" && !window.confirm("Полностью заменить атрибуты и значения шаблона после показанного отчёта?")) return;
  action.value = "template-import";
  error.value = "";
  try {
    const result = await attributeAssistantService.importTemplate(templateFile.value, {
      ...templateForm,
      category_path: templateForm.category_path.trim() || templateForm.category_name.trim(),
    });
    workspace.value = result.workspace;
    batchForm.template_id = result.template.id;
    templatePreview.value = null;
    templateFile.value = null;
    if (templateFileInput.value) templateFileInput.value.value = "";
    allowedValuesCache.clear();
    toast.add({
      title: result.report.created ? "Шаблон создан" : "Шаблон обновлён",
      description: `${Number(result.report.new_fields) || 0} новых атрибутов · ${Number(result.report.new_values) || 0} новых значений`,
      color: "success",
    });
    await openTemplate(result.template.id);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function createTemplate() {
  action.value = "template-create";
  error.value = "";
  try {
    const result = await attributeAssistantService.createTemplate({
      ...templateForm,
      category_path: templateForm.category_path.trim() || templateForm.category_name.trim(),
    });
    workspace.value = result.workspace;
    toast.add({ title: "Пустой шаблон создан", color: "success" });
    await openTemplate(result.template.id);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function openTemplate(templateId: number) {
  action.value = `template-${templateId}`;
  activeTab.value = "templates";
  try {
    const result = await attributeAssistantService.getTemplate(templateId);
    activeTemplate.value = result.template;
    templateRevisions.value = result.revisions;
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function saveField(fieldId: number, fields: Record<string, unknown>) {
  action.value = `field-${fieldId}`;
  try {
    activeTemplate.value = (await attributeAssistantService.updateField(fieldId, fields)).template;
    allowedValuesCache.clear();
    toast.add({ title: "Атрибут обновлён", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function addTemplateField() {
  if (!activeTemplate.value || !newField.group_name.trim() || !newField.name.trim()) return;
  action.value = "field-add";
  try {
    activeTemplate.value = (
      await attributeAssistantService.createField(activeTemplate.value.id, {
        ...newField,
        group_name: newField.group_name.trim(),
        name: newField.name.trim(),
      })
    ).template;
    newField.group_name = "";
    newField.name = "";
    templateRevisions.value = (await attributeAssistantService.getTemplate(activeTemplate.value.id)).revisions;
    toast.add({ title: "Атрибут добавлен", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function deleteTemplateField(fieldId: number) {
  if (!activeTemplate.value || !window.confirm("Удалить атрибут из шаблона? Текущие данные товаров сохранятся.")) return;
  try {
    activeTemplate.value = (await attributeAssistantService.deleteField(fieldId)).template;
    allowedValuesCache.delete(fieldId);
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function moveTemplateField(index: number, direction: -1 | 1) {
  if (!activeTemplate.value) return;
  const target = index + direction;
  if (target < 0 || target >= activeTemplate.value.fields.length) return;
  const ids = activeTemplate.value.fields.map((field) => field.id);
  [ids[index], ids[target]] = [ids[target]!, ids[index]!];
  try {
    activeTemplate.value = (
      await attributeAssistantService.reorderFields(activeTemplate.value.id, ids)
    ).template;
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function addAllowedValue(fieldId: number) {
  const value = newAllowedValue[fieldId]?.trim();
  if (!value || !activeTemplate.value) return;
  if (!window.confirm(`Добавить новое разрешённое значение «${value}» в справочник?`)) return;
  action.value = `allowed-${fieldId}`;
  try {
    await attributeAssistantService.addAllowedValue(fieldId, { value, is_recommended: true });
    newAllowedValue[fieldId] = "";
    await openTemplate(activeTemplate.value.id);
    allowedValuesCache.delete(fieldId);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function addSynonym(valueId: number) {
  const synonym = newSynonym[valueId]?.trim();
  if (!synonym || !activeTemplate.value) return;
  action.value = `synonym-${valueId}`;
  try {
    await attributeAssistantService.addSynonym(valueId, synonym);
    newSynonym[valueId] = "";
    await openTemplate(activeTemplate.value.id);
    allowedValuesCache.clear();
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function deleteSynonym(synonymId: number) {
  if (!activeTemplate.value) return;
  try {
    await attributeAssistantService.deleteSynonym(synonymId);
    await openTemplate(activeTemplate.value.id);
    allowedValuesCache.clear();
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function updateAllowedFlag(
  value: AttributeAllowedValue,
  key: "is_global" | "is_recommended" | "is_active",
) {
  try {
    await attributeAssistantService.updateAllowedValue(value.id, { [key]: value[key] });
    allowedValuesCache.clear();
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function copyActiveTemplate() {
  if (!activeTemplate.value) return;
  const name = window.prompt("Название копии шаблона", `${activeTemplate.value.name} — копия`);
  if (!name) return;
  try {
    const result = await attributeAssistantService.copyTemplate(activeTemplate.value.id, name);
    workspace.value = result.workspace;
    await openTemplate(result.template.id);
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function restoreTemplate(revision: AttributeTemplateRevision) {
  if (!activeTemplate.value) return;
  if (!window.confirm(`Восстановить шаблон из версии ${revision.version}? Текущее состояние попадёт в историю.`)) return;
  action.value = `restore-${revision.id}`;
  try {
    const result = await attributeAssistantService.restoreTemplate(activeTemplate.value.id, revision.id);
    activeTemplate.value = result.template;
    templateRevisions.value = result.revisions;
    workspace.value = result.workspace;
    allowedValuesCache.clear();
    toast.add({ title: "Версия шаблона восстановлена", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function deleteTemplate(templateId: number) {
  if (!window.confirm("Удалить шаблон? Ранее созданные обработки сохранятся.")) return;
  try {
    const result = await attributeAssistantService.deleteTemplate(templateId);
    workspace.value = result.workspace;
    if (activeTemplate.value?.id === templateId) activeTemplate.value = null;
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function importBatch() {
  if (!batchFile.value || !batchForm.template_id) {
    error.value = "Выберите шаблон и CSV с товарами.";
    return;
  }
  action.value = "batch-import";
  try {
    const result = await attributeAssistantService.importBatch(
      batchFile.value,
      batchForm.template_id,
      batchForm.processing_mode,
    );
    workspace.value = result.workspace;
    batchFile.value = null;
    if (batchFileInput.value) batchFileInput.value.value = "";
    activeTab.value = "review";
    await openBatch(result.batch.id);
    toast.add({ title: "Товары загружены", description: `${result.batch.products_count} товаров`, color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function importUrls() {
  const urls = productUrls.value.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
  if (!urls.length) {
    error.value = "Вставьте одну или несколько ссылок.";
    return;
  }
  action.value = "url-import";
  try {
    const result = await attributeAssistantService.importUrls(urls, batchForm.template_id || 0, batchForm.processing_mode);
    workspace.value = result.workspace;
    productUrls.value = "";
    activeTab.value = "review";
    await openBatch(result.batch.id);
    toast.add({ title: "Страницы обработаны", description: `${result.batch.products_count} товаров`, color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function openBatch(batchId: number) {
  action.value = `batch-${batchId}`;
  activeTab.value = "review";
  try {
    const result = await attributeAssistantService.getBatch(batchId);
    activeBatch.value = result.batch;
    activeReport.value = result.report;
    activeProduct.value = null;
    selectedValueIds.value = [];
    if (result.batch.products[0]) await openProduct(result.batch.products[0].id);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function openProduct(productId: number) {
  action.value = `product-${productId}`;
  try {
    const [productResult, historyResult] = await Promise.all([
      attributeAssistantService.getProduct(productId),
      attributeAssistantService.getProductHistory(productId),
    ]);
    activeProduct.value = hydrateAllowedValues(productResult.product);
    productLogs.value = historyResult.logs as AttributeProductLog[];
    selectedValueIds.value = [];
    donorUrl.value = "";
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function rollbackProductValue(logId: number) {
  if (!activeProduct.value || !window.confirm("Отменить это изменение значения?")) return;
  action.value = `rollback-${logId}`;
  try {
    activeProduct.value = hydrateAllowedValues(
      (await attributeAssistantService.rollbackValue(activeProduct.value.id, logId)).product,
    );
    productLogs.value = (
      await attributeAssistantService.getProductHistory(activeProduct.value.id)
    ).logs as AttributeProductLog[];
    if (activeBatch.value) {
      const refreshed = await attributeAssistantService.getBatch(activeBatch.value.id);
      activeBatch.value = refreshed.batch;
      activeReport.value = refreshed.report;
    }
    toast.add({ title: "Изменение отменено", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function saveValue(value: AttributeProductValue, target = value.final_value) {
  if (!activeProduct.value || value.is_extra_attribute) return;
  action.value = `value-${value.id}`;
  try {
    const result = await attributeAssistantService.updateValue(activeProduct.value.id, value.id, target);
    activeProduct.value = hydrateAllowedValues(result.product);
    replaceBatchSummary(result.batch);
    const product = activeBatch.value?.products.find((item) => item.id === result.product.id);
    if (product) Object.assign(product, result.product);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function runBulk(bulkAction: string) {
  if (!activeBatch.value) return;
  action.value = `bulk-${bulkAction}`;
  try {
    const result = await attributeAssistantService.bulkUpdate(activeBatch.value.id, bulkAction, {
      value_ids: selectedValueIds.value.length ? selectedValueIds.value : undefined,
      threshold: 95,
    });
    replaceBatchSummary(result.batch);
    if (activeProduct.value) await openProduct(activeProduct.value.id);
    activeReport.value = await attributeAssistantService.getReport(activeBatch.value.id);
    toast.add({ title: "Массовое действие выполнено", description: `Изменено: ${result.result.changed}`, color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function parseDonor() {
  if (!activeProduct.value || !donorUrl.value.trim()) return;
  action.value = "donor-parse";
  try {
    activeProduct.value = hydrateAllowedValues((await attributeAssistantService.parseDonor(activeProduct.value.id, {
      url: donorUrl.value.trim(),
      donor_id: productDonorId.value,
      priority: donorPriority.value,
    })).product);
    donorUrl.value = "";
    if (activeBatch.value) activeReport.value = await attributeAssistantService.getReport(activeBatch.value.id);
    toast.add({ title: "Донор обработан", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function loadChatGptStatus(silent = false) {
  try {
    const previous = chatGptStatus.value;
    const next = await attributeAssistantService.getChatGptStatus();
    chatGptStatus.value = next;
    if (previous?.pending && next.authenticated) {
      toast.add({ title: "ChatGPT подключён", description: `Подписка: ${next.plan_type || "активна"}`, color: "success" });
    }
  } catch (caught) {
    if (!silent) error.value = errorMessage(caught, "Не удалось проверить подключение ChatGPT");
  }
}

async function startChatGptLogin() {
  action.value = "chatgpt-login";
  error.value = "";
  try {
    chatGptStatus.value = await attributeAssistantService.startChatGptLogin();
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function logoutChatGpt() {
  action.value = "chatgpt-logout";
  error.value = "";
  try {
    chatGptStatus.value = await attributeAssistantService.logoutChatGpt();
    donorChatGptResult.value = null;
    toast.add({ title: "ChatGPT отключён", color: "neutral" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function copyChatGptCode() {
  const code = chatGptStatus.value?.user_code;
  if (!code) return;
  try {
    await navigator.clipboard.writeText(code);
    toast.add({ title: "Код скопирован", color: "success" });
  } catch {
    error.value = "Не удалось скопировать код автоматически.";
  }
}

async function analyzeProductWithChatGpt() {
  if (!activeProduct.value) return;
  const url = donorUrl.value.trim() || activeProduct.value.source_url;
  if (!url) {
    error.value = "Укажите ссылку на страницу товара.";
    return;
  }
  if (!chatGptStatus.value?.authenticated) {
    error.value = "Сначала подключите аккаунт ChatGPT во вкладке «Доноры».";
    return;
  }
  action.value = "chatgpt-product-analyze";
  error.value = "";
  try {
    const productId = activeProduct.value.id;
    const result = await attributeAssistantService.analyzeProductChatGpt(productId, {
      url,
      donor_id: productDonorId.value,
    });
    if (activeProduct.value?.id === productId) activeProduct.value = hydrateAllowedValues(result.product);
    replaceBatchSummary(result.batch);
    if (activeBatch.value?.id === result.batch.id) {
      activeReport.value = await attributeAssistantService.getReport(result.batch.id);
    }
    toast.add({
      title: "Анализ ChatGPT завершён",
      description: result.changed
        ? `Добавлено предложений: ${result.changed}. Проверьте их перед сохранением.`
        : "Подходящих новых предложений не найдено.",
      color: result.changed ? "success" : "neutral",
    });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function saveDonor() {
  action.value = "donor-save";
  try {
    const result = await attributeAssistantService.createDonor(donorForm as unknown as Partial<AttributeDonor>);
    workspace.value = result.workspace;
    donorForm.name = "";
    donorForm.domain = "";
    donorForm.base_url = "";
    toast.add({ title: "Донор сохранён", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function testDonor() {
  if (!donorTestUrl.value.trim()) return;
  action.value = "donor-test";
  error.value = "";
  donorChatGptResult.value = null;
  try {
    donorTestResult.value = (await attributeAssistantService.testDonor(donorTestUrl.value.trim(), donorForm.selectors)).parsed;
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function analyzeDonorWithChatGpt() {
  if (!donorTestUrl.value.trim()) return;
  if (!chatGptStatus.value?.authenticated) {
    error.value = "Сначала подключите аккаунт ChatGPT.";
    return;
  }
  action.value = "chatgpt-donor-analyze";
  error.value = "";
  donorTestResult.value = null;
  try {
    const result = await attributeAssistantService.analyzeChatGptUrl(
      donorTestUrl.value.trim(),
      donorTestTemplateId.value,
    );
    donorChatGptResult.value = result.analysis;
    toast.add({
      title: "Анализ ChatGPT завершён",
      description: `${result.analysis.observed_attributes.length} характеристик · ${result.analysis.suggestions.length} предложений по шаблону`,
      color: "success",
    });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function deleteDonor(donorId: number) {
  if (!window.confirm("Удалить настройки донора? Сырые результаты обработок сохранятся.")) return;
  try {
    workspace.value = (await attributeAssistantService.deleteDonor(donorId)).workspace;
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function loadMappingTemplate(templateId: number | undefined) {
  mappingFields.value = [];
  mappingForm.template_field_id = undefined;
  if (!templateId) return;
  try {
    mappingFields.value = (await attributeAssistantService.getTemplate(templateId)).template.fields;
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function saveMappingRule() {
  if (
    !mappingForm.donor_id ||
    !mappingForm.template_id ||
    !mappingForm.template_field_id ||
    !mappingForm.donor_attribute_name.trim()
  ) {
    error.value = "Заполните донора, шаблон, атрибут и название на сайте донора.";
    return;
  }
  action.value = "mapping-save";
  try {
    await attributeAssistantService.saveMappingRule({
      donor_id: mappingForm.donor_id,
      template_id: mappingForm.template_id,
      template_field_id: mappingForm.template_field_id,
      donor_attribute_name: mappingForm.donor_attribute_name.trim(),
    });
    mappingForm.donor_attribute_name = "";
    await loadWorkspace(true);
    toast.add({ title: "Правило сопоставления сохранено", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function exportBatch(onlyReady = false) {
  if (!activeBatch.value) return;
  const warning = activeReport.value?.export_warning || "Будет сформирован CSV с полным стеком атрибутов.";
  if (!window.confirm(`${warning}\n\nПродолжить?`)) return;
  action.value = "export";
  try {
    const result = await attributeAssistantService.exportBatch(activeBatch.value.id, onlyReady);
    replaceBatchSummary(result.batch);
    window.location.assign(result.download_url);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function exportReport() {
  if (!activeBatch.value) return;
  action.value = "report";
  try {
    const result = await attributeAssistantService.exportReport(activeBatch.value.id);
    window.location.assign(result.download_url);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    action.value = "";
  }
}

async function deleteBatch(batchId: number) {
  if (!window.confirm("Удалить обработку, исходный файл, отчёт и экспорт?")) return;
  try {
    workspace.value = (await attributeAssistantService.deleteBatch(batchId)).workspace;
    if (activeBatch.value?.id === batchId) {
      activeBatch.value = null;
      activeProduct.value = null;
      activeReport.value = null;
    }
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

function toggleValueSelection(valueId: number, checked: boolean) {
  if (checked && !selectedValueIds.value.includes(valueId)) selectedValueIds.value.push(valueId);
  if (!checked) selectedValueIds.value = selectedValueIds.value.filter((id) => id !== valueId);
}

useProgressPolling(() => loadWorkspace(Boolean(workspace.value)), ref(true), 5000);
const chatGptLoginPending = computed(() => Boolean(chatGptStatus.value?.pending));
useProgressPolling(() => loadChatGptStatus(true), chatGptLoginPending, 2000);
onMounted(() => void loadChatGptStatus(true));
</script>

<template>
  <div class="attribute-assistant-page">
    <SectionHeader
      eyebrow="ПОМОЩНИК АТРИБУТОВ"
      title="Подготовка атрибутов OpenCart"
      description="Безопасно дополняет полный стек атрибутов, сохраняет текущие данные и формирует CP1251 CSV для CSV Price Pro."
    />

    <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-triangle-alert" :description="error" close class="page-error" @update:open="error = ''" />

    <div v-if="loading" class="loading-state">
      <span class="loading-logo"><UIcon name="i-lucide-list-checks" /></span>
      <p>Загружаем рабочее пространство…</p>
    </div>

    <template v-else-if="workspace">
      <nav class="attribute-tabs" aria-label="Разделы помощника">
        <button v-for="tab in workspaceTabs" :key="tab.value" type="button" :class="{ active: activeTab === tab.value }" @click="activeTab = tab.value">
          <UIcon :name="tab.icon" />
          <span>{{ tab.label }}</span>
          <UBadge v-if="tab.value === 'review' && workspace.metrics.needs_review" color="warning" variant="subtle">{{ workspace.metrics.needs_review }}</UBadge>
        </button>
      </nav>

      <section v-if="activeTab === 'dashboard'" class="attribute-section-stack">
        <div class="metrics-grid metrics-grid--six">
          <MetricCard label="Товаров" :value="workspace.metrics.products" icon="i-lucide-package-search" tone="purple" />
          <MetricCard label="Заполнено" :value="workspace.metrics.filled" icon="i-lucide-badge-check" tone="mint" />
          <MetricCard label="На проверке" :value="workspace.metrics.needs_review" icon="i-lucide-circle-alert" tone="amber" />
          <MetricCard label="Конфликтов" :value="workspace.metrics.conflicts" icon="i-lucide-git-compare-arrows" tone="red" />
          <MetricCard label="Готовы к экспорту" :value="workspace.metrics.ready_products" icon="i-lucide-file-check-2" tone="blue" />
          <MetricCard label="Шаблонов" :value="workspace.metrics.templates" icon="i-lucide-library" tone="mint" />
        </div>

        <div class="attribute-dashboard-grid">
          <UCard variant="outline" class="panel">
            <div class="panel-header"><div><p class="eyebrow">БЫСТРЫЙ СТАРТ</p><h2>Что нужно сделать</h2></div></div>
            <div class="attribute-quick-actions">
              <UButton icon="i-lucide-file-up" @click="activeTab = 'upload'">Загрузить товары</UButton>
              <UButton color="neutral" variant="outline" icon="i-lucide-library" @click="activeTab = 'templates'">Открыть шаблоны</UButton>
              <UButton color="neutral" variant="outline" icon="i-lucide-globe-2" @click="activeTab = 'donors'">Настроить доноров</UButton>
              <UButton color="neutral" variant="outline" icon="i-lucide-list-checks" @click="activeTab = 'review'">Перейти к проверке</UButton>
              <UButton v-if="workspace.batches[0]" color="neutral" variant="outline" icon="i-lucide-download" @click="openBatch(workspace.batches[0].id)">Открыть последний экспорт</UButton>
            </div>
          </UCard>
          <UCard variant="outline" class="panel">
            <div class="panel-header"><div><p class="eyebrow">ПОСЛЕДНИЕ ОБРАБОТКИ</p><h2>Недавние файлы и ссылки</h2></div></div>
            <div v-if="workspace.batches.length" class="attribute-compact-list">
              <button v-for="batch in workspace.batches.slice(0, 6)" :key="batch.id" type="button" @click="openBatch(batch.id)">
                <span><strong>{{ batch.source_filename }}</strong><small>{{ batch.products_count }} товаров · {{ batch.summary.needs_review || 0 }} проверить</small></span>
                <UBadge :color="batch.summary.conflicts ? 'error' : batch.summary.needs_review ? 'warning' : 'success'" variant="subtle">{{ batch.summary.conflicts || batch.summary.needs_review || 'Готово' }}</UBadge>
              </button>
            </div>
            <div v-else class="attribute-empty-inline">Обработок пока нет.</div>
          </UCard>
        </div>
      </section>

      <section v-else-if="activeTab === 'upload'" class="attribute-section-stack">
        <UCard variant="outline" class="panel attribute-upload-card">
          <div class="panel-header">
            <div><p class="eyebrow">ДОБАВЛЕНИЕ ТОВАРОВ</p><h2>Массово из CSV или быстро по ссылке</h2></div>
            <div class="attribute-segmented">
              <button type="button" :class="{ active: uploadMode === 'csv' }" @click="uploadMode = 'csv'; if (!batchForm.template_id) batchForm.template_id = workspace.templates[0]?.id">CSV-файл</button>
              <button type="button" :class="{ active: uploadMode === 'url' }" @click="uploadMode = 'url'; batchForm.template_id = 0">Ссылка</button>
            </div>
          </div>

          <div class="attribute-upload-settings">
            <UFormField label="Категория / шаблон">
              <USelect v-model="batchForm.template_id" :items="uploadTemplateItems" placeholder="Выберите шаблон" class="w-full" />
            </UFormField>
            <UFormField label="Режим обработки">
              <USelect v-model="batchForm.processing_mode" :items="processingModeItems" class="w-full" />
            </UFormField>
          </div>

          <template v-if="uploadMode === 'csv'">
            <input ref="batchFileInput" class="sr-only" type="file" accept=".csv,text/csv" @change="selectCsv($event, 'batch')">
            <button class="attribute-dropzone" type="button" @click="batchFileInput?.click()">
              <UIcon name="i-lucide-file-up" />
              <span><strong>{{ batchFile?.name || 'Выберите CSV из CSV Price Pro' }}</strong><small>Обязательные столбцы: _MODEL_ и _ATTRIBUTES_; поддерживается CP1251</small></span>
            </button>
            <UButton icon="i-lucide-scan-text" :loading="action === 'batch-import'" :disabled="!workspace.templates.length" block @click="importBatch">Получить товары и найти недостающие атрибуты</UButton>
          </template>
          <template v-else>
            <UFormField label="Ссылки на товары — по одной на строку">
              <UTextarea v-model="productUrls" :rows="8" placeholder="https://mega-kuhnya.ru/product/tovar-1/&#10;https://mega-kuhnya.ru/product/tovar-2/" class="w-full" />
            </UFormField>
            <UAlert color="neutral" variant="subtle" icon="i-lucide-shield-check" description="Страницы используются только для чтения. Сервис не изменяет сайт и всё равно формирует CSV для ручного импорта." />
            <UButton icon="i-lucide-link" :loading="action === 'url-import'" :disabled="!workspace.templates.length" block @click="importUrls">Получить товары по ссылкам</UButton>
          </template>
        </UCard>
      </section>

      <section v-else-if="activeTab === 'templates'" class="attribute-template-workspace">
        <aside class="attribute-template-sidebar">
          <UCard variant="outline" class="panel">
            <div class="panel-header"><div><p class="eyebrow">ИМПОРТ</p><h2>Шаблон категории</h2></div></div>
            <div class="attribute-form-stack">
              <UFormField label="Категория"><UInput v-model="templateForm.category_name" placeholder="Встраиваемые холодильники" class="w-full" /></UFormField>
              <UFormField label="Полный путь"><UInput v-model="templateForm.category_path" placeholder="Встраиваемая техника → Холодильники" class="w-full" /></UFormField>
              <UFormField label="Название шаблона"><UInput v-model="templateForm.template_name" placeholder="Встраиваемые холодильники" class="w-full" /></UFormField>
              <UFormField label="Тип товаров"><UInput v-model="templateForm.product_type" placeholder="Холодильники" class="w-full" /></UFormField>
              <UFormField label="Ключ категории Attribut&co"><UInput v-model="templateForm.external_key" placeholder="category_233" class="w-full" /></UFormField>
              <UFormField label="Режим обновления"><USelect v-model="templateForm.mode" :items="templateModeItems" class="w-full" /></UFormField>
              <label class="attribute-check"><input v-model="templateForm.is_default" type="checkbox"><span>Использовать по умолчанию для категории</span></label>
              <input ref="templateFileInput" class="sr-only" type="file" accept=".csv,text/csv" @change="selectCsv($event, 'template')">
              <UButton color="neutral" variant="outline" icon="i-lucide-paperclip" @click="templateFileInput?.click()">{{ templateFile?.name || 'Выбрать CSV-справочник' }}</UButton>
              <div class="attribute-inline-actions">
                <UButton color="neutral" variant="outline" :loading="action === 'template-preview'" :disabled="!templateFile" @click="previewTemplate">Проверить отличия</UButton>
                <UButton :loading="action === 'template-import'" :disabled="!templateFile || !templatePreview" @click="importTemplate">Применить</UButton>
              </div>
              <UButton color="neutral" variant="ghost" icon="i-lucide-plus" :loading="action === 'template-create'" @click="createTemplate">Создать пустой шаблон</UButton>
            </div>
          </UCard>

          <UCard v-if="templatePreview" variant="outline" class="panel attribute-diff-card">
            <div class="panel-header"><div><p class="eyebrow">ПРЕДПРОСМОТР</p><h3>Изменения ещё не применены</h3></div></div>
            <div class="attribute-diff-grid">
              <span><strong>{{ templatePreview.new_fields_count || 0 }}</strong> новых атрибутов</span>
              <span><strong>{{ templatePreview.removed_fields_count || 0 }}</strong> отсутствуют в новом CSV</span>
              <span><strong>{{ templatePreview.new_values_count || 0 }}</strong> новых значений</span>
              <span><strong>{{ templatePreview.removed_values_count || 0 }}</strong> отсутствуют в новом CSV</span>
              <span><strong>{{ templatePreview.duplicate_values || 0 }}</strong> дублей</span>
              <span><strong>{{ templatePreview.invalid_values?.length || 0 }}</strong> некорректных значений</span>
              <span><strong>{{ templatePreview.changed_groups_count || 0 }}</strong> изменений групп</span>
              <span><strong>{{ templatePreview.used_attributes?.length || 0 }}</strong> атрибутов уже используются</span>
            </div>
          </UCard>

          <UCard variant="outline" class="panel">
            <div class="panel-header"><div><p class="eyebrow">БИБЛИОТЕКА</p><h2>Все шаблоны</h2></div><UBadge color="primary" variant="subtle">{{ workspace.templates.length }}</UBadge></div>
            <div class="attribute-template-list">
              <button v-for="template in workspace.templates" :key="template.id" type="button" class="attribute-template-item" :class="{ active: activeTemplate?.id === template.id }" @click="openTemplate(template.id)">
                <span class="attribute-template-icon"><UIcon name="i-lucide-table-properties" /></span>
                <span><strong>{{ template.name }}</strong><small>{{ template.category.full_path }}</small><small>{{ template.fields_count }} атрибутов · {{ template.values_count }} значений</small></span>
                <UBadge v-if="template.is_default" color="success" variant="subtle">По умолчанию</UBadge>
              </button>
            </div>
          </UCard>
        </aside>

        <UCard variant="outline" class="panel attribute-template-editor">
          <template v-if="activeTemplate">
            <div class="panel-header">
              <div><p class="eyebrow">РЕДАКТОР · ВЕРСИЯ {{ activeTemplate.version }}</p><h2>{{ activeTemplate.name }}</h2><span>{{ activeTemplate.category.full_path }}</span></div>
              <div class="attribute-inline-actions">
                <UInput v-model="dictionarySearch" icon="i-lucide-search" placeholder="Поиск по справочнику" />
                <UButton color="neutral" variant="outline" icon="i-lucide-copy" @click="copyActiveTemplate">Копировать</UButton>
                <UButton color="neutral" variant="outline" icon="i-lucide-download" :to="`/api/attribute-assistant/templates/${activeTemplate.id}/export`" external>Экспорт</UButton>
                <UButton color="error" variant="ghost" icon="i-lucide-trash-2" @click="deleteTemplate(activeTemplate.id)">Удалить</UButton>
              </div>
            </div>

            <div class="attribute-new-field">
              <UFormField label="Группа"><UInput v-model="newField.group_name" placeholder="Общие параметры" /></UFormField>
              <UFormField label="Название атрибута"><UInput v-model="newField.name" placeholder="Тип установки" /></UFormField>
              <UFormField label="Тип"><USelect v-model="newField.value_type" :items="valueTypeItems" /></UFormField>
              <label class="attribute-check"><input v-model="newField.is_required" type="checkbox"> Обязательный</label>
              <UButton icon="i-lucide-plus" :loading="action === 'field-add'" @click="addTemplateField">Добавить атрибут</UButton>
            </div>

            <div class="attribute-field-editor-list">
              <article v-for="(field, fieldIndex) in activeTemplate.fields" :key="field.id" class="attribute-field-editor">
                <div class="attribute-field-editor-head">
                  <div class="attribute-field-title-inputs">
                    <UInput v-model="field.name" aria-label="Название атрибута" @change="saveField(field.id, { name: field.name })" />
                    <UInput v-model="field.group_name" aria-label="Группа атрибута" size="sm" @change="saveField(field.id, { group_name: field.group_name })" />
                  </div>
                  <div class="attribute-field-options">
                    <UButton size="xs" color="neutral" variant="ghost" icon="i-lucide-arrow-up" :disabled="fieldIndex === 0" @click="moveTemplateField(fieldIndex, -1)" />
                    <UButton size="xs" color="neutral" variant="ghost" icon="i-lucide-arrow-down" :disabled="fieldIndex === activeTemplate.fields.length - 1" @click="moveTemplateField(fieldIndex, 1)" />
                    <USelect v-model="field.value_type" :items="valueTypeItems" @update:model-value="saveField(field.id, { value_type: field.value_type })" />
                    <label><input v-model="field.is_required" type="checkbox" @change="saveField(field.id, { is_required: field.is_required })"> Обязательный</label>
                    <label><input v-model="field.is_composite" type="checkbox" @change="saveField(field.id, { is_composite: field.is_composite })"> Составной</label>
                    <UInput v-if="field.is_composite" v-model="field.separator" aria-label="Разделитель" size="xs" class="attribute-separator-input" @change="saveField(field.id, { separator: field.separator })" />
                    <UButton size="xs" color="error" variant="ghost" icon="i-lucide-trash-2" @click="deleteTemplateField(field.id)" />
                  </div>
                </div>
                <div class="attribute-values-cloud">
                  <div v-for="allowed in filteredDictionaryValues(field)" :key="allowed.id" class="attribute-dictionary-value" :class="{ inactive: !allowed.is_active }">
                    <div><strong>{{ allowed.value }}</strong><small>{{ allowed.is_global ? 'Глобальное' : allowed.is_recommended ? 'Рекомендуется для категории' : 'Категорийное' }}</small></div>
                    <div class="attribute-value-flags">
                      <label><input v-model="allowed.is_active" type="checkbox" @change="updateAllowedFlag(allowed, 'is_active')"> Активное</label>
                      <label><input v-model="allowed.is_global" type="checkbox" @change="updateAllowedFlag(allowed, 'is_global')"> Глобальное</label>
                      <label><input v-model="allowed.is_recommended" type="checkbox" @change="updateAllowedFlag(allowed, 'is_recommended')"> Рекомендуемое</label>
                    </div>
                    <div v-if="allowed.synonyms?.length" class="attribute-synonyms">
                      <span v-for="synonym in allowed.synonyms" :key="synonym.id">{{ synonym.synonym }}<button type="button" aria-label="Удалить синоним" @click="deleteSynonym(synonym.id)">×</button></span>
                    </div>
                    <div class="attribute-add-synonym">
                      <UInput v-model="newSynonym[allowed.id]" placeholder="Новый синоним" size="sm" @keyup.enter="addSynonym(allowed.id)" />
                      <UButton size="sm" color="neutral" variant="ghost" icon="i-lucide-plus" :loading="action === `synonym-${allowed.id}`" @click="addSynonym(allowed.id)" />
                    </div>
                  </div>
                </div>
                <div class="attribute-add-value">
                  <UInput v-model="newAllowedValue[field.id]" placeholder="Добавить разрешённое значение" @keyup.enter="addAllowedValue(field.id)" />
                  <UButton color="neutral" variant="outline" icon="i-lucide-plus" :loading="action === `allowed-${field.id}`" @click="addAllowedValue(field.id)">Добавить</UButton>
                </div>
              </article>
            </div>

            <details class="attribute-history">
              <summary>История шаблона · {{ templateRevisions.length }} записей</summary>
              <div>
                <span v-for="revision in templateRevisions" :key="revision.id">
                  <span>v{{ revision.version }} · {{ revision.action }} · {{ formatDateTime(revision.created_at) }}</span>
                  <UButton size="xs" color="neutral" variant="ghost" icon="i-lucide-history" :loading="action === `restore-${revision.id}`" @click="restoreTemplate(revision)">Восстановить</UButton>
                </span>
              </div>
            </details>
          </template>
          <div v-else class="attribute-review-empty attribute-review-empty--large"><UIcon name="i-lucide-library" /><strong>Выберите шаблон</strong><span>Здесь появятся его атрибуты, значения, синонимы и история.</span></div>
        </UCard>
      </section>

      <section v-else-if="activeTab === 'donors'" class="attribute-donors-grid">
        <UCard variant="outline" class="panel attribute-ai-card">
          <div class="panel-header attribute-ai-header">
            <div><p class="eyebrow">CHATGPT PLUS · CODEX APP SERVER</p><h2>Автоматический помощник по характеристикам</h2></div>
            <div class="attribute-ai-status">
              <UBadge v-if="chatGptStatus?.authenticated" color="success" variant="subtle">Подключено · {{ chatGptStatus.plan_type || 'ChatGPT' }}</UBadge>
              <UBadge v-else-if="chatGptStatus?.pending" color="warning" variant="subtle">Ожидается подтверждение</UBadge>
              <UBadge v-else color="neutral" variant="subtle">Не подключено</UBadge>
              <UAlert v-if="chatGptStatus && !chatGptStatus.available" color="error" variant="subtle" icon="i-lucide-circle-x" title="Codex App Server недоступен" :description="chatGptStatus.error" />
              <div v-else-if="chatGptStatus?.pending" class="attribute-device-login">
                <div><span>Код подтверждения</span><code>{{ chatGptStatus.user_code }}</code></div>
                <div class="attribute-ai-actions">
                  <UButton icon="i-lucide-copy" color="neutral" variant="outline" @click="copyChatGptCode">Скопировать код</UButton>
                  <UButton :to="chatGptStatus.verification_url" target="_blank" icon="i-lucide-external-link">Открыть страницу входа</UButton>
                </div>
                <small>Введите код на странице OpenAI. После подтверждения статус обновится автоматически.</small>
              </div>
              <div v-else class="attribute-ai-actions attribute-ai-connect-actions">
                <template v-if="chatGptStatus?.authenticated">
                  <span>{{ chatGptStatus.email || 'Аккаунт ChatGPT' }}</span>
                  <UButton color="neutral" variant="outline" icon="i-lucide-log-out" :loading="action === 'chatgpt-logout'" @click="logoutChatGpt">Отключить</UButton>
                </template>
                <UButton v-else icon="i-lucide-log-in" :loading="action === 'chatgpt-login'" :disabled="chatGptStatus === null" @click="startChatGptLogin">Подключить ChatGPT</UButton>
              </div>
            </div>
          </div>
        </UCard>

        <UCard variant="outline" class="panel attribute-source-settings-card">
          <div class="panel-header"><div><p class="eyebrow">НОВЫЙ ДОМЕН</p><h2>Настройки донора</h2></div></div>
          <div class="attribute-form-stack">
            <UFormField label="Название"><UInput v-model="donorForm.name" placeholder="AEG Россия" /></UFormField>
            <UFormField label="Домен"><UInput v-model="donorForm.domain" placeholder="aeg-com.ru" /></UFormField>
            <UFormField label="Базовый URL"><UInput v-model="donorForm.base_url" placeholder="https://aeg-com.ru" /></UFormField>
            <details class="attribute-selector-details">
              <summary>CSS-селекторы для нестандартного сайта</summary>
              <UFormField label="Название"><UInput v-model="donorForm.selectors.name_selector" placeholder="h1.product-title" /></UFormField>
              <UFormField label="Модель"><UInput v-model="donorForm.selectors.model_selector" placeholder=".product-model" /></UFormField>
              <UFormField label="Хлебные крошки"><UInput v-model="donorForm.selectors.breadcrumb_selector" placeholder=".breadcrumb a" /></UFormField>
              <UFormField label="Строка характеристики"><UInput v-model="donorForm.selectors.attribute_row_selector" placeholder=".spec-row" /></UFormField>
              <UFormField label="Название внутри строки"><UInput v-model="donorForm.selectors.attribute_name_selector" placeholder=".spec-name" /></UFormField>
              <UFormField label="Значение внутри строки"><UInput v-model="donorForm.selectors.attribute_value_selector" placeholder=".spec-value" /></UFormField>
            </details>
            <UButton icon="i-lucide-save" :loading="action === 'donor-save'" @click="saveDonor">Сохранить донора</UButton>
          </div>
        </UCard>

        <UCard variant="outline" class="panel attribute-analysis-card">
          <div class="panel-header"><div><p class="eyebrow">АНАЛИЗ СТРАНИЦЫ</p><h2>Какие характеристики указаны</h2><span>Выберите один режим: быстрая проверка запускает локальный парсер, ChatGPT самостоятельно открывает URL и анализирует страницу.</span></div></div>
          <div class="attribute-form-stack">
            <div class="attribute-analysis-form">
              <UInput v-model="donorTestUrl" icon="i-lucide-link" placeholder="https://donor.ru/product/model" />
              <USelect v-model="donorTestTemplateId" :items="templateItems" placeholder="Шаблон для предложений · необязательно" />
              <div class="attribute-analysis-actions">
                <UButton color="neutral" variant="outline" icon="i-lucide-flask-conical" :loading="action === 'donor-test'" @click="testDonor">Быстрая проверка</UButton>
                <UButton icon="i-lucide-sparkles" :loading="action === 'chatgpt-donor-analyze'" :disabled="!chatGptStatus?.authenticated" @click="analyzeDonorWithChatGpt">Проанализировать через ChatGPT</UButton>
              </div>
            </div>

            <div v-if="!donorTestResult && !donorChatGptResult" class="attribute-analysis-empty">
              <UIcon name="i-lucide-scan-search" />
              <strong>Результат появится здесь</strong>
              <span>Режимы независимы: быстрая проверка запускает только парсер, анализ ChatGPT — только ChatGPT.</span>
            </div>

            <div v-if="donorTestResult" class="attribute-page-result attribute-analysis-output">
              <div class="attribute-page-identity">
                <UBadge color="neutral" variant="subtle">Обычный парсер</UBadge>
                <strong>{{ donorTestResult.name || 'Название не найдено' }}</strong>
                <span>Модель: {{ donorTestResult.model || '—' }} · Бренд: {{ donorTestResult.brand || '—' }}</span>
                <small>{{ donorTestResult.category || donorTestResult.url }}</small>
              </div>
              <div class="attribute-result-heading"><strong>Найдено парсером</strong><UBadge color="neutral" variant="subtle">{{ donorTestResult.attributes.length }}</UBadge></div>
              <div v-if="donorTestResult.attributes.length" class="attribute-result-attributes">
                <article v-for="(item, index) in donorTestResult.attributes" :key="`${item.name}-${index}`"><span>{{ item.name }}</span><strong>{{ item.value }}</strong></article>
              </div>
              <div v-else class="attribute-empty-inline">Структурированные пары не найдены.</div>
            </div>

            <div v-if="donorChatGptResult" class="attribute-ai-result attribute-analysis-output">
              <div class="attribute-page-identity">
                <UBadge color="primary" variant="subtle">Прямой анализ ChatGPT</UBadge>
                <strong>{{ donorChatGptResult.product.name || 'Название не найдено' }}</strong>
                <span>Модель: {{ donorChatGptResult.product.model || '—' }} · Бренд: {{ donorChatGptResult.product.brand || '—' }}</span>
                <small>{{ donorChatGptResult.product.category || donorTestUrl }}</small>
              </div>
              <div class="attribute-result-heading"><strong>Найденные характеристики</strong><UBadge color="primary" variant="subtle">{{ donorChatGptResult.observed_attributes.length }}</UBadge></div>
              <div v-if="donorChatGptResult.observed_attributes.length" class="attribute-result-attributes">
                <article v-for="(item, index) in donorChatGptResult.observed_attributes" :key="`${item.name}-${index}`"><span>{{ item.name }}</span><strong>{{ item.value }}</strong><small>«{{ item.evidence }}»</small></article>
              </div>
              <div v-else class="attribute-empty-inline">ChatGPT не нашёл явно указанных характеристик на этой странице.</div>
              <div v-if="donorChatGptResult.suggestions.length" class="attribute-ai-suggestions">
                <div class="attribute-result-heading"><strong>Предложения по шаблону</strong><UBadge color="info" variant="subtle">{{ donorChatGptResult.suggestions.length }}</UBadge></div>
                <article v-for="item in donorChatGptResult.suggestions" :key="item.template_field_id">
                  <div><span>{{ item.group_name }}</span><strong>{{ item.attribute_name }}</strong></div>
                  <div><span>Предложение</span><strong>{{ item.proposed_value }}</strong></div>
                  <UBadge color="info" variant="subtle">{{ item.confidence }}%</UBadge>
                  <p>{{ item.explanation }} · «{{ item.evidence }}»</p>
                </article>
              </div>
              <UAlert v-if="donorChatGptResult.warnings.length" color="warning" variant="subtle" icon="i-lucide-triangle-alert" :description="donorChatGptResult.warnings.join(' · ')" />
            </div>
          </div>
        </UCard>

        <UCard variant="outline" class="panel attribute-source-library-card">
          <div class="panel-header"><div><p class="eyebrow">ДОНОРЫ</p><h2>Сохранённые домены</h2></div><UBadge color="primary" variant="subtle">{{ workspace.donors.length }}</UBadge></div>
          <div class="attribute-donor-list">
            <article v-for="donor in workspace.donors" :key="donor.id">
              <span class="attribute-template-icon"><UIcon name="i-lucide-globe-2" /></span>
              <div><strong>{{ donor.name }}</strong><a :href="donor.base_url" target="_blank" rel="noreferrer">{{ donor.domain }}</a><small>{{ Object.keys(donor.selectors || {}).filter((key) => donor.selectors[key]).length }} CSS-селекторов</small></div>
              <UButton color="error" variant="ghost" icon="i-lucide-trash-2" @click="deleteDonor(donor.id)" />
            </article>
            <div v-if="!workspace.donors.length" class="attribute-empty-inline">Доноры пока не настроены. Универсальный парсер всё равно умеет читать таблицы и пары характеристик.</div>
          </div>
        </UCard>

        <UCard variant="outline" class="panel attribute-mapping-card">
          <div class="panel-header"><div><p class="eyebrow">СОПОСТАВЛЕНИЕ</p><h2>Названия атрибутов донора</h2></div></div>
          <div class="attribute-mapping-form">
            <UFormField label="Донор"><USelect v-model="mappingForm.donor_id" :items="donorItems" placeholder="Выберите донора" /></UFormField>
            <UFormField label="Шаблон"><USelect v-model="mappingForm.template_id" :items="templateItems" placeholder="Выберите шаблон" @update:model-value="loadMappingTemplate" /></UFormField>
            <UFormField label="Как называется у донора"><UInput v-model="mappingForm.donor_attribute_name" placeholder="Общий полезный объем" /></UFormField>
            <UFormField label="Атрибут шаблона"><USelect v-model="mappingForm.template_field_id" :items="mappingFieldItems" placeholder="Выберите атрибут" /></UFormField>
            <UButton icon="i-lucide-git-compare-arrows" :loading="action === 'mapping-save'" @click="saveMappingRule">Сохранить правило</UButton>
          </div>
          <div class="attribute-mapping-list">
            <template v-for="donor in workspace.donors" :key="donor.id">
              <span v-for="rule in donor.mapping_rules" :key="rule.id"><strong>{{ donor.name }}</strong> · {{ rule.donor_attribute_name }} → поле #{{ rule.template_field_id }}</span>
            </template>
          </div>
        </UCard>
      </section>

      <section v-else class="attribute-review-workspace">
        <aside class="attribute-review-sidebar">
          <UCard variant="outline" class="panel">
            <div class="panel-header"><div><p class="eyebrow">ОБРАБОТКИ</p><h2>Файлы и ссылки</h2></div><UBadge color="neutral" variant="subtle">{{ workspace.batches.length }}</UBadge></div>
            <div class="attribute-batch-list">
              <button v-for="batch in workspace.batches" :key="batch.id" type="button" class="attribute-batch-item" :class="{ active: activeBatch?.id === batch.id }" @click="openBatch(batch.id)">
                <span class="attribute-batch-status"><UIcon :name="batch.input_mode === 'url' ? 'i-lucide-link' : 'i-lucide-file-check-2'" /></span>
                <span><strong>{{ batch.source_filename }}</strong><small>{{ batch.category_name }} · {{ batch.products_count }} товаров</small><small>{{ batch.summary.needs_review || 0 }} проверить · {{ formatDateTime(batch.created_at) }}</small></span>
                <UBadge :color="batch.summary.conflicts ? 'error' : batch.summary.needs_review ? 'warning' : 'success'" variant="subtle">{{ batch.summary.conflicts || batch.summary.needs_review || '✓' }}</UBadge>
              </button>
            </div>
          </UCard>
        </aside>

        <UCard variant="outline" class="panel attribute-review-panel">
          <template v-if="activeBatch">
            <div class="panel-header attribute-review-header">
              <div><p class="eyebrow">ПРОВЕРКА И ЭКСПОРТ</p><h2>{{ activeBatch.source_filename }}</h2><span>{{ activeBatch.template_name }} · {{ activeBatch.products_count }} товаров</span></div>
              <div class="attribute-inline-actions">
                <UButton color="neutral" variant="outline" icon="i-lucide-file-spreadsheet" :loading="action === 'report'" @click="exportReport">Скачать отчёт</UButton>
                <UButton color="neutral" variant="outline" icon="i-lucide-badge-check" :loading="action === 'export'" @click="exportBatch(true)">Только готовые</UButton>
                <UButton icon="i-lucide-download" :loading="action === 'export'" @click="exportBatch(false)">Весь импорт</UButton>
                <UButton color="error" variant="ghost" icon="i-lucide-trash-2" aria-label="Удалить обработку" @click="deleteBatch(activeBatch.id)" />
              </div>
            </div>

            <div class="attribute-review-metrics">
              <span><strong>{{ activeBatch.summary.filled || 0 }}</strong> заполнено</span>
              <span><strong>{{ activeBatch.summary.proposed || 0 }}</strong> предложено</span>
              <span class="danger"><strong>{{ activeBatch.summary.conflicts || 0 }}</strong> конфликтов</span>
              <span><strong>{{ activeBatch.summary.dash || 0 }}</strong> останется —</span>
              <span><strong>{{ activeBatch.summary.extra || 0 }}</strong> вне шаблона</span>
              <span><strong>{{ activeBatch.summary.ready_products || 0 }}</strong> готово к экспорту</span>
            </div>

            <details v-if="activeBatch.summary.url_errors?.length" class="attribute-review-notice">
              <summary><span><UIcon name="i-lucide-link-2-off" /> Не обработано ссылок</span><UBadge color="warning" variant="subtle">{{ activeBatch.summary.url_errors.length }}</UBadge></summary>
              <div><span v-for="item in activeBatch.summary.url_errors" :key="item.url"><strong>{{ item.url }}</strong><small>{{ item.error }}</small></span></div>
            </details>

            <details class="attribute-bulk-panel">
              <summary><span><UIcon name="i-lucide-list-checks" /> Массовые действия</span><small>{{ selectedValueIds.length ? `Выбрано строк: ${selectedValueIds.length}` : 'по всем подходящим строкам' }}</small></summary>
              <div class="attribute-bulk-actions">
                <UButton size="sm" color="neutral" variant="outline" :loading="action === 'bulk-accept_confident'" @click="runBulk('accept_confident')">Принять ≥95%</UButton>
                <UButton size="sm" color="neutral" variant="outline" @click="runBulk('accept_primary')">Принять основного донора</UButton>
                <UButton size="sm" color="neutral" variant="outline" @click="runBulk('accept_exact')">Принять точные совпадения</UButton>
                <UButton size="sm" color="neutral" variant="outline" @click="runBulk('keep_current')">Оставить текущие</UButton>
                <UButton size="sm" color="neutral" variant="outline" @click="runBulk('dash')">Поставить —</UButton>
                <UButton size="sm" color="neutral" variant="ghost" @click="selectedValueIds = []">Снять выбор</UButton>
              </div>
            </details>

            <div class="attribute-review-grid">
              <aside class="attribute-products">
                <div class="attribute-filter-stack">
                  <UInput v-model="productSearch" icon="i-lucide-search" placeholder="Модель или название" />
                  <USelect v-model="productStatus" :items="productStatusItems" />
                </div>
                <div class="attribute-product-list">
                  <button v-for="product in filteredProducts" :key="product.id" type="button" class="attribute-product-item" :class="{ active: activeProduct?.id === product.id }" @click="openProduct(product.id)">
                    <span><strong>{{ product.model }}</strong><small>{{ product.name || 'Без названия' }}</small></span>
                    <UBadge :color="product.status === 'ready' ? 'success' : 'warning'" variant="subtle">{{ statusLabel(product.status) }}</UBadge>
                  </button>
                </div>
              </aside>

              <div v-if="activeProduct" class="attribute-values">
                <div class="attribute-product-heading">
                  <div class="attribute-product-identity"><span class="eyebrow">ТОВАР</span><h3>{{ activeProduct.model }}</h3><p>{{ activeProduct.name || 'Название не передано' }}</p><small>ID: {{ activeProduct.external_id || '—' }} · {{ activeProduct.category_name || activeBatch.category_name }}</small><a v-if="activeProduct.source_url" :href="activeProduct.source_url" target="_blank" rel="noreferrer">Открыть страницу</a></div>
                  <div class="attribute-value-filters">
                    <UInput v-model="valueSearch" icon="i-lucide-search" placeholder="Найти атрибут" />
                    <USelect v-model="valueStatus" :items="valueStatusItems" />
                    <USelect v-model="valueGroup" :items="groupItems" />
                    <USelect v-model="valueSource" :items="valueSourceItems" />
                    <USelect v-model="valueConfidence" :items="[{ label: 'Любая уверенность', value: 'all' }, { label: 'Только ≥95%', value: 'high' }, { label: 'Ниже 95%', value: 'low' }]" />
                  </div>
                </div>

                <details class="attribute-product-donors">
                  <summary>Получить характеристики со страницы</summary>
                  <div class="attribute-donor-run-form">
                    <UInput v-model="donorUrl" placeholder="https://donor.ru/product/model" />
                    <div class="attribute-donor-run-actions">
                      <UButton color="neutral" variant="outline" icon="i-lucide-scan-search" :loading="action === 'donor-parse'" @click="parseDonor">Обычный парсер</UButton>
                      <UButton icon="i-lucide-sparkles" :loading="action === 'chatgpt-product-analyze'" :disabled="!chatGptStatus?.authenticated" @click="analyzeProductWithChatGpt">Анализ ChatGPT</UButton>
                    </div>
                    <details class="attribute-donor-options">
                      <summary>Настройки обычного парсера</summary>
                      <div>
                        <USelect v-model="productDonorId" :items="donorItems" placeholder="Домен — определить автоматически" />
                        <USelect v-model="donorPriority" :items="[{ label: 'Основной донор', value: 0 }, { label: 'Дополнительный 1', value: 1 }, { label: 'Дополнительный 2', value: 2 }, { label: 'Дополнительный 3', value: 3 }]" />
                      </div>
                    </details>
                  </div>
                  <div v-if="activeProduct.donor_sources.length" class="attribute-source-list"><span v-for="source in activeProduct.donor_sources" :key="source.id"><strong>{{ source.donor_name || 'Универсальный парсер' }}</strong> · {{ source.status }} · {{ source.url }}</span></div>
                </details>

                <details v-if="productLogs.length" class="attribute-product-history">
                  <summary>История изменений · {{ productLogs.length }}</summary>
                  <div>
                    <span v-for="log in productLogs" :key="log.id">
                      <span>{{ formatDateTime(log.created_at) }} · {{ log.action }}</span>
                      <UButton v-if="log.action === 'value_updated' && log.details.before" size="xs" color="neutral" variant="ghost" icon="i-lucide-undo-2" :loading="action === `rollback-${log.id}`" @click="rollbackProductValue(log.id)">Отменить</UButton>
                    </span>
                  </div>
                </details>

                <section v-for="group in groupedValues" :key="group.name" class="attribute-value-group">
                  <h4>{{ group.name }}</h4>
                  <div class="attribute-value-table">
                    <article v-for="value in group.values" :key="value.id" class="attribute-value-row" :class="`status-${value.is_extra_attribute ? 'extra' : value.status}`">
                      <div class="attribute-value-row-head">
                        <label class="attribute-row-check"><input :checked="selectedValueIds.includes(value.id)" :disabled="value.is_extra_attribute" type="checkbox" @change="toggleValueSelection(value.id, ($event.target as HTMLInputElement).checked)"></label>
                        <div class="attribute-value-name"><strong>{{ value.attribute_name }}</strong><small>{{ value.reason }}</small></div>
                        <UBadge :color="statusColor(value)" variant="subtle">{{ value.is_extra_attribute ? 'Вне шаблона' : statusLabel(value.status) }}</UBadge>
                      </div>
                      <div class="attribute-value-comparison">
                        <div class="attribute-current-value"><span>Было</span><strong>{{ value.current_value || '—' }}</strong></div>
                        <div class="attribute-proposed-value">
                          <span>Предложение</span><strong>{{ value.proposed_value || '—' }}</strong><small>{{ sourceLabel(value.source) }}<template v-if="value.confidence"> · {{ value.confidence }}%</template></small>
                          <details v-if="value.source_details.candidates?.length" class="attribute-candidate-details">
                            <summary>Все источники</summary>
                            <span v-for="(candidate, candidateIndex) in value.source_details.candidates" :key="candidateIndex">{{ sourceLabel(candidate.source) }}: {{ candidate.value }} · {{ candidate.confidence }}%</span>
                          </details>
                        </div>
                        <div class="attribute-final-value">
                          <span>Итог</span>
                          <USelectMenu v-if="value.has_allowed_values && !value.is_extra_attribute" v-model="value.final_value" :items="valueSelectItems(value)" value-key="value" :loading="Boolean(value.template_field_id && allowedValuesLoading[value.template_field_id])" virtualize @update:open="(open) => open && ensureAllowedValues(value)" />
                          <UInput v-else v-model="value.final_value" :disabled="value.is_extra_attribute" />
                        </div>
                      </div>
                      <div class="attribute-value-action">
                        <div v-if="!value.is_extra_attribute" class="attribute-row-actions">
                          <UButton v-if="value.proposed_value" size="sm" icon="i-lucide-wand-sparkles" @click="saveValue(value, value.proposed_value)">Принять</UButton>
                          <UButton size="sm" color="neutral" variant="outline" icon="i-lucide-check" :loading="action === `value-${value.id}`" @click="saveValue(value)">Сохранить</UButton>
                        </div>
                      </div>
                    </article>
                  </div>
                </section>
                <div v-if="!groupedValues.length" class="attribute-empty-inline">По фильтрам ничего не найдено.</div>
              </div>
              <div v-else class="attribute-review-empty"><UIcon name="i-lucide-mouse-pointer-click" /><strong>Выберите товар</strong><span>Справа появятся текущие значения, предложения, источники и уверенность.</span></div>
            </div>

          </template>
          <div v-else class="attribute-review-empty attribute-review-empty--large"><UIcon name="i-lucide-layers-3" /><strong>Откройте обработку</strong><span>Выберите файл слева или добавьте товары во вкладке загрузки.</span></div>
        </UCard>
      </section>
    </template>

  </div>
</template>
