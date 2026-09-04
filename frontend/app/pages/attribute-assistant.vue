<script setup lang="ts">
import { attributeAssistantService as api } from "~/services/attribute-assistant.service";
import type {
  AttributeAllowedValue,
  AttributeBatch,
  AttributeBatchOperation,
  AttributeDonor,
  AttributeHistoryItem,
  AttributeMappingRule,
  AttributeValueMappingRule,
  AttributeProcessingMode,
  AttributeProduct,
  AttributeSource,
  AttributeTemplate,
  AttributeTemplatePreview,
  AttributeValue,
  AttributeWorkspace,
  ChatGptLogin,
  ChatGptStatus,
} from "~/types/attribute-assistant";
import { errorMessage } from "~/utils/format";

definePageMeta({
  title: "Атрибуты",
  eyebrow: "Автоматическое заполнение",
});

const toast = useToast();
const route = useRoute();
const router = useRouter();
type MainTab = "start" | "templates" | "review";
type RouteWriteMode = "push" | "replace";

const ALL_FILTER_VALUE = "all";
const PRODUCT_STATUS_VALUES = new Set(["ready", "conflict", "missing", "outside_template", "needs_review"]);
const ATTRIBUTE_STATUS_VALUES = new Set(["outside_template", "conflict", "suggested", "no_suggestion"]);
const ALLOWED_OPTIONS_PAGE_SIZE = 40;

function routeQueryValue(value: unknown): string {
  return Array.isArray(value) ? String(value[0] || "") : String(value || "");
}

function routeSegments(): string[] {
  const raw = route.params.state;
  const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return values.flatMap((value) => String(value).split("/")).filter(Boolean);
}

function positiveRouteId(value: string | undefined): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

const loading = ref(true);
const busy = ref("");
const error = ref("");
const tab = ref<MainTab>("start");
const inputMode = ref<"csv" | "urls">("csv");
const workspace = ref<AttributeWorkspace>({ templates: [], donors: [], batches: [], dashboard: { active_templates: 0, batches: 0, products: 0, ready: 0, conflicts: 0, missing: 0 } });
const selectedTemplateId = ref<number | null>(null);
const selectedBatch = ref<AttributeBatch | null>(null);
const selectedProduct = ref<AttributeProduct | null>(null);
const loadingProductId = ref<number | null>(null);
const selectedDonors = ref<number[]>([]);
const productFile = ref<File | null>(null);
const templateFile = ref<File | null>(null);
const urlsText = ref("");
const processingMode = ref<AttributeProcessingMode>("suggest");
const chatGpt = ref<ChatGptStatus | null>(null);
const deviceLogin = ref<ChatGptLogin | null>(null);
const templateDetails = ref<AttributeTemplate | null>(null);
const templatePreview = ref<AttributeTemplatePreview | null>(null);
const templateUpdateFile = ref<File | null>(null);
const templateUpdateMode = ref<"merge" | "replace">("merge");
const templateRevisions = ref<Array<{ id: number; version: number; action: string; created_at: string }>>([]);
const templateRevisionsLoaded = ref(false);
const templateRevisionsLoading = ref(false);
const mappingRules = ref<AttributeMappingRule[]>([]);
const valueMappingRules = ref<AttributeValueMappingRule[]>([]);
const loadedTemplateFieldIds = ref<Set<number>>(new Set());
const loadingTemplateFieldIds = ref<Set<number>>(new Set());
const templateFieldQueries = ref<Record<number, string>>({});
const templateFieldMatchedCounts = ref<Record<number, number>>({});
const templateFieldSearchTimers = new Map<number, ReturnType<typeof setTimeout>>();
const templateFieldSearchTokens = new Map<number, number>();
const showNewTemplateField = ref(false);
const allowedValueEditor = ref<{
  id: number;
  fieldName: string;
  value: string;
  synonyms: string[];
  synonymDraft: string;
} | null>(null);
const appDialog = ref<{
  confirm: (options: Record<string, unknown>) => Promise<boolean>;
  prompt: (options: Record<string, unknown>) => Promise<string | null>;
} | null>(null);
const templateFieldEditor = ref<{
  id: number;
  name: string;
  synonyms: string[];
  synonymDraft: string;
  group_name: string;
  value_type: string;
  is_composite: boolean;
  conversion_rules: string;
} | null>(null);
const fieldValueEditor = ref<{
  fieldId: number;
  fieldName: string;
  value: string;
  synonym: string;
} | null>(null);
const unknownSelections = ref<Record<string, number>>({});
const donorRecommendations = ref<AttributeDonor[]>([]);
const donorUrlOverrides = ref<Record<string, string>>({});
const historyItems = ref<AttributeHistoryItem[]>([]);
const batchOperation = ref<AttributeBatchOperation | null>(null);

const productQuery = ref(routeQueryValue(route.query.product_query));
const initialProductStatus = routeQueryValue(route.query.product_status);
const initialAttributeStatus = routeQueryValue(route.query.attribute_status);
const productStatusFilter = ref(PRODUCT_STATUS_VALUES.has(initialProductStatus) ? initialProductStatus : ALL_FILTER_VALUE);
const attributeStatusFilter = ref(ATTRIBUTE_STATUS_VALUES.has(initialAttributeStatus) ? initialAttributeStatus : ALL_FILTER_VALUE);
const allowedOptionCache = ref<Record<number, Array<{ id: number; value: string }>>>({});
const allowedSearchQueries = ref<Record<number, string>>({});
const searchingAllowedValueIds = ref<Set<number>>(new Set());
const allowedSearchTimers = new Map<number, ReturnType<typeof setTimeout>>();
const allowedRequestTokens = new Map<number, number>();
const allowedOptionPages = ref<Record<number, {
  query: string;
  total: number;
  matched: number;
  hasMore: boolean;
}>>({});
type AllowedSelectInstance = { viewportRef?: HTMLElement | { value?: HTMLElement | null } | null };
const allowedSelectRefs = new Map<string, AllowedSelectInstance>();
const allowedSelectRefCallbacks = new Map<string, (instance: unknown) => void>();
const allowedScrollBindings = new Map<string, { valueId: number; check: () => void; cleanup: () => void }>();
const templateForm = reactive({
  name: "",
  category: "",
  product_type: "",
  description: "",
});
let authPoll: ReturnType<typeof setInterval> | null = null;
let productRequestToken = 0;
let routeApplyToken = 0;
let routeStateReady = false;
let applyingRouteState = false;
let writtenRoute = "";
let filterRouteTimer: ReturnType<typeof setTimeout> | null = null;
let batchOperationPoll: ReturnType<typeof setTimeout> | null = null;
const newTemplateField = reactive({
  group_name: "Основные характеристики",
  name: "",
  value_type: "select",
  is_required: true,
  is_composite: false,
  separator: "/",
});

const templates = computed(() => workspace.value.templates);
const templateSelectItems = computed(() => [
  { label: "Определить автоматически", value: null as number | null },
  ...templates.value.map((item) => ({
    label: `${item.category} · ${item.name}`,
    value: item.id,
  })),
]);
const productTemplateItems = computed(() => templates.value.map((item) => ({
  label: `${item.category} · ${item.name}`,
  value: item.id,
})));
const processingModeItems: Array<{ label: string; value: AttributeProcessingMode }> = [
  { label: "Только проверить, без предложений в итог", value: "check" },
  { label: "Показать предложения, решение вручную", value: "suggest" },
  { label: "Автопринять только точные 100%", value: "auto_exact" },
  { label: "Автопринять уверенное от главного донора", value: "auto_primary" },
  { label: "Автопринять подтверждённое от 95%", value: "auto_confident" },
  { label: "Автопринять всё найденное в справочнике", value: "auto_all" },
];
const templateUpdateModeItems = [
  { label: "Объединить", value: "merge" },
  { label: "Заменить значения из файла", value: "replace" },
];
const templateFieldTypeItems = [
  { label: "Из справочника", value: "select" },
  { label: "Текст", value: "text" },
  { label: "Число", value: "number" },
  { label: "Габариты", value: "dimensions" },
  { label: "Да / нет", value: "boolean" },
];

function matchesProductStatus(product: AttributeProduct, status: string): boolean {
  if (status === ALL_FILTER_VALUE) return true;
  if (status === "conflict") return product.status === status || product.counts.conflicts > 0;
  if (status === "missing") return product.status === status || product.counts.missing > 0;
  if (status === "outside_template") return product.counts.outside_template > 0;
  return product.status === status;
}

const productStatusItems = computed(() => {
  const products = selectedBatch.value?.products || [];
  const count = (status: string) => products.filter((product) => matchesProductStatus(product, status)).length;
  return [
    { label: `Все товары (${products.length})`, value: ALL_FILTER_VALUE },
    { label: `Готовые (${count("ready")})`, value: "ready" },
    { label: `С конфликтами (${count("conflict")})`, value: "conflict" },
    { label: `С пропусками (${count("missing")})`, value: "missing" },
    { label: `Вне шаблона (${count("outside_template")})`, value: "outside_template" },
    { label: `Нужна проверка (${count("needs_review")})`, value: "needs_review" },
  ];
});
const mainTabItems = computed(() => [
  { label: "Новая обработка", icon: "i-lucide-sparkles", value: "start" },
  { label: "Шаблоны", icon: "i-lucide-layout-template", value: "templates" },
  {
    label: "Проверка",
    icon: "i-lucide-list-checks",
    value: "review",
    disabled: !selectedBatch.value,
    badge: selectedBatch.value?.summary.needs_review || undefined,
  },
]);
const inputModeItems = [
  { label: "CSV-файл", icon: "i-lucide-file-spreadsheet", value: "csv" },
  { label: "Ссылки сайта", icon: "i-lucide-link", value: "urls" },
];
const donors = computed(() => workspace.value.donors);
const displayedDonors = computed(() => donorRecommendations.value.length ? donorRecommendations.value : donors.value);
const selectedTemplate = computed(() =>
  templates.value.find((item) => item.id === selectedTemplateId.value),
);
const selectedDonorRows = computed(() =>
  selectedDonors.value
    .map((id) => displayedDonors.value.find((item) => item.id === id))
    .filter((item): item is AttributeDonor => Boolean(item)),
);
const filteredProducts = computed(() => (selectedBatch.value?.products || []).filter((product) => {
  const query = productQuery.value.trim().toLocaleLowerCase("ru-RU");
  const queryMatches = !query || `${product.model} ${product.name} ${product.brand}`.toLocaleLowerCase("ru-RU").includes(query);
  const statusMatches = matchesProductStatus(product, productStatusFilter.value);
  return queryMatches && statusMatches;
}));

function productListIndicator(product: AttributeProduct): string {
  if (productStatusFilter.value === "outside_template") {
    return `${product.counts.outside_template}`;
  }
  return String(product.counts.conflicts || product.counts.missing || "✓");
}

function hasPendingProposal(value: AttributeValue): boolean {
  const proposal = displayedProposal(value);
  return Boolean(proposal && proposal !== value.final_value);
}

function matchesAttributeStatus(value: AttributeValue, status: string): boolean {
  if (status === ALL_FILTER_VALUE) return true;
  if (status === "outside_template") return !value.is_in_template;
  if (!value.is_in_template) return false;
  if (status === "conflict") return value.status === "conflict";
  if (status === "suggested") {
    return value.status !== "conflict" && hasPendingProposal(value);
  }
  if (status === "no_suggestion") {
    return value.status !== "conflict" && !hasPendingProposal(value);
  }
  return true;
}

const attributeValues = computed(() => selectedProduct.value?.values || []);
const filteredAttributeValues = computed(() =>
  attributeValues.value.filter((value) => matchesAttributeStatus(value, attributeStatusFilter.value)),
);
const batchOperationRunning = computed(() =>
  ["queued", "running"].includes(batchOperation.value?.status || ""),
);
const batchChatGptLoading = computed(() =>
  busy.value === "chatgpt-all"
  || (batchOperationRunning.value && batchOperation.value?.kind === "chatgpt"),
);
const attributeStatusItems = computed(() => {
  const values = attributeValues.value;
  const count = (status: string) => values.filter((value) => matchesAttributeStatus(value, status)).length;
  return [
    { label: `Все атрибуты (${values.length})`, value: ALL_FILTER_VALUE },
    { label: `Вне шаблона (${count("outside_template")})`, value: "outside_template" },
    { label: `Конфликт (${count("conflict")})`, value: "conflict" },
    { label: `Предложения (${count("suggested")})`, value: "suggested" },
    { label: `Нет предложения (${count("no_suggestion")})`, value: "no_suggestion" },
  ];
});

const valuesByGroup = computed(() => {
  const groups = new Map<string, AttributeValue[]>();
  const outsideTemplate: AttributeValue[] = [];
  for (const value of filteredAttributeValues.value) {
    if (!value.is_in_template) {
      outsideTemplate.push(value);
      continue;
    }
    const key = value.group_name || "Без группы";
    groups.set(key, [...(groups.get(key) || []), value]);
  }
  const result: Array<[string, AttributeValue[]]> = [...groups.entries()];
  if (outsideTemplate.length) result.unshift(["Вне шаблона", outsideTemplate]);
  return result;
});
const displayedProductSources = computed(() =>
  (selectedProduct.value?.sources || []).filter((source) => {
    const kind = sourceKind(source);
    return kind === "donor" || kind === "chatgpt";
  }),
);

function assistantRouteLocation() {
  let path = "/attribute-assistant/new";
  const query: Record<string, string> = {};

  if (tab.value === "templates") {
    path = templateDetails.value
      ? `/attribute-assistant/templates/${templateDetails.value.id}`
      : "/attribute-assistant/templates";
  } else if (tab.value === "review" && selectedBatch.value) {
    path = `/attribute-assistant/review/${selectedBatch.value.id}`;
    if (selectedProduct.value) path += `/${selectedProduct.value.id}`;
    if (productQuery.value) query.product_query = productQuery.value;
    if (productStatusFilter.value !== ALL_FILTER_VALUE) query.product_status = productStatusFilter.value;
    if (selectedProduct.value && attributeStatusFilter.value !== ALL_FILTER_VALUE) {
      query.attribute_status = attributeStatusFilter.value;
    }
  }

  return { path, query };
}

async function writeAssistantRoute(mode: RouteWriteMode = "replace") {
  if (!import.meta.client) return;
  const location = assistantRouteLocation();
  const target = router.resolve(location).fullPath;
  if (target === route.fullPath) return;
  writtenRoute = target;
  if (mode === "push") await router.push(location);
  else await router.replace(location);
}

function applyRouteFilters() {
  productQuery.value = routeQueryValue(route.query.product_query);
  const productStatus = routeQueryValue(route.query.product_status);
  const attributeStatus = routeQueryValue(route.query.attribute_status);
  productStatusFilter.value = PRODUCT_STATUS_VALUES.has(productStatus) ? productStatus : ALL_FILTER_VALUE;
  attributeStatusFilter.value = ATTRIBUTE_STATUS_VALUES.has(attributeStatus) ? attributeStatus : ALL_FILTER_VALUE;
}

async function applyAssistantRoute() {
  const token = ++routeApplyToken;
  applyingRouteState = true;
  applyRouteFilters();
  const [section, firstId, secondId] = routeSegments();

  try {
    if (section === "templates") {
      tab.value = "templates";
      const templateId = positiveRouteId(firstId);
      if (templateId && templateDetails.value?.id !== templateId) {
        await openTemplate(templateId, false);
      }
    } else if (section === "review") {
      const batchId = positiveRouteId(firstId);
      const productId = positiveRouteId(secondId);
      if (batchId) {
        const opened = await openBatch(batchId, productId, { syncRoute: false, resetFilters: false });
        if (!opened) {
          selectedBatch.value = null;
          selectedProduct.value = null;
          tab.value = "start";
        }
      } else if (selectedBatch.value) {
        tab.value = "review";
      } else {
        tab.value = "start";
      }
    } else {
      tab.value = "start";
    }
  } finally {
    if (token === routeApplyToken) {
      applyingRouteState = false;
      routeStateReady = true;
    }
  }

  if (token === routeApplyToken) await writeAssistantRoute("replace");
}

async function changeMainTab(value: string | number) {
  const next = String(value) as MainTab;
  if (!new Set<MainTab>(["start", "templates", "review"]).has(next)) return;
  if (next === "review" && !selectedBatch.value) return;
  tab.value = next;
  await writeAssistantRoute("push");
}

async function useTemplateForNewBatch(id: number) {
  selectedTemplateId.value = id;
  tab.value = "start";
  await writeAssistantRoute("push");
}

function notify(title: string) {
  toast.add({ title, color: "success" });
}

async function run<T>(key: string, task: () => Promise<T>): Promise<T | null> {
  busy.value = key;
  error.value = "";
  try {
    return await task();
  } catch (caught) {
    error.value = errorMessage(caught);
    return null;
  } finally {
    busy.value = "";
  }
}

async function confirmAction(options: Record<string, unknown>) {
  return Boolean(await appDialog.value?.confirm(options));
}

async function promptValue(options: Record<string, unknown>) {
  return (await appDialog.value?.prompt(options)) ?? null;
}

async function loadWorkspace() {
  const data = await run("load", () => api.workspace());
  if (data) {
    workspace.value = data;
    selectedTemplateId.value ||= data.templates[0]?.id || null;
  }
}

async function loadChatGpt() {
  chatGpt.value = await api.chatGptStatus();
  if (chatGpt.value.authenticated && authPoll) {
    clearInterval(authPoll);
    authPoll = null;
    deviceLogin.value = null;
  }
}

async function loginChatGpt() {
  const login = await run("chatgpt-login", () => api.chatGptLogin());
  if (!login) return;
  deviceLogin.value = login;
  window.open(login.verification_url, "_blank", "noopener,noreferrer");
  await navigator.clipboard?.writeText(login.user_code).catch(() => undefined);
  authPoll && clearInterval(authPoll);
  authPoll = setInterval(() => void loadChatGpt(), 3000);
}

async function logoutChatGpt() {
  if (await run("chatgpt-logout", () => api.chatGptLogout())) {
    await loadChatGpt();
  }
}

async function previewNewTemplate() {
  if (!templateFile.value) {
    error.value = "Выберите CSV-файл шаблона.";
    return;
  }
  templatePreview.value = await run("template-preview", () => api.previewTemplate(templateFile.value!));
}

async function importTemplate() {
  if (!templateFile.value) {
    error.value = "Выберите CSV-файл шаблона.";
    return;
  }
  if (!templatePreview.value) await previewNewTemplate();
  if (!templatePreview.value?.can_import) {
    error.value = "Предварительная проверка не разрешает импорт.";
    return;
  }
  const result = await run("template-import", () => api.importTemplate(templateFile.value!, templateForm));
  if (!result) return;
  notify("Шаблон импортирован");
  await loadWorkspace();
  selectedTemplateId.value = result.id;
  templateFile.value = null;
  templatePreview.value = null;
  await openTemplate(result.id);
}

async function openTemplate(id: number, syncRoute = true) {
  const requestKey = `template-open-${id}`;
  if (busy.value === requestKey) return;
  selectedTemplateId.value = id;
  const result = await run(requestKey, () => Promise.all([
    api.template(id),
    api.mappingRules(id).catch(() => ({ items: [] })),
    api.valueMappingRules(id).catch(() => ({ items: [] })),
  ]));
  if (!result) return;
  const [details, rules, valueRules] = result;
  templateDetails.value = details;
  loadedTemplateFieldIds.value = new Set();
  templateFieldQueries.value = {};
  templateFieldMatchedCounts.value = {};
  templateFieldSearchTimers.forEach((timer) => clearTimeout(timer));
  templateFieldSearchTimers.clear();
  templateFieldSearchTokens.clear();
  templateRevisions.value = [];
  templateRevisionsLoaded.value = false;
  mappingRules.value = rules.items;
  valueMappingRules.value = valueRules.items;
  if (syncRoute) await writeAssistantRoute("push");
}

async function loadTemplateRevisions() {
  const templateId = templateDetails.value?.id;
  if (!templateId || templateRevisionsLoaded.value || templateRevisionsLoading.value) return;
  templateRevisionsLoading.value = true;
  try {
    const result = await api.templateRevisions(templateId);
    if (templateDetails.value?.id !== templateId) return;
    templateRevisions.value = result.items;
    templateRevisionsLoaded.value = true;
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    templateRevisionsLoading.value = false;
  }
}

function handleTemplateHistoryOpen(open: boolean) {
  if (open) void loadTemplateRevisions();
}

function setTemplateFieldLoading(fieldId: number, loading: boolean) {
  const next = new Set(loadingTemplateFieldIds.value);
  if (loading) next.add(fieldId);
  else next.delete(fieldId);
  loadingTemplateFieldIds.value = next;
}

async function loadTemplateFieldValues(fieldId: number) {
  if (
    loadedTemplateFieldIds.value.has(fieldId)
    || loadingTemplateFieldIds.value.has(fieldId)
  ) return;
  setTemplateFieldLoading(fieldId, true);
  try {
    const result = await api.allowedValues(fieldId, "", true);
    if (templateDetails.value?.fields) {
      templateDetails.value = {
        ...templateDetails.value,
        fields: templateDetails.value.fields.map((field) => field.id === fieldId
          ? { ...field, allowed_values: result.values, allowed_values_count: result.total }
          : field),
      };
    }
    loadedTemplateFieldIds.value = new Set([...loadedTemplateFieldIds.value, fieldId]);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    setTemplateFieldLoading(fieldId, false);
  }
}

function handleTemplateFieldOpen(open: boolean, fieldId: number) {
  if (open) void loadTemplateFieldValues(fieldId);
}

function queueTemplateFieldValueSearch(fieldId: number, event: Event) {
  const query = (event.target as HTMLInputElement).value;
  templateFieldQueries.value = { ...templateFieldQueries.value, [fieldId]: query };
  const previousTimer = templateFieldSearchTimers.get(fieldId);
  if (previousTimer) clearTimeout(previousTimer);
  const token = (templateFieldSearchTokens.get(fieldId) || 0) + 1;
  templateFieldSearchTokens.set(fieldId, token);
  templateFieldSearchTimers.set(fieldId, setTimeout(async () => {
    setTemplateFieldLoading(fieldId, true);
    try {
      const result = await api.allowedValues(fieldId, query, true);
      if (templateFieldSearchTokens.get(fieldId) !== token || !templateDetails.value?.fields) return;
      templateDetails.value = {
        ...templateDetails.value,
        fields: templateDetails.value.fields.map((field) => field.id === fieldId
          ? { ...field, allowed_values: result.values, allowed_values_count: result.total }
          : field),
      };
      templateFieldMatchedCounts.value = { ...templateFieldMatchedCounts.value, [fieldId]: result.matched };
    } catch (caught) {
      if (templateFieldSearchTokens.get(fieldId) === token) error.value = errorMessage(caught);
    } finally {
      if (templateFieldSearchTokens.get(fieldId) === token) setTemplateFieldLoading(fieldId, false);
    }
  }, 250));
}
async function updateTemplateCsv() {
  if (!templateDetails.value || !templateUpdateFile.value) return;
  const preview = await run("template-update-preview", () => api.previewTemplate(templateUpdateFile.value!, templateDetails.value!.id));
  if (!preview) return;
  templatePreview.value = preview;
  if (!preview.can_import || !await confirmAction({
    title: "Обновить шаблон?",
    description: `Будет применено полей: ${preview.fields.length}. Предупреждений: ${preview.warnings.length}.`,
    confirmLabel: "Применить",
  })) return;
  const result = await run("template-update", () => api.updateTemplateCsv(templateDetails.value!.id, templateUpdateFile.value!, templateUpdateMode.value));
  if (!result) return;
  templateDetails.value = result.template;
  templateUpdateFile.value = null;
  await loadWorkspace();
  notify("Шаблон обновлён");
}

async function copyCurrentTemplate() {
  if (!templateDetails.value) return;
  const name = await promptValue({
    title: "Создать копию шаблона",
    label: "Название копии",
    defaultValue: `${templateDetails.value.name} — копия`,
    confirmLabel: "Создать",
  });
  if (!name?.trim()) return;
  const result = await run("template-copy", () => api.copyTemplate(templateDetails.value!.id, name));
  if (result) {
    await loadWorkspace();
    await openTemplate(result.id);
    notify("Копия шаблона создана");
  }
}

async function toggleTemplateActive() {
  if (!templateDetails.value) return;
  const result = await run("template-active", () => api.updateTemplate(templateDetails.value!.id, { is_active: !templateDetails.value!.is_active }));
  if (result) {
    templateDetails.value = result;
    await loadWorkspace();
  }
}


async function removeTemplate(template: AttributeTemplate) {
  const requestKey = `template-remove-${template.id}`;
  if (busy.value === requestKey) return;
  if (!await confirmAction({
    title: `Удалить шаблон «${template.name}»?`,
    description: "Будут удалены атрибуты, значения, синонимы и история шаблона. Используемый шаблон сервер удалить не позволит.",
    confirmLabel: "Удалить шаблон",
    color: "error",
  })) return;
  const result = await run(requestKey, () => api.removeTemplate(template.id));
  if (!result) return;

  if (templateDetails.value?.id === template.id) {
    templateDetails.value = null;
    templateRevisions.value = [];
    mappingRules.value = [];
    valueMappingRules.value = [];
  }
  const remaining = workspace.value.templates.filter((item) => item.id !== template.id);
  if (selectedTemplateId.value === template.id) {
    selectedTemplateId.value = remaining[0]?.id || null;
  }
  await loadWorkspace();
  if (tab.value === "templates") await writeAssistantRoute("replace");
  notify("Шаблон удалён");
}


async function removeMapping(id: number) {
  if (!await confirmAction({
    title: "Удалить сопоставление?",
    description: "Автоматическое сопоставление атрибута донора больше не будет применяться.",
    confirmLabel: "Удалить",
    color: "error",
  })) return;
  if (await run(`mapping-remove-${id}`, () => api.removeMappingRule(id))) {
    mappingRules.value = mappingRules.value.filter((item) => item.id !== id);
  }
}
async function removeValueMapping(id: number) {
  if (!await confirmAction({
    title: "Удалить соответствие значения?",
    description: "Сохранённое правило для значения донора больше не будет применяться.",
    confirmLabel: "Удалить",
    color: "error",
  })) return;
  if (await run(`value-mapping-remove-${id}`, () => api.removeValueMappingRule(id))) {
    valueMappingRules.value = valueMappingRules.value.filter((item) => item.id !== id);
  }
}

async function createTemplateField() {
  if (!templateDetails.value || !newTemplateField.name.trim()) {
    error.value = "Укажите название нового атрибута.";
    return;
  }
  const result = await run("field-create", () =>
    api.createField(templateDetails.value!.id, { ...newTemplateField }),
  );
  if (!result) return;
  templateDetails.value = result;
  newTemplateField.name = "";
  showNewTemplateField.value = false;
  await loadWorkspace();
  notify("Атрибут добавлен");
}

async function removeTemplateField(field: NonNullable<AttributeTemplate["fields"]>[number]) {
  const requestKey = `field-remove-${field.id}`;
  if (!templateDetails.value || busy.value === requestKey) return;
  if (!await confirmAction({
    title: `Удалить атрибут «${field.name}»?`,
    description: "Заполненные значения товаров сохранятся как дополнительные атрибуты.",
    confirmLabel: "Удалить атрибут",
    color: "error",
  })) return;
  const previous = templateDetails.value;
  const remainingFields = (previous.fields || []).filter((item) => item.id !== field.id);
  templateDetails.value = { ...previous, fields: remainingFields, field_count: remainingFields.length };
  workspace.value = {
    ...workspace.value,
    templates: workspace.value.templates.map((item) => item.id === previous.id
      ? { ...item, field_count: remainingFields.length }
      : item),
  };
  const result = await run(requestKey, () => api.removeField(field.id));
  if (!result) {
    templateDetails.value = previous;
    workspace.value = {
      ...workspace.value,
      templates: workspace.value.templates.map((item) => item.id === previous.id
        ? { ...item, field_count: previous.field_count }
        : item),
    };
    return;
  }
  const revisions = await api.templateRevisions(previous.id).catch(() => null);
  if (revisions) templateRevisions.value = revisions.items;
  notify("Атрибут удалён");
}

async function restoreTemplateVersion(id: number) {
  if (!templateDetails.value || !await confirmAction({
    title: "Восстановить версию шаблона?",
    description: "Текущая структура и значения шаблона будут заменены выбранной версией.",
    confirmLabel: "Восстановить",
  })) return;
  const result = await run("template-restore", () => api.restoreTemplate(templateDetails.value!.id, id));
  if (result) {
    templateDetails.value = result;
    await openTemplate(result.id);
  }
}

function editField(field: NonNullable<AttributeTemplate["fields"]>[number]) {
  error.value = "";
  templateFieldEditor.value = {
    id: field.id,
    name: field.name,
    synonyms: [...(field.synonyms || [])],
    synonymDraft: "",
    group_name: field.group_name,
    value_type: field.value_type,
    is_composite: field.is_composite,
    conversion_rules: JSON.stringify(field.conversion_rules || [], null, 2),
  };
}

function addTemplateFieldSynonym() {
  const editor = templateFieldEditor.value;
  if (!editor) return;
  const synonym = editor.synonymDraft.trim();
  if (!synonym) return;
  const key = synonym.toLocaleLowerCase("ru-RU");
  if (key === editor.name.trim().toLocaleLowerCase("ru-RU")) {
    error.value = "Синоним не должен совпадать с названием атрибута.";
    return;
  }
  if (editor.synonyms.some((item) => item.toLocaleLowerCase("ru-RU") === key)) {
    error.value = "Такой синоним уже добавлен.";
    return;
  }
  editor.synonyms.push(synonym);
  editor.synonymDraft = "";
  error.value = "";
}

function removeTemplateFieldSynonym(index: number) {
  templateFieldEditor.value?.synonyms.splice(index, 1);
}

async function saveTemplateFieldEdit() {
  const editor = templateFieldEditor.value;
  if (!editor || !editor.name.trim()) return;
  if (editor.synonymDraft.trim()) addTemplateFieldSynonym();
  if (templateFieldEditor.value?.synonymDraft.trim()) return;
  let conversionRules: unknown;
  try {
    conversionRules = JSON.parse(editor.conversion_rules || "[]");
    if (!Array.isArray(conversionRules)) throw new Error("not an array");
  } catch {
    error.value = "Правила конвертации должны быть корректным JSON-массивом.";
    return;
  }
  const result = await run(`field-${editor.id}`, () => api.updateField(editor.id, {
    name: editor.name,
    synonyms: editor.synonyms,
    group_name: editor.group_name,
    value_type: editor.value_type,
    is_composite: editor.is_composite,
    conversion_rules: conversionRules,
  }));
  if (!result) return;
  templateDetails.value = result;
  templateFieldEditor.value = null;
  notify("Атрибут и синонимы обновлены");
}

function addFieldValue(field: NonNullable<AttributeTemplate["fields"]>[number]) {
  fieldValueEditor.value = {
    fieldId: field.id,
    fieldName: field.name,
    value: "",
    synonym: "",
  };
}

async function saveFieldValue() {
  const editor = fieldValueEditor.value;
  if (!editor?.value.trim()) return;
  const result = await run(
    `field-value-${editor.fieldId}`,
    () => api.addAllowedValue(editor.fieldId, editor.value, editor.synonym),
  );
  if (!result || !templateDetails.value) return;
  fieldValueEditor.value = null;
  await openTemplate(templateDetails.value.id);
  notify("Значение добавлено");
}

function editAllowedValue(fieldName: string, allowed: AttributeAllowedValue) {
  error.value = "";
  allowedValueEditor.value = {
    id: allowed.id,
    fieldName,
    value: allowed.value,
    synonyms: [...(allowed.synonyms || [])],
    synonymDraft: "",
  };
}

function closeAllowedValueEditor() {
  const editor = allowedValueEditor.value;
  if (editor && busy.value === `allowed-${editor.id}`) return;
  allowedValueEditor.value = null;
}

function addAllowedValueSynonym() {
  const editor = allowedValueEditor.value;
  if (!editor) return;
  const synonym = editor.synonymDraft.trim();
  if (!synonym) return;
  const key = synonym.toLocaleLowerCase("ru-RU");
  if (key === editor.value.trim().toLocaleLowerCase("ru-RU")) {
    error.value = "Синоним не должен совпадать с разрешённым значением.";
    return;
  }
  if (editor.synonyms.some((item) => item.toLocaleLowerCase("ru-RU") === key)) {
    error.value = "Такой синоним уже добавлен.";
    return;
  }
  editor.synonyms.push(synonym);
  editor.synonymDraft = "";
  error.value = "";
}

function removeAllowedValueSynonym(index: number) {
  allowedValueEditor.value?.synonyms.splice(index, 1);
}

async function saveAllowedValue() {
  const editor = allowedValueEditor.value;
  if (!editor) return;
  const value = editor.value.trim();
  if (!value) {
    error.value = "Разрешённое значение не может быть пустым.";
    return;
  }
  if (editor.synonymDraft.trim()) addAllowedValueSynonym();
  if (allowedValueEditor.value?.synonymDraft.trim()) return;
  const result = await run(`allowed-${editor.id}`, () => api.updateAllowedValue(editor.id, {
    value,
    synonyms: editor.synonyms,
  }));
  if (!result) return;
  patchAllowedValue(editor.id, result.value);
  if (templateDetails.value) templateDetails.value = { ...templateDetails.value, version: result.template_version };
  allowedValueEditor.value = null;
  notify("Значение и синонимы сохранены");
}

function patchAllowedValue(id: number, values: Partial<{ value: string; is_active: boolean; is_combination: boolean; synonyms: string[] }>) {
  if (!templateDetails.value?.fields) return;
  templateDetails.value = {
    ...templateDetails.value,
    fields: templateDetails.value.fields.map((field) => ({
      ...field,
      allowed_values: field.allowed_values.map((allowed) => allowed.id === id ? { ...allowed, ...values } : allowed),
    })),
  };
}

function allowedValueMenuItems(fieldName: string, allowed: AttributeAllowedValue) {
  return [
    {
      label: "Значение и синонимы",
      icon: "i-lucide-pencil",
      onSelect: () => editAllowedValue(fieldName, allowed),
    },
    {
      label: allowed.is_active ? "Отключить" : "Включить",
      icon: allowed.is_active ? "i-lucide-circle-off" : "i-lucide-circle-check",
      disabled: busy.value === `allowed-${allowed.id}`,
      onSelect: () => void toggleAllowedValue(allowed.id, allowed.is_active),
    },
  ];
}

async function toggleAllowedValue(id: number, active: boolean) {
  const nextActive = !active;
  patchAllowedValue(id, { is_active: nextActive });
  const result = await run(`allowed-${id}`, () => api.updateAllowedValue(id, { is_active: !active }));
  if (!result) {
    patchAllowedValue(id, { is_active: active });
    return;
  }
  patchAllowedValue(id, result.value || { is_active: nextActive });
  if (templateDetails.value) templateDetails.value = { ...templateDetails.value, version: result.template_version };
  notify(nextActive ? "Значение включено" : "Значение отключено");
}
async function createBatch() {
  if (inputMode.value === "csv") {
    if (!productFile.value || !selectedTemplateId.value) {
      error.value = "Выберите CSV товаров и шаблон категории.";
      return;
    }
    const batch = await run("batch-import", () =>
      api.importBatch(
        productFile.value!,
        selectedTemplateId.value!,
        processingMode.value,
      ),
    );
    if (batch) await openBatch(batch.id);
    return;
  }
  const urls = urlsText.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  if (!urls.length) {
    error.value = "Вставьте хотя бы одну ссылку.";
    return;
  }
  const batch = await run("url-import", () =>
    api.importUrls(urls, selectedTemplateId.value, processingMode.value),
  );
  if (batch) await openBatch(batch.id);
}

function clearBatchOperationPoll() {
  if (batchOperationPoll) clearTimeout(batchOperationPoll);
  batchOperationPoll = null;
}

function currentProductOverrides(): Record<string, Record<string, string>> {
  if (!selectedProduct.value) return {};
  return { [String(selectedProduct.value.id)]: { ...donorUrlOverrides.value } };
}

function scheduleBatchOperationPoll(batchId: number, delay = 1400) {
  clearBatchOperationPoll();
  batchOperationPoll = setTimeout(() => void loadBatchOperation(batchId), delay);
}

async function loadBatchOperation(batchId: number) {
  try {
    const previous = batchOperation.value;
    const operation = await api.batchOperation(batchId);
    if (selectedBatch.value?.id !== batchId) return;
    batchOperation.value = operation;
    if (["queued", "running"].includes(operation.status)) {
      scheduleBatchOperationPoll(batchId);
      return;
    }
    clearBatchOperationPoll();
    const justFinished = previous?.id === operation.id
      && ["queued", "running"].includes(previous.status)
      && ["completed", "failed"].includes(operation.status);
    if (!justFinished) return;
    await refreshBatch();
    const productId = selectedProduct.value?.id;
    if (productId && selectedBatch.value?.id === batchId) {
      await openProduct(productId, { syncRoute: false, resetAttributeFilter: false });
    }
    const summary = "Обработано: " + operation.processed
      + " · успешно: " + operation.succeeded
      + " · ошибок: " + operation.failed;
    if (operation.status === "failed") {
      toast.add({ title: "Массовая операция остановлена", description: operation.error || summary, color: "error" });
    } else if (operation.failed) {
      toast.add({ title: "Массовая операция завершена с ошибками", description: summary, color: "warning" });
    } else {
      notify("Массовая операция завершена · " + summary);
    }
  } catch (caught) {
    if (selectedBatch.value?.id !== batchId) return;
    clearBatchOperationPoll();
    error.value = errorMessage(caught);
    if (!batchOperation.value || batchOperationRunning.value) {
      scheduleBatchOperationPoll(batchId, 5000);
    }
  }
}

async function processAllProducts() {
  if (!selectedBatch.value || !selectedDonors.value.length || batchOperationRunning.value) return;
  const total = selectedBatch.value.summary.products;
  if (!await confirmAction({
    title: "Найти и проверить все товары (" + total + ")?",
    description: "Выбранные доноры будут применены ко всей текущей обработке. Для неё используется один общий браузерный сеанс.",
    confirmLabel: "Начать проверку",
  })) return;
  const result = await run("process-all", () =>
    api.processBatch(
      selectedBatch.value!.id,
      selectedDonors.value,
      currentProductOverrides(),
    ),
  );
  if (!result) return;
  batchOperation.value = result;
  scheduleBatchOperationPoll(result.batch_id);
  notify("Проверка запущена для " + result.total + " товаров");
}

async function askChatGptForAllProducts() {
  if (!selectedBatch.value || batchOperationRunning.value) return;
  if (!chatGpt.value?.authenticated) {
    error.value = "Сначала подключите ChatGPT в блоке подключения выше.";
    return;
  }
  const total = selectedBatch.value.summary.products;
  if (!await confirmAction({
    title: "Спросить ChatGPT по всем товарам (" + total + ")?",
    description: "Каждый товар будет отправлен ChatGPT отдельным запросом. Запросы выполняются параллельно с ограничением нагрузки; ошибка одного товара не останавливает остальные.",
    confirmLabel: "Начать анализ",
  })) return;
  const result = await run("chatgpt-all", () =>
    api.analyzeBatchWithChatGpt(
      selectedBatch.value!.id,
      selectedDonors.value,
      currentProductOverrides(),
    ),
  );
  if (!result) return;
  batchOperation.value = result;
  scheduleBatchOperationPoll(result.batch_id);
  notify("ChatGPT-анализ запущен для " + result.total + " товаров");
}

async function openBatch(
  id: number,
  requestedProductId: number | null = null,
  options: { syncRoute?: boolean; resetFilters?: boolean } = {},
) {
  const syncRoute = options.syncRoute ?? true;
  const resetFilters = options.resetFilters ?? true;
  const batchChanged = selectedBatch.value?.id !== id;
  if (resetFilters && batchChanged) {
    productQuery.value = "";
    productStatusFilter.value = ALL_FILTER_VALUE;
    attributeStatusFilter.value = ALL_FILTER_VALUE;
  }
  const batch = await run("batch", () => api.batch(id));
  if (!batch) return false;
  clearBatchOperationPoll();
  batchOperation.value = null;
  selectedBatch.value = batch;
  void loadBatchOperation(id);

  tab.value = "review";
  const requested = requestedProductId
    ? batch.products?.find((product) => product.id === requestedProductId)
    : null;
  const first = requested || batch.products?.[0];
  if (first) {
    await openProduct(first.id, {
      syncRoute: false,
      resetAttributeFilter: resetFilters && selectedProduct.value?.id !== first.id,
    });
  }
  else selectedProduct.value = null;
  if (syncRoute) await writeAssistantRoute("push");
  return true;
}

async function removeBatch(batch: AttributeBatch) {
  const requestKey = `batch-remove-${batch.id}`;
  if (busy.value === requestKey) return;
  if (!await confirmAction({
    title: `Удалить обработку «${batch.name}»?`,
    description: "Будут удалены загруженный CSV, отчёты, страницы доноров и все результаты этой обработки. Шаблон останется.",
    confirmLabel: "Удалить обработку",
    color: "error",
  })) return;
  const result = await run(requestKey, () => api.removeBatch(batch.id));
  if (!result) return;
  if (selectedBatch.value?.id === batch.id) {
    clearBatchOperationPoll();
    batchOperation.value = null;
    selectedBatch.value = null;
    selectedProduct.value = null;

    historyItems.value = [];
    tab.value = "start";
    await writeAssistantRoute("replace");
  }
  await loadWorkspace();
  notify(`Обработка удалена · товаров: ${result.deleted.products}, файлов: ${result.deleted.files}`);
}

async function refreshProductHistory(productId = selectedProduct.value?.id) {
  if (!productId) {
    historyItems.value = [];
    return;
  }
  try {
    const history = await api.productHistory(productId);
    if (selectedProduct.value?.id === productId) historyItems.value = history.items;
  } catch {
    error.value = "Не удалось обновить историю изменений товара.";
  }
}

async function openProduct(
  id: number,
  options: { syncRoute?: boolean; resetAttributeFilter?: boolean } = {},
) {
  const syncRoute = options.syncRoute ?? true;
  const resetAttributeFilter = options.resetAttributeFilter ?? true;
  if (resetAttributeFilter && selectedProduct.value?.id !== id) {
    attributeStatusFilter.value = ALL_FILTER_VALUE;
  }
  const token = ++productRequestToken;
  loadingProductId.value = id;
  error.value = "";
  let product: AttributeProduct;
  try {
    product = await api.product(id);
  } catch (caught) {
    if (token === productRequestToken) error.value = errorMessage(caught);
    return false;
  } finally {
    if (token === productRequestToken) loadingProductId.value = null;
  }
  if (token !== productRequestToken) return false;
  selectedProduct.value = product;
  historyItems.value = [];
  selectedDonors.value = [...(product.selected_donor_ids || [])];
  donorUrlOverrides.value = { ...(product.donor_url_overrides || {}) };
  resetAllowedOptionState();
  void Promise.all([
    api.donorRecommendations(id).catch(() => ({ items: [] })),
    api.productHistory(id).catch(() => ({ items: [] })),
  ]).then(([recommendations, history]) => {
    if (token !== productRequestToken) return;
    donorRecommendations.value = recommendations.items;
    historyItems.value = history.items;
    if (!selectedDonors.value.length) {
      selectedDonors.value = recommendations.items.filter((item) => item.recommended).slice(0, 4).map((item) => item.id);
    }
  });
  if (syncRoute) await writeAssistantRoute("push");
  return true;
}

function toggleDonor(id: number) {
  selectedDonors.value = selectedDonors.value.includes(id)
    ? selectedDonors.value.filter((item) => item !== id)
    : [...selectedDonors.value, id];
}

function moveDonor(index: number, direction: number) {
  const next = index + direction;
  if (next < 0 || next >= selectedDonors.value.length) return;
  const copy = [...selectedDonors.value];
  const current = copy[index];
  const target = copy[next];
  if (current === undefined || target === undefined) return;
  copy[index] = target; copy[next] = current;
  selectedDonors.value = copy;
}

async function processDonors() {
  if (!selectedProduct.value || !selectedDonors.value.length) {
    error.value = "Выберите доноров в порядке приоритета.";
    return;
  }
  const result = await run("process", () =>
    api.processProduct(selectedProduct.value!.id, selectedDonors.value, donorUrlOverrides.value),
  );
  if (result) {
    selectedProduct.value = result.product;
    await refreshBatch();
    const reports = result.report.reports || [];
    const opened = reports.filter((item) => ["parsed", "no_attributes"].includes(item.status)).length;
    const found = reports.reduce((sum, item) => sum + (item.attributes_found || 0), 0);
    const mapped = reports.reduce((sum, item) => sum + (item.mapped || 0), 0);
    const ambiguous = reports.reduce((sum, item) => sum + (item.ambiguous || 0), 0);
    const unknown = reports.reduce((sum, item) => sum + (item.unknown || 0), 0);
    const alreadyFilled = reports.reduce((sum, item) => sum + (item.already_filled || 0), 0);
    const failed = reports.length - opened;
    notify(
      `Страниц открыто: ${opened} · характеристик извлечено: ${found} · предложений: ${mapped}`
      + (alreadyFilled ? ` · уже заполнено: ${alreadyFilled}` : "")
      + (ambiguous ? ` · требуют сопоставления: ${ambiguous}` : "")
      + (unknown ? ` · вне справочника: ${unknown}` : "")
      + (failed ? ` · проблем: ${failed}` : ""),
    );
  }
}

async function useSimilar() {
  if (!selectedProduct.value) return;
  const result = await run("similar", () => api.useSimilar(selectedProduct.value!.id));
  if (result) {
    selectedProduct.value = result.product;
    await refreshBatch();
    notify(`Добавлено предложений: ${result.changed}`);
  }
}

async function askChatGpt() {
  if (!selectedProduct.value) return;
  if (!chatGpt.value?.authenticated) {
    error.value = "Сначала подключите ChatGPT в блоке подключения выше.";
    return;
  }
  const result = await run("chatgpt-product", () =>
    api.analyzeProductWithChatGpt(
      selectedProduct.value!.id,
      selectedDonors.value,
      donorUrlOverrides.value,
    ),
  );
  if (!result) return;
  selectedProduct.value = result.product;
  await refreshBatch();
  const warnings = result.analysis.warnings.length;
  notify(
    warnings
      ? `ChatGPT: предложений ${result.changed}, предупреждений ${warnings}`
      : `ChatGPT: добавлено предложений ${result.changed}`,
  );
}

async function assignCurrentTemplate(selection: unknown) {
  if (!selectedProduct.value) return;
  const templateId = Number(selection);
  if (!templateId) return;
  const result = await run("assign-template", () => api.assignTemplate(selectedProduct.value!.id, templateId));
  if (result) {
    selectedProduct.value = result;
    await refreshBatch();
  }
}


async function exportReadyOnly() {
  if (!selectedBatch.value) return;
  const result = await run("export-ready", () => api.export(selectedBatch.value!.id, true));
  if (result) window.location.href = `/api/attribute-assistant/batches/${selectedBatch.value.id}/download`;
}

function formatHistoryDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(date);
}

async function restoreHistory(id: number) {
  if (!selectedProduct.value || !await confirmAction({
    title: "Восстановить состояние товара?",
    description: "Текущие решения по атрибутам будут заменены выбранным состоянием.",
    confirmLabel: "Восстановить",
  })) return;
  const product = await run("history-restore", () => api.restoreProduct(selectedProduct.value!.id, id));
  if (product) {
    selectedProduct.value = product;
    await openProduct(product.id);
    await refreshBatch();
  }
}

function optionsFor(value: AttributeValue) {
  const loaded = allowedOptionCache.value[value.id] || value.allowed_values;
  const result = [...loaded];
  const pinned = [value.final_value, displayedProposal(value)]
    .flatMap((item) => value.is_composite ? item.split("/") : [item])
    .map((item) => item.trim())
    .filter((item) => item && item !== "-");
  for (const item of [...new Set(pinned)].reverse()) {
    if (!result.some((option) => option.value === item)) {
      result.unshift({ id: -result.length - 1, value: item });
    }
  }
  return result;
}

function setAllowedSearchLoading(valueId: number, loading: boolean) {
  const next = new Set(searchingAllowedValueIds.value);
  if (loading) next.add(valueId);
  else next.delete(valueId);
  searchingAllowedValueIds.value = next;
}

async function searchAllowed(value: AttributeValue, query: string) {
  if (!value.field_id) return;
  const normalizedQuery = query.trim();
  const token = (allowedRequestTokens.get(value.id) || 0) + 1;
  allowedRequestTokens.set(value.id, token);
  setAllowedSearchLoading(value.id, true);
  const result = await api.allowedValues(
    value.field_id,
    normalizedQuery,
    false,
    0,
    ALLOWED_OPTIONS_PAGE_SIZE,
  ).catch(() => null);
  if (
    result
    && allowedRequestTokens.get(value.id) === token
    && allowedSearchQueries.value[value.id] === normalizedQuery
  ) {
    allowedOptionCache.value = { ...allowedOptionCache.value, [value.id]: result.values };
    allowedOptionPages.value = {
      ...allowedOptionPages.value,
      [value.id]: {
        query: normalizedQuery,
        total: result.total,
        matched: result.matched,
        hasMore: result.has_more,
      },
    };
  }
  if (allowedRequestTokens.get(value.id) === token) {
    setAllowedSearchLoading(value.id, false);
    await nextTick();
    checkAllowedMenus(value.id);
  }
}

async function loadMoreAllowed(value: AttributeValue) {
  if (!value.field_id || searchingAllowedValueIds.value.has(value.id)) return;
  const page = allowedOptionPages.value[value.id];
  if (!page?.hasMore || page.query !== (allowedSearchQueries.value[value.id] || "")) return;
  const token = (allowedRequestTokens.get(value.id) || 0) + 1;
  allowedRequestTokens.set(value.id, token);
  setAllowedSearchLoading(value.id, true);
  const loaded = allowedOptionCache.value[value.id] || [];
  const result = await api.allowedValues(
    value.field_id,
    page.query,
    false,
    loaded.length,
    ALLOWED_OPTIONS_PAGE_SIZE,
  ).catch(() => null);
  if (
    result
    && allowedRequestTokens.get(value.id) === token
    && allowedSearchQueries.value[value.id] === page.query
  ) {
    const merged = [...loaded];
    const known = new Set(merged.map((item) => item.id));
    for (const item of result.values) {
      if (!known.has(item.id)) merged.push(item);
    }
    allowedOptionCache.value = { ...allowedOptionCache.value, [value.id]: merged };
    allowedOptionPages.value = {
      ...allowedOptionPages.value,
      [value.id]: {
        query: page.query,
        total: result.total,
        matched: result.matched,
        hasMore: result.has_more,
      },
    };
  }
  if (allowedRequestTokens.get(value.id) === token) {
    setAllowedSearchLoading(value.id, false);
    await nextTick();
    checkAllowedMenus(value.id);
  }
}

function queueAllowedSearch(value: AttributeValue, query: string) {
  const normalizedQuery = query.trim();
  allowedSearchQueries.value = { ...allowedSearchQueries.value, [value.id]: normalizedQuery };
  const previous = allowedSearchTimers.get(value.id);
  if (previous) clearTimeout(previous);
  allowedSearchTimers.set(value.id, setTimeout(() => {
    allowedSearchTimers.delete(value.id);
    void searchAllowed(value, normalizedQuery);
  }, 250));
}

async function ensureAllowedOptions(value: AttributeValue, open: boolean) {
  if (!open || !value.field_id || searchingAllowedValueIds.value.has(value.id)) return;
  const page = allowedOptionPages.value[value.id];
  if (page?.query === "" && allowedOptionCache.value[value.id]) return;
  allowedSearchQueries.value = { ...allowedSearchQueries.value, [value.id]: "" };
  await searchAllowed(value, "");
}

function finalAllowedMenuKey(value: AttributeValue) {
  return `final-${value.id}`;
}

function unknownAllowedMenuKey(value: AttributeValue, index: number) {
  return `unknown-${value.id}-${index}`;
}

function clearAllowedScrollBinding(key: string) {
  allowedScrollBindings.get(key)?.cleanup();
  allowedScrollBindings.delete(key);
}

function setAllowedSelectRef(key: string, instance: unknown) {
  if (!instance) {
    clearAllowedScrollBinding(key);
    allowedSelectRefs.delete(key);
    return;
  }
  allowedSelectRefs.set(key, instance as AllowedSelectInstance);
}

function allowedSelectRef(key: string) {
  let callback = allowedSelectRefCallbacks.get(key);
  if (!callback) {
    callback = (instance: unknown) => setAllowedSelectRef(key, instance);
    allowedSelectRefCallbacks.set(key, callback);
  }
  return callback;
}

function allowedViewport(instance: AllowedSelectInstance | undefined): HTMLElement | null {
  const exposed = instance?.viewportRef;
  if (exposed instanceof HTMLElement) return exposed;
  return exposed?.value instanceof HTMLElement ? exposed.value : null;
}

function checkAllowedMenus(valueId: number) {
  for (const binding of allowedScrollBindings.values()) {
    if (binding.valueId === valueId) binding.check();
  }
}

async function handleAllowedMenuOpen(
  value: AttributeValue,
  key: string,
  open: boolean,
) {
  clearAllowedScrollBinding(key);
  if (!open) return;
  await ensureAllowedOptions(value, true);
  await nextTick();
  const viewport = allowedViewport(allowedSelectRefs.get(key));
  if (!viewport) return;
  const check = () => {
    if (viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 48) {
      void loadMoreAllowed(value);
    }
  };
  viewport.addEventListener("scroll", check, { passive: true });
  allowedScrollBindings.set(key, {
    valueId: value.id,
    check,
    cleanup: () => viewport.removeEventListener("scroll", check),
  });
  check();
}

function resetAllowedOptionState() {
  for (const binding of allowedScrollBindings.values()) binding.cleanup();
  allowedScrollBindings.clear();
  allowedSelectRefs.clear();
  allowedSelectRefCallbacks.clear();
  allowedOptionCache.value = {};
  allowedOptionPages.value = {};
  allowedSearchQueries.value = {};
  searchingAllowedValueIds.value = new Set();
  allowedRequestTokens.clear();
  for (const timer of allowedSearchTimers.values()) clearTimeout(timer);
  allowedSearchTimers.clear();
}

function selectedFinalParts(value: AttributeValue) {
  const selected = value.status === "rejected" ? value.final_value : value.final_value || displayedProposal(value);
  return new Set(selected.split("/").map((item) => item.trim()).filter(Boolean));
}
function sourceStatusText(
  status: string,
  attributesFound = 0,
  mapped = 0,
  ambiguous = 0,
  unknown = 0,
  alreadyFilled = 0,
) {
  if (status === "parsed") return `Извлечено: ${attributesFound} · сопоставлено: ${mapped} · проверено заполненных: ${alreadyFilled} · не сопоставлено: ${ambiguous} · вне справочника: ${unknown}`;
  if (status === "resolved") return "Ссылка найдена";
  if (status === "no_attributes") return "Страница открыта, характеристик нет";
  if (status === "not_found") return "Не найдена";
  if (status === "error") return "Ошибка";
  return status || "Нет данных";
}

function sourceTitle(source: string) {
  const labels: Record<string, string> = {
    current_csv: "Исходный CSV сайта",
    own_site: "Официальный сайт",
    manual: "Ручной выбор",
    similar: "Похожий товар",
    ai: "ChatGPT",
  };
  return labels[source] || source || "Источник";
}

function sourceKind(source: AttributeSource) {
  if (source.source_type) return source.source_type;
  if (source.role === "chatgpt") return "chatgpt";
  if (source.donor_id) return "donor";
 return "site";
}

function sourceKindLabel(source: AttributeSource) {
  return {
    chatgpt: "ChatGPT",
    donor: "Донор",
    site: "Страница сайта",
 }[sourceKind(source)];
}

function bestCandidate(value: AttributeValue) {
  return [...(value.source_details.candidates || [])].sort((left, right) => {
    const priorityDifference = (left.priority ?? 999) - (right.priority ?? 999);
    return priorityDifference || (right.confidence ?? 0) - (left.confidence ?? 0);
  })[0];
}

function displayedProposal(value: AttributeValue) {
  return value.proposed_value || bestCandidate(value)?.value || "";
}

function isTechnicalDash(value: string) {
  return /^[-–—−]$/u.test(value.trim());
}

function displayedProposalSource(value: AttributeValue) {
  const candidate = bestCandidate(value);
  return sourceTitle(value.proposed_value ? value.source : candidate?.source || "");
}

function displayedProposalConfidence(value: AttributeValue) {
  return value.confidence || bestCandidate(value)?.confidence || 0;
}

function valueStatusLabel(value: AttributeValue) {
  if (!value.is_in_template) return "Вне шаблона";
  if (value.status === "conflict") return "Конфликт";
  if (value.status === "unknown") return "Нет в справочнике";
  if (value.status === "dash") return "Технический пропуск";
  if (value.status === "rejected") return "Отклонено";
  if (value.current_value) return value.source === "current_site" ? "Сохранено со страницы" : "Сохранено из CSV";
  if (value.status === "approved") return "Принято";
  if (value.status === "suggested") return "Нужно проверить";
  return "Не заполнено";
}

function currentValueCaption(value: AttributeValue) {
  if (value.current_value) {
    return value.source === "current_site" || selectedBatch.value?.input_mode === "urls"
      ? "Исходная страница сайта"
      : "Исходный CSV сайта";
  }
  return selectedBatch.value?.input_mode === "urls" ? "На странице не найдено" : "В файле не заполнено";
}

function valueStatusColor(value: AttributeValue): "error" | "warning" | "success" | "neutral" {
  if (!value.is_in_template) return "warning";
  if (value.status === "conflict" || value.status === "rejected") return "error";
  if (value.status === "unknown") return "warning";
  if (value.current_value || value.status === "approved") return "success";
  return "neutral";
}

async function valueAction(value: AttributeValue, action: "accept" | "reject" | "dash", manual = "") {
  const dashReason = action === "dash"
    ? await promptValue({
        title: "Технический пропуск",
        label: "Причина",
        defaultValue: "Не найдено после проверки источников",
        confirmLabel: "Поставить «-»",
      }) || ""
    : "";
  if (action === "dash" && !dashReason) return;
  const updated = await run(`value-${value.id}`, () =>
    api.updateValue(value.id, { action, value: manual, dash_reason: dashReason }),
  );
  if (!updated || !selectedProduct.value?.values) return;
  const index = selectedProduct.value.values.findIndex((item) => item.id === updated.id);
  if (index >= 0) selectedProduct.value.values[index] = updated;
  await refreshBatch();
}

async function removeOutsideTemplateValue(value: AttributeValue) {
  if (value.is_in_template) return;
  if (!await confirmAction({
    title: `Удалить атрибут «${value.name}»?`,
    description: "Он исчезнет из текущей обработки и последующих экспортов. Шаблон не изменится.",
    confirmLabel: "Удалить атрибут",
    color: "error",
  })) return;
  const result = await run(`value-remove-${value.id}`, () => api.removeExtraValue(value.id));
  if (!result) return;
  selectedProduct.value = result.product;
  await refreshBatch();
  notify("Атрибут вне шаблона удалён");
}

function selectedFinalValue(value: AttributeValue) {
  if (value.final_value && value.final_value !== "-") return value.final_value;
  if (value.status === "rejected") return "";
  return displayedProposal(value);
}

async function selectFinalValue(value: AttributeValue, selection: unknown) {
  const parts = (Array.isArray(selection) ? selection : [selection])
    .filter((item): item is string => typeof item === "string" && Boolean(item));
  const selected = value.is_composite
    ? parts.sort((left, right) => left.localeCompare(right, "ru")).join("/")
    : parts[0] || "";
  if (!selected) return;
  await valueAction(value, "accept", selected);
  if (!error.value) {
    notify(`Итог для «${value.name}» сохранён`);
  }
}

async function addUnknown(value: AttributeValue, unknown: NonNullable<AttributeValue["source_details"]["unknown_values"]>[number]) {
  if (!value.field_id) return;
  const confirmed = await confirmAction({
    title: `Добавить «${unknown.value}» в справочник?`,
    description: "Значение станет разрешённым для этого атрибута и будет применено к товару.",
    confirmLabel: "Добавить и применить",
  });
  if (!confirmed) return;
  const result = await run(`dictionary-${value.id}`, async () => {
    await api.addAllowedValue(value.field_id!, unknown.value);
    return api.updateValue(value.id, { action: "accept", value: unknown.value });
  });
  if (result && selectedProduct.value?.values) {
    const index = selectedProduct.value.values.findIndex((item) => item.id === result.id);
    if (index >= 0) selectedProduct.value.values[index] = result;
    await refreshBatch();
    notify("Значение добавлено в справочник");
  }
}

function unknownSelectionKey(value: AttributeValue, index: number) {
  return `${value.id}:${index}`;
}

async function rememberUnknownValue(
  value: AttributeValue,
  unknown: NonNullable<AttributeValue["source_details"]["unknown_values"]>[number],
  index: number,
) {
  const allowedValueId = unknownSelections.value[unknownSelectionKey(value, index)];
  if (!unknown.donor_id || !allowedValueId) {
    error.value = "Выберите разрешённое значение для этого донора.";
    return;
  }
  const result = await run(`value-mapping-${value.id}-${index}`, () =>
    api.rememberValueMapping(value.id, {
      donor_id: unknown.donor_id!,
      raw_value: unknown.value,
      allowed_value_id: allowedValueId,
    }),
  );
  if (!result || !selectedProduct.value?.values) return;
  const valueIndex = selectedProduct.value.values.findIndex((item) => item.id === result.value.id);
  if (valueIndex >= 0) selectedProduct.value.values[valueIndex] = result.value;
  delete unknownSelections.value[unknownSelectionKey(value, index)];
  await refreshBatch();
  notify("Значение применено и запомнено для донора");
}

async function refreshBatch() {
  if (!selectedBatch.value) return;
  const batch = await api.batch(selectedBatch.value.id);
  selectedBatch.value = batch;
  const index = workspace.value.batches.findIndex((item) => item.id === batch.id);
  if (index >= 0) workspace.value.batches[index] = batch;
  await refreshProductHistory();
}

async function bulk(action: "accept_high" | "fill_dashes") {
  if (!selectedBatch.value) return;
  const confirmed = await confirmAction({
    title: action === "accept_high" ? "Принять уверенные предложения?" : "Заполнить технические пропуски?",
    description: action === "accept_high"
      ? "Будут подтверждены все предложения с уверенностью от 90%."
      : "Во все оставшиеся неконфликтные поля будет поставлен технический пропуск.",
    confirmLabel: action === "accept_high" ? "Принять" : "Заполнить",
  });
  if (!confirmed) return;
  const result = await run("bulk", () =>
    api.bulk(selectedBatch.value!.id, {
      action,
      minimum_confidence: 90,
      dash_reason: "Не найдено после проверки источников",
    }),
  );
  if (result) {
    selectedBatch.value = result.batch;
    if (selectedProduct.value) await openProduct(selectedProduct.value.id);
    notify(`Изменено значений: ${result.changed}`);
  }
}

async function exportBatch() {
  if (!selectedBatch.value) return;
  const result = await run("export", () => api.export(selectedBatch.value!.id));
  if (!result) return;
  window.location.href = `/api/attribute-assistant/batches/${selectedBatch.value.id}/download`;
}

watch(
  [productQuery, productStatusFilter, attributeStatusFilter],
  () => {
    if (!routeStateReady || applyingRouteState || tab.value !== "review") return;
    if (filterRouteTimer) clearTimeout(filterRouteTimer);
    filterRouteTimer = setTimeout(() => {
      filterRouteTimer = null;
      if (!routeStateReady || applyingRouteState || tab.value !== "review") return;
      void writeAssistantRoute("replace");
    }, 180);
  },
);

watch(
  () => route.fullPath,
  (fullPath) => {
    if (fullPath === writtenRoute) {
      writtenRoute = "";
      return;
    }
    if (routeStateReady) void applyAssistantRoute();
  },
);

onMounted(async () => {
  try {
    await Promise.all([loadWorkspace(), loadChatGpt()]);
    await applyAssistantRoute();
  } finally {
    loading.value = false;
  }
});
onBeforeUnmount(() => {
  if (authPoll) clearInterval(authPoll);
  if (filterRouteTimer) clearTimeout(filterRouteTimer);
  clearBatchOperationPoll();
  resetAllowedOptionState();
});
</script>

<template>
  <div>
    <SectionHeader
      eyebrow="АВТОМАТИЧЕСКОЕ ЗАПОЛНЕНИЕ"
      title="Атрибуты"
      description="Загрузите товары, выберите доноров — сервис найдёт страницы по модели и подготовит значения к проверке."
    >
      <template #actions>
        <UTooltip text="Прокси используется только для подключения ChatGPT">
          <UBadge
            :color="chatGpt?.authenticated ? 'success' : 'neutral'"
            variant="subtle"
            size="lg"
            :icon="chatGpt?.authenticated ? 'i-lucide-circle-check' : 'i-lucide-circle-off'"
          >
            ChatGPT {{ chatGpt?.authenticated ? "подключён" : "не подключён" }}
          </UBadge>
        </UTooltip>
      </template>
    </SectionHeader>

    <UTabs
      :model-value="tab"
      :items="mainTabItems"
      :content="false"
      variant="link"
      size="lg"
      class="aa-tabs"
      aria-label="Разделы вкладки"
      @update:model-value="changeMainTab"
    />

    <UAlert
      v-if="error"
      color="error"
      variant="subtle"
      icon="i-lucide-circle-alert"
      :description="error"
      orientation="horizontal"
      :close="{ color: 'error', variant: 'ghost' }"
      class="aa-alert"
      @update:open="(open) => { if (!open) error = '' }"
    />

    <USkeleton v-if="loading" class="aa-loading h-24 w-full" />

    <template v-else-if="tab === 'start'">
      <div class="aa-metrics aa-dashboard">
        <MetricCard label="Товаров в работе" :value="workspace.dashboard.products" icon="i-lucide-package-search" tone="blue" />
        <MetricCard label="Готово" :value="workspace.dashboard.ready" icon="i-lucide-circle-check-big" tone="mint" />
        <MetricCard label="Конфликтов" :value="workspace.dashboard.conflicts" icon="i-lucide-triangle-alert" tone="red" />
        <MetricCard label="Активных шаблонов" :value="workspace.dashboard.active_templates" icon="i-lucide-layout-template" tone="purple" />
      </div>
      <div class="aa-grid aa-grid--start">
        <UCard as="section" variant="outline" class="aa-card aa-card--main">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Шаг 1</span>
              <h2>Что обрабатываем?</h2>
            </div>
            <UTabs
              v-model="inputMode"
              :items="inputModeItems"
              :content="false"
              size="sm"
              class="aa-switch"
            />
          </div>

          <UFileUpload
            v-if="inputMode === 'csv'"
            v-model="productFile"
            class="aa-drop"
            accept=".csv,text/csv"
            icon="i-lucide-upload-cloud"
            :label="productFile?.name || 'Выберите CSV с товарами'"
            description="CP1251 или UTF-8 · разделитель определяется автоматически"
            :preview="false"
          />
          <UFormField
            v-else
            label="Ссылки на товары — по одной в строке"
            description="Категорию попробуем определить по странице. Если не получится — используем выбранный ниже шаблон."
          >
            <UTextarea v-model="urlsText" :rows="7" placeholder="https://site.ru/product/model" class="w-full" />
          </UFormField>

          <div class="aa-form-row">
            <UFormField label="Шаблон категории">
              <USelect v-model="selectedTemplateId" :items="templateSelectItems" class="w-full" />
            </UFormField>
            <UFormField label="Режим обработки">
              <USelect v-model="processingMode" :items="processingModeItems" class="w-full" />
            </UFormField>
          </div>

          <UButton
            color="primary"
            size="lg"
            trailing-icon="i-lucide-arrow-right"
            class="aa-create-action"
            :loading="busy === 'batch-import' || busy === 'url-import'"
            :disabled="Boolean(busy)"
            @click="createBatch"
          >
            Создать обработку
          </UButton>
        </UCard>

        <aside class="aa-side">
          <UCard as="section" variant="outline" class="aa-card">
            <div class="aa-card-head">
              <div>
                <span class="aa-step">ChatGPT</span>
                <h2>Умные подсказки</h2>
              </div>
              <UBadge :color="chatGpt?.authenticated ? 'success' : 'neutral'" variant="subtle">
                {{ chatGpt?.authenticated ? "Готов" : "Отключён" }}
              </UBadge>
            </div>
            <p class="aa-muted" v-if="!chatGpt?.available">{{ chatGpt?.error || "Codex App Server недоступен" }}</p>
            <template v-else-if="chatGpt?.authenticated">
              <p class="aa-muted">{{ chatGpt.account?.email || "Авторизация ChatGPT активна" }}</p>
              <UButton color="neutral" variant="soft" @click="logoutChatGpt">Отключить аккаунт</UButton>
            </template>
            <template v-else>
              <p class="aa-muted">Авторизация через код устройства. Ключ API не нужен.</p>
              <UButton color="neutral" variant="soft" :disabled="busy === 'chatgpt-login'" @click="loginChatGpt">
                Подключить ChatGPT
              </UButton>
            </template>
            <div v-if="deviceLogin" class="aa-device-code">
              <small>Введите код на открывшейся странице</small>
              <strong>{{ deviceLogin.user_code }}</strong>
              <UButton as="a" color="primary" variant="link" trailing-icon="i-lucide-external-link" :href="deviceLogin.verification_url" target="_blank" rel="noopener">Открыть страницу входа</UButton>
            </div>
            <p class="aa-privacy">При ручном запуске в ChatGPT передаются точная URL карточки и видимый текст страницы. CSV-файл и данные других товаров не передаются.</p>
          </UCard>

          <UCard as="section" variant="outline" class="aa-card">
            <div class="aa-card-head"><h2>Последние обработки</h2></div>
            <article
              v-for="batch in workspace.batches.slice(0, 5)"
              :key="batch.id"
              class="aa-history-entry"
            >
              <UButton color="neutral" variant="ghost" block class="aa-history" @click="openBatch(batch.id)">
                <span><strong>{{ batch.name }}</strong><small>{{ batch.template.category }}</small></span>
                <b>{{ batch.summary.needs_review }}</b>
              </UButton>
              <UButton
                color="error"
                variant="ghost"
                icon="i-lucide-trash-2"
                square

                :loading="busy === `batch-remove-${batch.id}`"
                :title="`Удалить обработку «${batch.name}»`"
                :aria-label="`Удалить обработку «${batch.name}»`"
                @click="removeBatch(batch)"
              />
            </article>
            <p v-if="!workspace.batches.length" class="aa-muted">Пока ничего не загружено.</p>
          </UCard>
        </aside>
      </div>
    </template>



    <template v-else-if="tab === 'templates'">
      <div class="aa-grid aa-grid--templates">
        <UCard as="section" variant="outline" class="aa-card">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Импорт</span>
              <h2>Новый шаблон категории</h2>
            </div>
          </div>
          <p class="aa-muted">Каждый столбец — атрибут. Формат заголовка: «Атрибут (Группа)». Строки столбца станут разрешёнными значениями.</p>
          <div class="aa-form-stack">
            <UFormField label="CSV шаблона">
              <UFileUpload
                v-model="templateFile"
                accept=".csv,text/csv"
                variant="button"
                label="Выбрать CSV"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Категория" required>
              <UInput v-model="templateForm.category" placeholder="Бытовая техника → Стиральные машины" class="w-full" />
            </UFormField>
            <UFormField label="Название шаблона" required>
              <UInput v-model="templateForm.name" placeholder="Стиральные машины" class="w-full" />
            </UFormField>
            <UFormField label="Тип товара" hint="необязательно">
              <UInput v-model="templateForm.product_type" placeholder="Стиральная машина" class="w-full" />
            </UFormField>
          </div>
          <div class="aa-inline-actions">
            <UButton color="neutral" variant="soft" icon="i-lucide-file-search" :loading="busy === 'template-preview'" :disabled="Boolean(busy)" @click="previewNewTemplate">Проверить файл</UButton>
            <UButton color="primary" icon="i-lucide-file-plus-2" :loading="busy === 'template-import'" :disabled="Boolean(busy) || !templatePreview?.can_import" @click="importTemplate">
              Подтвердить импорт
            </UButton>
          </div>
          <div v-if="templatePreview" class="aa-preview">
            <strong>Строк: {{ templatePreview.rows }} · атрибутов: {{ templatePreview.fields.length }}</strong>
            <span v-if="templatePreview.removed_fields.length">Будут отсутствовать в файле: {{ templatePreview.removed_fields.length }}</span>
            <p v-for="warning in templatePreview.warnings" :key="warning" class="aa-warning-text">{{ warning }}</p>
          </div>
        </UCard>

        <UCard as="section" variant="outline" class="aa-card aa-card--main">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Справочник</span>
              <h2>Шаблоны категорий</h2>
            </div>
            <UBadge color="neutral" variant="subtle">{{ templates.length }}</UBadge>
          </div>
          <div v-if="templates.length" class="aa-template-list">
            <article v-for="item in templates" :key="item.id" class="aa-template-row">
              <span class="aa-template-icon"><UIcon name="i-lucide-folders" /></span>
              <span>
                <strong>{{ item.name }}</strong>
                <small>{{ item.category }}</small>
              </span>
              <b>{{ item.field_count }} атр.</b>
              <span class="aa-template-row-actions">
                <UButton
                  color="neutral"
                  variant="soft"
                  icon="i-lucide-folder-open"
                  :loading="busy === `template-open-${item.id}`"
                  @click="openTemplate(item.id)"
                />
                <UButton
                  color="error"
                  variant="ghost"
                  icon="i-lucide-trash-2"
                  :loading="busy === `template-remove-${item.id}`"
                  @click="removeTemplate(item)"
                />
              </span>
            </article>
          </div>
          <EmptyState
            v-else
            icon="i-lucide-layout-template"
            title="Сначала импортируйте шаблон"
            description="Он задаст порядок, группы, типы и разрешённые значения."
          />
        </UCard>
      </div>

      <UCard as="section" variant="outline" v-if="templateDetails" class="aa-card aa-template-editor">
        <div class="aa-card-head">
          <div>
            <span class="aa-step">Редактор</span>
            <h2>{{ templateDetails.name }}</h2>
            <p>{{ templateDetails.category }} · {{ templateDetails.field_count }} атрибутов</p>
          </div>
          <div class="aa-inline-actions">
            <UButton color="neutral" variant="soft" @click="copyCurrentTemplate">Создать копию</UButton>
            <UButton
              :color="templateDetails.is_active ? 'error' : 'success'"
              variant="soft"
              :icon="templateDetails.is_active ? 'i-lucide-circle-off' : 'i-lucide-circle-check'"
              :loading="busy === 'template-active'"
              @click="toggleTemplateActive"
            >
              {{ templateDetails.is_active ? "Деактивировать" : "Активировать" }}
            </UButton>
            <UButton color="primary" @click="useTemplateForNewBatch(templateDetails.id)">Использовать</UButton>
            <UButton
              color="error"
              variant="soft"
              icon="i-lucide-trash-2"
              :loading="busy === `template-remove-${templateDetails.id}`"
              @click="removeTemplate(templateDetails)"
            >Удалить шаблон</UButton>
          </div>
        </div>

        <div class="aa-template-update">
          <UFormField label="Обновить из CSV">
            <UFileUpload
              v-model="templateUpdateFile"
              accept=".csv,text/csv"
              variant="button"
              label="Выбрать CSV"
              class="w-full"
            />
          </UFormField>
          <UFormField label="Режим обновления">
            <USelect v-model="templateUpdateMode" :items="templateUpdateModeItems" class="w-full" />
          </UFormField>
          <UButton color="primary" icon="i-lucide-refresh-cw" :loading="busy === 'template-update'" :disabled="!templateUpdateFile" @click="updateTemplateCsv">Проверить diff и обновить</UButton>
        </div>
        <div class="aa-template-field-toolbar">
          <div>
            <strong>Поля шаблона</strong>
            <small>Добавляйте, редактируйте и удаляйте атрибуты шаблона.</small>
          </div>
          <UButton color="primary" @click="showNewTemplateField = !showNewTemplateField">
            {{ showNewTemplateField ? "Отмена" : "+ Добавить атрибут" }}
          </UButton>
        </div>

        <form v-if="showNewTemplateField" class="aa-new-template-field" @submit.prevent="createTemplateField">
          <UFormField label="Группа" required><UInput v-model="newTemplateField.group_name" class="w-full" /></UFormField>
          <UFormField label="Название" required><UInput v-model="newTemplateField.name" class="w-full" /></UFormField>
          <UFormField label="Тип значения">
            <USelect v-model="newTemplateField.value_type" :items="templateFieldTypeItems" class="w-full" />
          </UFormField>
          <UCheckbox v-model="newTemplateField.is_required" label="Обязательный" />
          <UCheckbox v-model="newTemplateField.is_composite" label="Составной через /" />
          <UButton color="primary" icon="i-lucide-plus" type="submit" :loading="busy === 'field-create'">Добавить</UButton>
        </form>


        <div class="aa-template-fields">
          <UCollapsible
            v-for="field in templateDetails.fields"
            :key="field.id"
            class="aa-template-field"
            @update:open="handleTemplateFieldOpen($event, field.id)"
          >
            <template #default="{ open }">
              <UButton color="neutral" variant="ghost" block class="aa-template-field-trigger">
                <span class="aa-template-field-title">
                  <strong>{{ field.group_name }} · {{ field.name }}</strong>
                  <small>
                    {{ field.value_type }} · {{ field.allowed_values_count }} значений
                    <template v-if="field.synonyms?.length"> · {{ field.synonyms.length }} синон.</template>
                  </small>
                </span>
                <UIcon name="i-lucide-chevron-down" :class="['aa-template-field-chevron', { open }]" />
              </UButton>
            </template>
            <template #content>
              <div class="aa-template-field-content">
                <div class="aa-inline-actions aa-template-field-actions">
                  <UButton color="neutral" variant="soft" icon="i-lucide-pencil" @click="editField(field)">Изменить</UButton>
                  <UButton color="primary" variant="soft" icon="i-lucide-plus" @click="addFieldValue(field)">Добавить значение</UButton>
                  <UButton
                    color="error"
                    variant="soft"
                    icon="i-lucide-trash-2"
                    :loading="busy === `field-remove-${field.id}`"
                    @click="removeTemplateField(field)"
                  >Удалить</UButton>
                </div>
                <div class="aa-value-chips">
                  <div class="aa-template-value-tools">
                    <UInput
                      :value="templateFieldQueries[field.id] || ''"
                      type="search"
                      icon="i-lucide-search"
                      placeholder="Найти значение или синоним…"
                      class="w-full"
                      @input="queueTemplateFieldValueSearch(field.id, $event)"
                    />
                    <small v-if="templateFieldQueries[field.id]">Найдено: {{ templateFieldMatchedCounts[field.id] ?? 0 }}</small>
                    <small v-else>Показаны первые {{ Math.min(field.allowed_values.length, 80) }} из {{ field.allowed_values_count }}</small>
                  </div>
                  <div v-if="loadingTemplateFieldIds.has(field.id)" class="aa-template-values-loading">
                    <USkeleton v-for="index in 4" :key="index" class="h-8 w-28 rounded-full" />
                  </div>
                  <div
                    v-for="allowed in field.allowed_values.slice(0, 80)"
                    :key="allowed.id"
                    :class="['aa-value-chip', { inactive: !allowed.is_active }]"
                  >
                    <UButton
                      color="neutral"
                      variant="soft"
                      class="aa-value-chip-main"
                      :title="allowed.synonyms?.length ? `Синонимы: ${allowed.synonyms.join(', ')}` : 'Изменить значение'"
                      @click="editAllowedValue(field.name, allowed)"
                    >
                      <span>{{ allowed.value }}</span>
                      <UBadge v-if="allowed.is_combination" color="neutral" variant="subtle" size="xs">комбинация</UBadge>
                      <UBadge v-if="allowed.synonyms?.length" color="primary" variant="subtle" size="xs">{{ allowed.synonyms.length }} синон.</UBadge>
                    </UButton>
                    <UDropdownMenu :items="allowedValueMenuItems(field.name, allowed)">
                      <UButton
                        color="neutral"
                        variant="ghost"
                        icon="i-lucide-ellipsis"
                        square
                        aria-label="Действия со значением"
                      />
                    </UDropdownMenu>
                  </div>
                  <EmptyState
                    v-if="loadedTemplateFieldIds.has(field.id) && !field.allowed_values.length"
                    icon="i-lucide-search-x"
                    :title="templateFieldQueries[field.id] ? 'Совпадений не найдено' : 'Разрешённых значений пока нет'"
                    description="Измените запрос или добавьте новое значение в справочник."
                  />
                </div>
              </div>
            </template>
          </UCollapsible>
        </div>
        <SettingsCollapsible class="aa-template-history" content-class="aa-template-history-content">
          <template #label>
            <span>Сохранённые сопоставления доноров</span>
            <UBadge color="neutral" variant="subtle" size="sm">{{ mappingRules.length }}</UBadge>
          </template>
          <div v-for="rule in mappingRules" :key="rule.id" class="aa-history-row">
            <span><strong>{{ rule.donor_name }}: {{ rule.donor_attribute_name }}</strong><small>→ {{ rule.field_name }}</small></span>
            <UButton color="error" variant="ghost" icon="i-lucide-trash-2" :loading="busy === `mapping-remove-${rule.id}`" @click="removeMapping(rule.id)">Удалить</UButton>
          </div>
          <EmptyState
            v-if="!mappingRules.length"
            icon="i-lucide-git-compare-arrows"
            title="Сопоставлений пока нет"
            description="Правила появятся после действия «Запомнить и применить» у характеристики донора."
          />
        </SettingsCollapsible>
        <SettingsCollapsible class="aa-template-history" content-class="aa-template-history-content">
          <template #label>
            <span>Сопоставления значений доноров</span>
            <UBadge color="neutral" variant="subtle" size="sm">{{ valueMappingRules.length }}</UBadge>
          </template>
          <div v-for="rule in valueMappingRules" :key="rule.id" class="aa-history-row">
            <span>
              <strong>{{ rule.donor_name }}: {{ rule.raw_value }} → {{ rule.allowed_value }}</strong>
              <small>{{ rule.field_name }}</small>
            </span>
            <UButton color="error" variant="ghost" icon="i-lucide-trash-2" :loading="busy === `value-mapping-remove-${rule.id}`" @click="removeValueMapping(rule.id)">Удалить</UButton>
          </div>
          <EmptyState
            v-if="!valueMappingRules.length"
            icon="i-lucide-book-open-check"
            title="Сопоставлений значений пока нет"
            description="Они появятся после сохранения выбранного значения для конкретного донора."
          />
        </SettingsCollapsible>
        <SettingsCollapsible
          class="aa-template-history"
          content-class="aa-template-history-content"
          @update:open="handleTemplateHistoryOpen"
        >
          <template #label>
            <span>История шаблона</span>
            <UBadge color="neutral" variant="subtle" size="sm">{{ templateRevisions.length }}</UBadge>
          </template>
          <div v-if="templateRevisionsLoading" class="space-y-2">
            <USkeleton v-for="index in 3" :key="index" class="h-10 w-full" />
          </div>
          <div v-for="revision in templateRevisions" :key="revision.id" class="aa-history-row">
            <span><strong>Версия {{ revision.version }}</strong><small>{{ revision.action }} · {{ revision.created_at }}</small></span>
            <UButton color="neutral" variant="soft" icon="i-lucide-history" @click="restoreTemplateVersion(revision.id)">Восстановить</UButton>
          </div>
        </SettingsCollapsible>
      </UCard>
    </template>

    <template v-else-if="tab === 'review' && selectedBatch">
      <div class="aa-review-head">
        <div>
          <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-left" @click="changeMainTab('start')">← К загрузке</UButton>
          <h2>{{ selectedBatch.name }}</h2>
          <p>{{ selectedBatch.template.category }} · {{ selectedBatch.summary.products }} товаров</p>
        </div>
        <div class="aa-review-actions">
          <UButton color="neutral" variant="soft" @click="bulk('accept_high')">Принять уверенные</UButton>
          <UButton color="neutral" variant="soft" @click="bulk('fill_dashes')">Заполнить пропуски «-»</UButton>

          <UButton v-if="selectedBatch.original_ready" :to="`/api/attribute-assistant/batches/${selectedBatch.id}/original/download`" external color="neutral" variant="soft" icon="i-lucide-file-spreadsheet">Исходный CSV</UButton>
          <UButton :to="`/api/attribute-assistant/batches/${selectedBatch.id}/report/download`" external color="neutral" variant="soft" icon="i-lucide-file-text">Скачать отчёт</UButton>
          <UButton color="neutral" variant="soft" :disabled="Boolean(busy)" @click="exportReadyOnly">Экспортировать готовые</UButton>
          <UButton color="primary" :disabled="Boolean(busy)" @click="exportBatch">
            <UIcon name="i-lucide-download" /> Экспорт всех
          </UButton>
          <UButton
            color="error"
            variant="soft"
            icon="i-lucide-trash-2"
            :loading="busy === `batch-remove-${selectedBatch.id}`"
            @click="removeBatch(selectedBatch)"
          >Удалить обработку</UButton>
        </div>
      </div>

      <div class="aa-metrics">
        <MetricCard label="Готово" :value="selectedBatch.summary.ready" icon="i-lucide-circle-check-big" tone="mint" />
        <MetricCard label="Предложений" :value="selectedBatch.summary.suggestions" icon="i-lucide-lightbulb" tone="blue" />
        <MetricCard label="Конфликтов" :value="selectedBatch.summary.conflicts" icon="i-lucide-triangle-alert" tone="red" />
        <MetricCard label="Не найдено" :value="selectedBatch.summary.missing" icon="i-lucide-circle-help" tone="amber" />
      </div>


      <div class="aa-workspace">
        <aside class="aa-products">
          <div class="aa-products-title">Товары</div>
          <div class="aa-product-controls">
            <UInput v-model="productQuery" icon="i-lucide-search" class="aa-product-filter" placeholder="Модель, название, бренд" />
            <USelect v-model="productStatusFilter" :items="productStatusItems" value-key="value" class="aa-product-filter" />
            <small class="aa-muted">Показано {{ filteredProducts.length }} из {{ selectedBatch.products?.length || 0 }}</small>
          </div>
          <div class="aa-product-list">
            <UButton
              v-for="product in filteredProducts"
              :key="product.id"
              color="neutral"
              variant="ghost"
              block
              :class="['aa-product', { active: selectedProduct?.id === product.id }]"
              :loading="loadingProductId === product.id"
              :disabled="loadingProductId === product.id"
              @click="openProduct(product.id)"
            >
              <span>
                <strong>{{ product.model }}</strong>
                <small style="text-wrap-mode: wrap">{{ product.name || "Без названия" }}</small>
              </span>
              <b :class="product.status">{{ productListIndicator(product) }}</b>
            </UButton>
          </div>
        </aside>

        <main v-if="selectedProduct" class="aa-product-work">
          <UCard as="section" variant="outline" class="aa-card aa-source-card">
            <div class="aa-product-title">
              <div>
                <span class="aa-step">Текущий товар</span>
                <h2>{{ selectedProduct.model }}</h2>
                <p>{{ selectedProduct.name }}</p>
              </div>
              <UBadge :color="selectedProduct.status === 'ready' ? 'success' : 'warning'" variant="subtle">
                {{ selectedProduct.status === "ready" ? "Готов" : "Нужна проверка" }}
              </UBadge>
            </div>

            <div class="aa-product-settings">
              <UFormField label="Шаблон этого товара">
                <USelect
                  :model-value="selectedProduct.template?.id"
                  :items="productTemplateItems"
                  placeholder="Выберите шаблон"
                  class="w-full"
                  @update:model-value="assignCurrentTemplate"
                />
              </UFormField>
              <SettingsCollapsible class="aa-history-menu" content-class="aa-product-history">
                <template #label>
                  <span>История изменений</span>
                  <UBadge color="neutral" variant="subtle" size="sm">{{ historyItems.length }}</UBadge>
                </template>
                <article v-for="item in historyItems" :key="item.id" class="aa-product-history-item">
                  <span>
                    <strong>{{ item.label }}</strong>
                    <small>{{ formatHistoryDate(item.created_at) }} · изменено: {{ item.changed_count }}</small>
                  </span>
                  <UButton color="neutral" variant="soft" icon="i-lucide-undo-2" :loading="busy === 'history-restore'" @click="restoreHistory(item.id)">Вернуть</UButton>
                </article>
                <EmptyState
                  v-if="!historyItems.length"
                  icon="i-lucide-history"
                  title="Изменений пока нет"
                  description="Здесь появятся точки восстановления товара."
                />
              </SettingsCollapsible>
            </div>

            <div class="aa-source-grid">
              <div class="aa-donor-picker">
                <div class="aa-section-title">
                  <span><strong>Доноры</strong><small>Отметьте нужные сайты</small></span>
                  <b>{{ selectedDonors.length }}</b>
                </div>
                <label v-for="donor in displayedDonors" :key="donor.id" :class="['aa-donor-check', { recommended: donor.recommended }]">
                  <UCheckbox
                    :model-value="selectedDonors.includes(donor.id)"
                    @update:model-value="toggleDonor(donor.id)"
                  />
                  <span><strong>{{ donor.name }} <em v-if="donor.recommended">рекомендуем {{ donor.score }}%</em></strong><small>{{ donor.site_url }} · {{ donor.connection_name }}<template v-if="donor.reasons?.length"> · {{ donor.reasons.join("; ") }}</template></small></span>
                </label>
              </div>

              <div class="aa-priority-list">
                <div class="aa-section-title">
                  <span><strong>Порядок проверки</strong><small>Первая строка имеет наивысший приоритет</small></span>
                </div>
                <div v-if="selectedDonorRows.length" class="aa-priority-rows">
                  <div v-for="(donor, index) in selectedDonorRows" :key="donor.id" class="aa-priority-row">
                    <b>{{ index + 1 }}</b>
                    <span>
                      <strong>{{ donor.name }}</strong>
                      <small>{{ index === 0 ? "Главный источник данных" : "Проверка и дополнение" }}</small>
                    </span>
                    <UInput v-model="donorUrlOverrides[String(donor.id)]" class="aa-url-override" :placeholder="`URL товара вручную (необязательно)`" />
                    <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-up" square :disabled="index === 0" aria-label="Поднять донора" @click="moveDonor(index, -1)" />
                    <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-down" square :disabled="index === selectedDonorRows.length - 1" aria-label="Опустить донора" @click="moveDonor(index, 1)" />
                  </div>
                </div>
                <div v-else class="aa-priority-empty">Выберите доноров слева. Ссылка на товар будет найдена по модели автоматически.</div>
                <div class="aa-inline-actions">
                  <UButton color="primary" :disabled="batchOperationRunning || busy === 'process' || !selectedDonors.length" @click="processDonors">
                    <UIcon name="i-lucide-wand-sparkles" /> Найти и проверить
                  </UButton>
                  <UButton
                    color="primary"
                    variant="soft"
                    icon="i-lucide-sparkles"
                    :loading="busy === 'chatgpt-product'"
                    :disabled="batchOperationRunning || !chatGpt?.authenticated"
                    :title="chatGpt?.authenticated ? 'Проанализировать страницу выбранного товара через ChatGPT' : 'Сначала подключите ChatGPT'"
                    @click="askChatGpt"
                  >Спросить ChatGPT</UButton>
                  <UButton color="neutral" variant="soft" :disabled="batchOperationRunning || busy === 'similar'" @click="useSimilar">Похожие товары</UButton>
                </div>
              </div>
            </div>

            <div class="aa-batch-operation">
              <div class="aa-batch-operation-head">
                <span>
                  <strong>Все товары текущей проверки</strong>
                  <small>Массовая обработка продолжится в фоне, даже если выбрать другой товар</small>
                </span>
                <div class="aa-inline-actions">
                  <UButton
                    color="primary"
                    icon="i-lucide-scan-search"
                    :loading="busy === 'process-all'"
                    :disabled="batchOperationRunning || !selectedDonors.length"
                    @click="processAllProducts"
                  >Найти и проверить (все товары)</UButton>
                  <UButton
                    color="primary"
                    variant="soft"
                    icon="i-lucide-sparkles"
                    :loading="batchChatGptLoading"
                    :disabled="batchChatGptLoading || batchOperationRunning || !batchOperation || !chatGpt?.authenticated"
                    @click="askChatGptForAllProducts"
                  >Спросить ChatGPT (все товары)</UButton>
                </div>
              </div>
              <div v-if="batchOperation?.kind === 'donors' && batchOperation.status !== 'idle'" class="aa-batch-operation-progress">
                <div>
                  <strong>{{ batchOperationRunning ? "Поиск и проверка всех товаров" : "Последняя массовая операция" }}</strong>
                  <span>
                    {{ batchOperation.processed }} из {{ batchOperation.total }}
                    · успешно {{ batchOperation.succeeded }}
                    · ошибок {{ batchOperation.failed }}
                    · извлечено {{ batchOperation.attributes_found }}
                  </span>
                </div>
                <UProgress :model-value="batchOperation.percent" color="primary" size="sm" />
                <small v-if="batchOperation.current_product">Сейчас: {{ batchOperation.current_product }}</small>
                <small v-else-if="batchOperation.status === 'failed'" class="aa-operation-error">{{ batchOperation.error || batchOperation.errors[0]?.error }}</small>
              </div>
              <p v-else-if="batchOperation?.kind === 'chatgpt' && batchOperation.status === 'failed'" class="aa-operation-error" role="alert">
                {{ batchOperation.error || batchOperation.errors[0]?.error || "Не удалось выполнить анализ ChatGPT" }}
              </p>
            </div>


            <div v-if="displayedProductSources.length" class="aa-source-results">
              <ULink
                v-for="source in displayedProductSources"
                :key="source.id"
                :href="source.url"
                target="_blank"
                rel="noopener"
                :class="['aa-source-result', source.status]"
              >
                <span>
                  <span class="aa-source-result-heading">
                    <strong>{{ source.donor_name }}</strong>
                    <em :class="['aa-source-kind', `is-${sourceKind(source)}`]">{{ sourceKindLabel(source) }}</em>
                  </span>
                  <small :title="source.message || source.role">{{ source.message || source.role }}</small>
                </span>
                <b>{{ sourceStatusText(source.status, source.attributes_found, source.mapped, source.ambiguous, source.unknown, source.already_filled) }}</b>
              </ULink>
            </div>
          </UCard>

          <UCard as="section" variant="outline" class="aa-card aa-attributes">
            <div class="aa-card-head">
              <div>
                <span class="aa-step">Проверка</span>
                <h2>Атрибуты товара</h2>
                <small class="aa-muted">Заполненные значения защищены</small>
              </div>
              <div class="aa-attribute-toolbar">
                <USelect
                  v-model="attributeStatusFilter"
                  :items="attributeStatusItems"
                  value-key="value"
                  class="aa-attribute-status-filter"
                  aria-label="Фильтр атрибутов по статусу"
                />
                <span class="aa-muted">
                  Показано {{ filteredAttributeValues.length }} из {{ attributeValues.length }}
                </span>
              </div>
            </div>

            <UAlert
              v-if="!valuesByGroup.length"
              color="neutral"
              variant="soft"
              icon="i-lucide-list-filter"
              title="По выбранному фильтру атрибутов нет"
              description="Выберите другой статус или покажите все атрибуты."
            />
            <div v-for="[group, values] in valuesByGroup" :key="group" class="aa-attribute-group">
              <h3>{{ group }}</h3>
              <article v-for="value in values" :key="value.id" :class="['aa-attribute', `is-${value.status}`, { 'is-outside-template': !value.is_in_template }]">
                <div class="aa-attribute-row-head">
                  <div class="aa-attribute-name">
                    <strong>{{ value.name }}</strong>
                    <small v-if="!value.is_in_template">Исходная группа: {{ value.group_name || "Без группы" }}</small>
                    <small v-else-if="value.allowed_values_count">Справочник: {{ value.allowed_values_count }} значений</small>
                    <small v-else>{{ value.is_composite ? "Составной атрибут" : value.value_type }}</small>
                  </div>
                  <UBadge :color="valueStatusColor(value)" variant="subtle">{{ valueStatusLabel(value) }}</UBadge>
                </div>

                <div class="aa-attribute-comparison">
                  <div class="aa-comparison-cell is-current">
                    <span>Было</span>
                    <strong>{{ value.current_value }}</strong>
                    <small>{{ currentValueCaption(value) }}</small>
                  </div>
                  <div class="aa-comparison-cell is-proposed">
                    <span>Предложение</span>
                    <strong :class="{ 'aa-not-found': !displayedProposal(value) }">{{ displayedProposal(value) }}</strong>
                    <small v-if="displayedProposal(value)">
                      {{ displayedProposalSource(value) }}
                      <template v-if="displayedProposalConfidence(value)"> · {{ displayedProposalConfidence(value) }}%</template>
                    </small>
                    <small v-else>{{ value.reason || "Источники ещё не дали значения" }}</small>
                  </div>
                  <div class="aa-comparison-cell is-final">
                    <span>Итог</span>
                    <USelectMenu
                      v-if="value.is_composite && value.allowed_values_count"
                      :ref="allowedSelectRef(finalAllowedMenuKey(value))"
                      class="aa-final-select aa-final-select--multiple"
                      :model-value="[...selectedFinalParts(value)]"
                      :items="optionsFor(value).filter((item) => !item.value.includes('/'))"
                      value-key="value"
                      label-key="value"
                      :search-input="{ placeholder: 'Найти значение…' }"
                      :loading="searchingAllowedValueIds.has(value.id)"
                      :reset-search-term-on-blur="true"
                      :ignore-filter="true"
                      :virtualize="true"
                      multiple
                      :disabled="busy === `value-${value.id}`"
                      @update:search-term="queueAllowedSearch(value, $event)"
                      @update:open="handleAllowedMenuOpen(value, finalAllowedMenuKey(value), $event)"
                      @update:model-value="selectFinalValue(value, $event)"
                    />
                    <USelectMenu
                      v-else-if="value.allowed_values_count"
                      :ref="allowedSelectRef(finalAllowedMenuKey(value))"
                      class="aa-final-select"
                      :model-value="selectedFinalValue(value)"
                      :items="optionsFor(value)"
                      value-key="value"
                      label-key="value"
                      placeholder="Выберите итоговое значение"
                      :search-input="{ placeholder: 'Найти значение…' }"
                      :loading="searchingAllowedValueIds.has(value.id)"
                      :reset-search-term-on-blur="true"
                      :ignore-filter="true"
                      :virtualize="true"
                      :disabled="busy === `value-${value.id}`"
                      @update:search-term="queueAllowedSearch(value, $event)"
                      @update:open="handleAllowedMenuOpen(value, finalAllowedMenuKey(value), $event)"
                      @update:model-value="selectFinalValue(value, $event)"
                    />
                    <strong v-else>{{ value.final_value || displayedProposal(value) }}</strong>
                    <small v-if="value.status === 'dash'">{{ value.dash_reason }}</small>
                    <small v-else-if="value.status === 'conflict'">Выберите итог или отклоните предложение</small>
                    <small v-else-if="value.allowed_values_count && value.final_value">Можно выбрать другое значение из шаблона</small>
                    <small v-else-if="value.allowed_values_count && displayedProposal(value)">Предложение системы уже подставлено</small>
                    <small v-else-if="value.allowed_values_count">Выберите значение из шаблона</small>
                    <small v-else>В шаблоне нет значений для выбора</small>
                  </div>
                </div>

                <div class="aa-value-actions">
                  <UButton
                    v-if="!value.is_in_template"
                    color="error"
                    variant="soft"
                    icon="i-lucide-trash-2"
                    :loading="busy === `value-remove-${value.id}`"
                    @click="removeOutsideTemplateValue(value)"
                  >Удалить атрибут</UButton>
                  <UButton
                    v-if="value.status !== 'rejected' && displayedProposal(value) && displayedProposal(value) !== value.final_value"
                    color="success"
                    variant="soft"
                    icon="i-lucide-check"
                    :loading="busy === `value-${value.id}`"
                    @click="valueAction(value, 'accept', displayedProposal(value))"
                  >Принять</UButton>
                  <UButton
                    v-if="value.status !== 'rejected' && displayedProposal(value) && displayedProposal(value) !== value.final_value"
                    color="error"
                    variant="ghost"
                    icon="i-lucide-x"
                    :disabled="busy === `value-${value.id}`"
                    @click="valueAction(value, 'reject')"
                  >Отклонить</UButton>
                  <UButton
                    v-if="(!value.current_value || isTechnicalDash(value.current_value)) && !value.final_value"
                    color="neutral"
                    variant="ghost"
                    icon="i-lucide-minus"
                    :disabled="busy === `value-${value.id}`"
                    @click="valueAction(value, 'dash')"
                  >Поставить «-»</UButton>
                </div>

                <SettingsCollapsible
                  v-if="value.source_details.candidates?.length"
                  class="aa-candidate-details"
                  content-class="aa-candidate-list"
                  :default-open="value.status === 'conflict'"
                >
                  <template #label>
                    <span>Все источники</span>
                    <UBadge color="neutral" variant="subtle" size="sm">{{ value.source_details.candidates.length }}</UBadge>
                  </template>
                    <div
                      v-for="(candidate, index) in value.source_details.candidates"
                      :key="`${candidate.source}-${candidate.source_name}-${index}`"
                      :class="['aa-candidate', { 'is-match': candidate.matches_current, 'is-mismatch': value.current_value && !candidate.matches_current }]"
                    >
                      <div class="aa-candidate-source">
                        <ULink v-if="candidate.url" :to="candidate.url" target="_blank">{{ sourceTitle(candidate.source) }}</ULink>
                        <strong v-else>{{ sourceTitle(candidate.source) }}</strong>
                        <small>{{ candidate.role || "Источник предложения" }}</small>
                      </div>
                      <div class="aa-candidate-values">
                        <span><small>На странице · {{ candidate.source_name }}</small><strong>{{ candidate.raw_value || candidate.value }}</strong></span>
                        <span v-if="candidate.raw_value && candidate.raw_value !== candidate.value"><small>После справочника</small><strong>{{ candidate.value }}</strong></span>
                      </div>
                      <div class="aa-candidate-result">
                        <b>{{ candidate.confidence }}%</b>
                        <UBadge v-if="candidate.matches_current" color="success" variant="subtle">Совпадает</UBadge>
                        <UBadge v-else-if="value.current_value" color="error" variant="subtle">Расхождение</UBadge>
                        <UBadge v-else color="neutral" variant="subtle">Предложение</UBadge>
                      </div>
                      <small class="aa-candidate-reason">{{ candidate.reason }}</small>
                      <UButton
                        v-if="candidate.value !== value.final_value"
                        color="success"
                        variant="soft"
                        icon="i-lucide-check"
                        :loading="busy === `value-${value.id}`"
                        @click="valueAction(value, 'accept', candidate.value)"
                      >Выбрать</UButton>
                    </div>
                </SettingsCollapsible>

                <div v-for="(unknown, index) in value.source_details.unknown_values || []" :key="`unknown-${index}`" class="aa-detail-line aa-unknown-detail">
                  <span>
                    <ULink v-if="unknown.url" :to="unknown.url" target="_blank">{{ sourceTitle(unknown.source) }}</ULink>
                    <strong v-else>{{ sourceTitle(unknown.source) }}</strong>
                    · {{ unknown.source_name }}: <strong>{{ unknown.value }}</strong>
                  </span>
                  <span v-if="unknown.suggestions?.length">Ближайшее: {{ unknown.suggestions.join(", ") }}</span>
                  <div v-if="unknown.donor_id && value.field_id && !value.current_value" class="aa-unknown-map">
                    <USelectMenu
                      :ref="allowedSelectRef(unknownAllowedMenuKey(value, index))"
                      v-model="unknownSelections[unknownSelectionKey(value, index)]"
                      class="aa-unknown-select"
                      :items="optionsFor(value)"
                      value-key="id"
                      label-key="value"
                      placeholder="Выберите значение шаблона"
                      :search-input="{ placeholder: 'Найти значение…' }"
                      :loading="searchingAllowedValueIds.has(value.id)"
                      :reset-search-term-on-blur="true"
                      :ignore-filter="true"
                      :virtualize="true"
                      @update:search-term="queueAllowedSearch(value, $event)"
                      @update:open="handleAllowedMenuOpen(value, unknownAllowedMenuKey(value, index), $event)"
                    />
                    <UButton
                      color="primary"
                      variant="soft"
                      icon="i-lucide-bookmark-check"
                      :loading="busy === `value-mapping-${value.id}-${index}`"
                      :disabled="!unknownSelections[unknownSelectionKey(value, index)]"
                      @click="rememberUnknownValue(value, unknown, index)"
                    >Применить и запомнить</UButton>
                  </div>
                  <UButton v-if="!value.current_value" color="warning" variant="soft" icon="i-lucide-book-plus" :loading="busy === `dictionary-${value.id}`" @click="addUnknown(value, unknown)">Добавить как новое значение</UButton>
                </div>
              </article>
            </div>
          </UCard>
        </main>
      </div>
    </template>

    <AppDialog ref="appDialog" />

    <UModal
      :open="Boolean(templateFieldEditor)"
      title="Редактирование атрибута"
      description="Измените структуру поля и названия, встречающиеся у доноров."
      :dismissible="busy !== `field-${templateFieldEditor?.id}`"
      :ui="{ content: 'sm:max-w-2xl' }"
      @update:open="(open) => { if (!open) templateFieldEditor = null }"
    >
      <template v-if="templateFieldEditor" #body>
        <div class="aa-dialog-form">
          <UAlert v-if="error" color="error" variant="subtle" :description="error" />
          <UFormField label="Название" required>
            <UInput v-model="templateFieldEditor.name" class="w-full" />
          </UFormField>
          <UFormField label="Группа">
            <UInput v-model="templateFieldEditor.group_name" class="w-full" />
          </UFormField>
          <UFormField label="Тип значения">
            <USelect
              v-model="templateFieldEditor.value_type"
              :items="[
                { label: 'Из справочника', value: 'select' },
                { label: 'Текст', value: 'text' },
                { label: 'Число', value: 'number' },
                { label: 'Габариты', value: 'dimensions' },
                { label: 'Да / нет', value: 'boolean' },
              ]"
              class="w-full"
            />
          </UFormField>
          <UCheckbox v-model="templateFieldEditor.is_composite" label="Составное значение через /" />
          <div class="aa-synonym-editor">
            <div class="aa-synonym-editor-title">
              <span>
                <strong>Синонимы атрибута</strong>
                <small>{{ templateFieldEditor.synonyms.length }} добавлено</small>
              </span>
            </div>
            <p class="aa-muted">
              Названия характеристик у доноров, соответствующие этому атрибуту шаблона.
            </p>
            <div v-if="templateFieldEditor.synonyms.length" class="aa-synonym-list">
              <div
                v-for="(synonym, index) in templateFieldEditor.synonyms"
                :key="`${synonym}-${index}`"
                class="aa-synonym-row"
              >
                <span>{{ synonym }}</span>
                <UButton
                  type="button"
                  color="error"
                  variant="ghost"
                  size="xs"
                  icon="i-lucide-x"
                  :aria-label="`Удалить синоним ${synonym}`"
                  @click="removeTemplateFieldSynonym(index)"
                />
              </div>
            </div>
            <p v-else class="aa-synonym-empty">Синонимов пока нет.</p>
            <form class="aa-synonym-add" @submit.prevent="addTemplateFieldSynonym">
              <UInput
                v-model="templateFieldEditor.synonymDraft"
                autocomplete="off"
                placeholder="Например: диаметр загрузочного проёма"
                class="w-full"
              />
              <UButton
                type="submit"
                color="neutral"
                variant="soft"
                :disabled="!templateFieldEditor.synonymDraft.trim()"
              >
                Добавить
              </UButton>
            </form>
          </div>
          <UFormField label="Правила конвертации (JSON-массив)">
            <UTextarea v-model="templateFieldEditor.conversion_rules" :rows="6" class="w-full font-mono" />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton color="neutral" variant="soft" @click="templateFieldEditor = null">Отмена</UButton>
          <UButton
            color="primary"
            :loading="busy === `field-${templateFieldEditor?.id}`"
            :disabled="!templateFieldEditor?.name.trim()"
            @click="saveTemplateFieldEdit"
          >
            Сохранить
          </UButton>
        </div>
      </template>
    </UModal>

    <UModal
      :open="Boolean(fieldValueEditor)"
      :title="`Добавить значение · ${fieldValueEditor?.fieldName || ''}`"
      description="Новое значение попадёт в справочник этого атрибута."
      :dismissible="busy !== `field-value-${fieldValueEditor?.fieldId}`"
      @update:open="(open) => { if (!open) fieldValueEditor = null }"
    >
      <template v-if="fieldValueEditor" #body>
        <div class="aa-dialog-form">
          <UFormField label="Разрешённое значение" required>
            <UInput v-model="fieldValueEditor.value" autofocus class="w-full" />
          </UFormField>
          <UFormField label="Синоним" hint="необязательно">
            <UInput v-model="fieldValueEditor.synonym" class="w-full" />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton color="neutral" variant="soft" @click="fieldValueEditor = null">Отмена</UButton>
          <UButton
            color="primary"
            :loading="busy === `field-value-${fieldValueEditor?.fieldId}`"
            :disabled="!fieldValueEditor?.value.trim()"
            @click="saveFieldValue"
          >
            Добавить
          </UButton>
        </div>
      </template>
    </UModal>

    <UModal
      :open="Boolean(allowedValueEditor)"
      :title="`Значение и синонимы · ${allowedValueEditor?.fieldName || ''}`"
      description="Синонимы помогают сопоставить формулировки доноров с точным значением шаблона."
      :dismissible="busy !== `allowed-${allowedValueEditor?.id}`"
      :ui="{ content: 'sm:max-w-2xl' }"
      @update:open="(open) => { if (!open) closeAllowedValueEditor() }"
    >
      <template v-if="allowedValueEditor" #body>
        <div class="aa-dialog-form">
          <UAlert v-if="error" color="error" variant="subtle" :description="error" />
          <UFormField label="Разрешённое значение">
            <UInput v-model="allowedValueEditor.value" autocomplete="off" class="w-full" />
          </UFormField>

          <div class="aa-synonym-editor">
            <div class="aa-synonym-editor-title">
              <span><strong>Синонимы</strong><small>{{ allowedValueEditor.synonyms.length }} добавлено</small></span>
            </div>
            <div v-if="allowedValueEditor.synonyms.length" class="aa-synonym-list">
              <div v-for="(synonym, index) in allowedValueEditor.synonyms" :key="`${synonym}-${index}`" class="aa-synonym-row">
                <span>{{ synonym }}</span>
                <UButton
                  type="button"
                  color="error"
                  variant="ghost"
                  size="xs"
                  icon="i-lucide-x"
                  :aria-label="`Удалить синоним ${synonym}`"
                  @click="removeAllowedValueSynonym(index)"
                />
              </div>
            </div>
            <p v-else class="aa-synonym-empty">Синонимов пока нет.</p>
            <form class="aa-synonym-add" @submit.prevent="addAllowedValueSynonym">
              <UInput v-model="allowedValueEditor.synonymDraft" autocomplete="off" placeholder="Например: снизу" class="w-full" />
              <UButton type="submit" color="neutral" variant="soft" :disabled="!allowedValueEditor.synonymDraft.trim()">
                Добавить
              </UButton>
            </form>
          </div>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="soft"
            :disabled="busy === `allowed-${allowedValueEditor?.id}`"
            @click="closeAllowedValueEditor"
          >
            Отмена
          </UButton>
          <UButton
            color="primary"
            :loading="busy === `allowed-${allowedValueEditor?.id}`"
            @click="saveAllowedValue"
          >
            Сохранить
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>

<style src="../assets/css/attribute-assistant.css"></style>

