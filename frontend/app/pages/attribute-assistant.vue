<script setup lang="ts">
import { attributeAssistantService as api } from "~/services/attribute-assistant.service";
import type {
  AttributeBatch,
  AttributeDonor,
  AttributeProduct,
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
const loading = ref(true);
const busy = ref("");
const error = ref("");
const tab = ref<"start" | "templates" | "review">("start");
const inputMode = ref<"csv" | "urls">("csv");
const workspace = ref<AttributeWorkspace>({ templates: [], donors: [], batches: [] });
const selectedTemplateId = ref<number | null>(null);
const selectedBatch = ref<AttributeBatch | null>(null);
const selectedProduct = ref<AttributeProduct | null>(null);
const selectedDonors = ref<number[]>([]);
const productFile = ref<File | null>(null);
const templateFile = ref<File | null>(null);
const urlsText = ref("");
const processingMode = ref<"suggest" | "auto">("suggest");
const chatGpt = ref<ChatGptStatus | null>(null);
const deviceLogin = ref<ChatGptLogin | null>(null);
const templateForm = reactive({
  name: "",
  category: "",
  product_type: "",
  description: "",
});
let authPoll: ReturnType<typeof setInterval> | null = null;

const templates = computed(() => workspace.value.templates);
const donors = computed(() => workspace.value.donors);
const selectedTemplate = computed(() =>
  templates.value.find((item) => item.id === selectedTemplateId.value),
);
const selectedDonorRows = computed(() =>
  selectedDonors.value
    .map((id) => donors.value.find((item) => item.id === id))
    .filter((item): item is AttributeDonor => Boolean(item)),
);
const valuesByGroup = computed(() => {
  const groups = new Map<string, AttributeValue[]>();
  for (const value of selectedProduct.value?.values || []) {
    const key = value.group_name || "Без группы";
    groups.set(key, [...(groups.get(key) || []), value]);
  }
  return [...groups.entries()];
});

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

async function loadWorkspace() {
  const data = await run("load", () => api.workspace());
  if (data) {
    workspace.value = data;
    selectedTemplateId.value ||= data.templates[0]?.id || null;
  }
  loading.value = false;
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

async function importTemplate() {
  if (!templateFile.value) {
    error.value = "Выберите CSV-файл шаблона.";
    return;
  }
  const result = await run("template-import", () =>
    api.importTemplate(templateFile.value!, templateForm),
  );
  if (!result) return;
  notify("Шаблон импортирован");
  await loadWorkspace();
  selectedTemplateId.value = result.id;
  templateFile.value = null;
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

async function openBatch(id: number) {
  const batch = await run("batch", () => api.batch(id));
  if (!batch) return;
  selectedBatch.value = batch;
  tab.value = "review";
  const first = batch.products?.[0];
  selectedProduct.value = first ? await api.product(first.id) : null;
  selectedDonors.value = [];
}

async function openProduct(id: number) {
  const product = await run("product", () => api.product(id));
  if (product) selectedProduct.value = product;
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
    api.processProduct(selectedProduct.value!.id, selectedDonors.value),
  );
  if (result) {
    selectedProduct.value = result.product;
    await refreshBatch();
    notify("Доноры проверены");
  }
}

async function useSimilar() {
  if (!selectedProduct.value) return;
  const result = await run("similar", () => api.useSimilar(selectedProduct.value!.id));
  if (result) {
    selectedProduct.value = result.product;
    notify(`Добавлено предложений: ${result.changed}`);
  }
}

async function valueAction(value: AttributeValue, action: "accept" | "reject" | "dash", manual = "") {
  const dashReason = action === "dash"
    ? window.prompt("Причина технического пропуска", "Не найдено после проверки источников") || ""
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

async function addUnknown(value: AttributeValue, unknown: NonNullable<AttributeValue["source_details"]["unknown_values"]>[number]) {
  if (!value.field_id) return;
  const confirmed = window.confirm(
    `Добавить «${unknown.value}» в справочник и применить к товару?`,
  );
  if (!confirmed) return;
  const result = await run(`dictionary-${value.id}`, async () => {
    await api.addAllowedValue(value.field_id!, unknown.value);
    return api.updateValue(value.id, { action: "accept", value: unknown.value });
  });
  if (result && selectedProduct.value?.values) {
    const index = selectedProduct.value.values.findIndex((item) => item.id === result.id);
    if (index >= 0) selectedProduct.value.values[index] = result;
    notify("Значение добавлено в справочник");
  }
}

async function refreshBatch() {
  if (!selectedBatch.value) return;
  const batch = await api.batch(selectedBatch.value.id);
  selectedBatch.value = batch;
  const index = workspace.value.batches.findIndex((item) => item.id === batch.id);
  if (index >= 0) workspace.value.batches[index] = batch;
}

async function bulk(action: "accept_high" | "fill_dashes") {
  if (!selectedBatch.value) return;
  const confirmed = window.confirm(
    action === "accept_high"
      ? "Подтвердить все предложения с уверенностью от 90%?"
      : "Поставить технический пропуск во все оставшиеся неконфликтные поля?",
  );
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

onMounted(async () => {
  await Promise.all([loadWorkspace(), loadChatGpt()]);
});
onBeforeUnmount(() => authPoll && clearInterval(authPoll));
</script>

<template>
  <div class="aa-page">
    <header class="aa-hero">
      <div>
        <span class="aa-kicker">Контент без рутины</span>
        <h1>Атрибуты</h1>
        <p>Загрузите товары, выберите доноров — сервис найдёт страницы по модели и подготовит значения к проверке.</p>
      </div>
      <div class="aa-hero-status">
        <span :class="['aa-dot', chatGpt?.authenticated && 'is-online']" />
        <div>
          <strong>ChatGPT {{ chatGpt?.authenticated ? "подключён" : "не подключён" }}</strong>
          <small>Proxy используется только этим подключением</small>
        </div>
      </div>
    </header>

    <nav class="aa-tabs" aria-label="Разделы вкладки">
      <button :class="{ active: tab === 'start' }" @click="tab = 'start'">1. Новая обработка</button>
      <button :class="{ active: tab === 'templates' }" @click="tab = 'templates'">2. Шаблоны</button>
      <button :class="{ active: tab === 'review' }" :disabled="!selectedBatch" @click="tab = 'review'">
        3. Проверка
        <span v-if="selectedBatch">{{ selectedBatch.summary.needs_review }}</span>
      </button>
    </nav>

    <div v-if="error" class="aa-alert">
      <UIcon name="i-lucide-circle-alert" />
      <span>{{ error }}</span>
      <button @click="error = ''">×</button>
    </div>

    <div v-if="loading" class="aa-loading">Загружаем рабочее пространство…</div>

    <template v-else-if="tab === 'start'">
      <div class="aa-grid aa-grid--start">
        <section class="aa-card aa-card--main">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Шаг 1</span>
              <h2>Что обрабатываем?</h2>
            </div>
            <div class="aa-switch">
              <button :class="{ active: inputMode === 'csv' }" @click="inputMode = 'csv'">CSV</button>
              <button :class="{ active: inputMode === 'urls' }" @click="inputMode = 'urls'">Ссылки сайта</button>
            </div>
          </div>

          <label v-if="inputMode === 'csv'" class="aa-drop">
            <input type="file" accept=".csv,text/csv" @change="productFile = ($event.target as HTMLInputElement).files?.[0] || null">
            <UIcon name="i-lucide-upload-cloud" />
            <strong>{{ productFile?.name || "Выберите CSV с товарами" }}</strong>
            <small>CP1251 или UTF-8 · разделитель определяется автоматически</small>
          </label>
          <label v-else class="aa-field">
            <span>Ссылки на товары — по одной в строке</span>
            <textarea v-model="urlsText" rows="7" placeholder="https://site.ru/product/model"></textarea>
            <small>Категорию попробуем определить по странице. Если не получится — используем выбранный ниже шаблон.</small>
          </label>

          <div class="aa-form-row">
            <label class="aa-field">
              <span>Шаблон категории</span>
              <select v-model.number="selectedTemplateId">
                <option :value="null">Определить автоматически</option>
                <option v-for="item in templates" :key="item.id" :value="item.id">
                  {{ item.category }} · {{ item.name }}
                </option>
              </select>
            </label>
            <label class="aa-field">
              <span>Режим</span>
              <select v-model="processingMode">
                <option value="suggest">Сначала показать предложения</option>
                <option value="auto">Автопринять только уверенные</option>
              </select>
            </label>
          </div>

          <button class="aa-primary" :disabled="Boolean(busy)" @click="createBatch">
            <UIcon name="i-lucide-arrow-right" />
            Создать обработку
          </button>
        </section>

        <aside class="aa-side">
          <section class="aa-card">
            <div class="aa-card-head">
              <div>
                <span class="aa-step">ChatGPT</span>
                <h2>Умные подсказки</h2>
              </div>
              <span :class="['aa-badge', chatGpt?.authenticated ? 'success' : 'muted']">
                {{ chatGpt?.authenticated ? "Готов" : "Отключён" }}
              </span>
            </div>
            <p class="aa-muted" v-if="!chatGpt?.available">{{ chatGpt?.error || "Codex App Server недоступен" }}</p>
            <template v-else-if="chatGpt?.authenticated">
              <p class="aa-muted">{{ chatGpt.account?.email || "Авторизация ChatGPT активна" }}</p>
              <button class="aa-secondary" @click="logoutChatGpt">Отключить аккаунт</button>
            </template>
            <template v-else>
              <p class="aa-muted">Авторизация через код устройства. Ключ API не нужен.</p>
              <button class="aa-secondary" :disabled="busy === 'chatgpt-login'" @click="loginChatGpt">
                Подключить ChatGPT
              </button>
            </template>
            <div v-if="deviceLogin" class="aa-device-code">
              <small>Введите код на открывшейся странице</small>
              <strong>{{ deviceLogin.user_code }}</strong>
              <a :href="deviceLogin.verification_url" target="_blank" rel="noopener">Открыть страницу входа</a>
            </div>
            <p class="aa-privacy">Не передаём URL, HTML и файлы. Анализ запускается только вручную.</p>
          </section>

          <section class="aa-card">
            <div class="aa-card-head"><h2>Последние обработки</h2></div>
            <button
              v-for="batch in workspace.batches.slice(0, 5)"
              :key="batch.id"
              class="aa-history"
              @click="openBatch(batch.id)"
            >
              <span><strong>{{ batch.name }}</strong><small>{{ batch.template.category }}</small></span>
              <b>{{ batch.summary.needs_review }}</b>
            </button>
            <p v-if="!workspace.batches.length" class="aa-muted">Пока ничего не загружено.</p>
          </section>
        </aside>
      </div>
    </template>



    <template v-else-if="tab === 'templates'">
      <div class="aa-grid aa-grid--templates">
        <section class="aa-card">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Импорт</span>
              <h2>Новый шаблон категории</h2>
            </div>
          </div>
          <p class="aa-muted">Каждый столбец — атрибут. Формат заголовка: «Атрибут (Группа)». Строки столбца станут разрешёнными значениями.</p>
          <div class="aa-form-stack">
            <label class="aa-field">
              <span>CSV шаблона</span>
              <input type="file" accept=".csv,text/csv" @change="templateFile = ($event.target as HTMLInputElement).files?.[0] || null">
            </label>
            <label class="aa-field">
              <span>Категория</span>
              <input v-model="templateForm.category" placeholder="Бытовая техника > Стиральные машины">
            </label>
            <label class="aa-field">
              <span>Название шаблона</span>
              <input v-model="templateForm.name" placeholder="Стиральные машины">
            </label>
            <label class="aa-field">
              <span>Тип товара <small>необязательно</small></span>
              <input v-model="templateForm.product_type" placeholder="Стиральная машина">
            </label>
          </div>
          <button class="aa-primary" :disabled="Boolean(busy)" @click="importTemplate">
            <UIcon name="i-lucide-file-plus-2" /> Импортировать шаблон
          </button>
        </section>

        <section class="aa-card aa-card--main">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Справочник</span>
              <h2>Шаблоны категорий</h2>
            </div>
            <span class="aa-badge muted">{{ templates.length }}</span>
          </div>
          <div v-if="templates.length" class="aa-template-list">
            <article v-for="item in templates" :key="item.id" class="aa-template-row">
              <span class="aa-template-icon"><UIcon name="i-lucide-folders" /></span>
              <span>
                <strong>{{ item.name }}</strong>
                <small>{{ item.category }}</small>
              </span>
              <b>{{ item.field_count }} атр.</b>
              <button @click="selectedTemplateId = item.id; tab = 'start'">Использовать</button>
            </article>
          </div>
          <div v-else class="aa-empty">
            <UIcon name="i-lucide-layout-template" />
            <strong>Сначала импортируйте шаблон</strong>
            <span>Он задаст порядок, группы, типы и разрешённые значения.</span>
          </div>
        </section>
      </div>
    </template>

    <template v-else-if="tab === 'review' && selectedBatch">
      <div class="aa-review-head">
        <div>
          <button class="aa-back" @click="tab = 'start'">← К загрузке</button>
          <h2>{{ selectedBatch.name }}</h2>
          <p>{{ selectedBatch.template.category }} · {{ selectedBatch.summary.products }} товаров</p>
        </div>
        <div class="aa-review-actions">
          <button class="aa-secondary" @click="bulk('accept_high')">Принять уверенные</button>
          <button class="aa-secondary" @click="bulk('fill_dashes')">Заполнить пропуски «-»</button>
          <button class="aa-primary" :disabled="Boolean(busy)" @click="exportBatch">
            <UIcon name="i-lucide-download" /> Экспорт CSV
          </button>
        </div>
      </div>

      <div class="aa-metrics">
        <div><strong>{{ selectedBatch.summary.ready }}</strong><span>готово</span></div>
        <div><strong>{{ selectedBatch.summary.suggestions }}</strong><span>предложений</span></div>
        <div class="warning"><strong>{{ selectedBatch.summary.conflicts }}</strong><span>конфликтов</span></div>
        <div><strong>{{ selectedBatch.summary.missing }}</strong><span>не найдено</span></div>
      </div>

      <div class="aa-workspace">
        <aside class="aa-products">
          <div class="aa-products-title">Товары</div>
          <button
            v-for="product in selectedBatch.products"
            :key="product.id"
            :class="['aa-product', { active: selectedProduct?.id === product.id }]"
            @click="openProduct(product.id)"
          >
            <span>
              <strong>{{ product.model }}</strong>
              <small>{{ product.name || "Без названия" }}</small>
            </span>
            <b :class="product.status">{{ product.counts.conflicts || product.counts.missing || "✓" }}</b>
          </button>
        </aside>

        <main v-if="selectedProduct" class="aa-product-work">
          <section class="aa-card aa-source-card">
            <div class="aa-product-title">
              <div>
                <span class="aa-step">Текущий товар</span>
                <h2>{{ selectedProduct.model }}</h2>
                <p>{{ selectedProduct.name }}</p>
              </div>
              <span :class="['aa-badge', selectedProduct.status === 'ready' ? 'success' : 'warning']">
                {{ selectedProduct.status === "ready" ? "Готов" : "Нужна проверка" }}
              </span>
            </div>

            <div class="aa-source-grid">
              <div class="aa-donor-picker">
                <div class="aa-section-title">
                  <span><strong>Доноры</strong><small>Отметьте нужные сайты</small></span>
                  <b>{{ selectedDonors.length }}</b>
                </div>
                <label v-for="donor in donors" :key="donor.id" class="aa-donor-check">
                  <input
                    type="checkbox"
                    :checked="selectedDonors.includes(donor.id)"
                    @change="toggleDonor(donor.id)"
                  >
                  <span><strong>{{ donor.name }}</strong><small>{{ donor.site_url }}</small></span>
                </label>
              </div>

              <div class="aa-priority-list">
                <div class="aa-section-title">
                  <span><strong>Порядок проверки</strong><small>Первая строка имеет наивысший приоритет</small></span>
                </div>
                <div v-if="selectedDonorRows.length">
                  <div v-for="(donor, index) in selectedDonorRows" :key="donor.id" class="aa-priority-row">
                    <b>{{ index + 1 }}</b>
                    <span>
                      <strong>{{ donor.name }}</strong>
                      <small>{{ index === 0 ? "Главный источник данных" : "Проверка и дополнение" }}</small>
                    </span>
                    <button :disabled="index === 0" @click="moveDonor(index, -1)">↑</button>
                    <button :disabled="index === selectedDonorRows.length - 1" @click="moveDonor(index, 1)">↓</button>
                  </div>
                </div>
                <div v-else class="aa-priority-empty">Выберите доноров слева. Ссылка на товар будет найдена по модели автоматически.</div>
                <div class="aa-inline-actions">
                  <button class="aa-primary" :disabled="busy === 'process' || !selectedDonors.length" @click="processDonors">
                    <UIcon name="i-lucide-wand-sparkles" /> Найти и проверить
                  </button>
                  <button class="aa-secondary" :disabled="busy === 'similar'" @click="useSimilar">Похожие товары</button>
                </div>
              </div>
            </div>

            <div v-if="selectedProduct.sources?.length" class="aa-source-results">
              <a
                v-for="source in selectedProduct.sources"
                :key="source.id"
                :href="source.url"
                target="_blank"
                rel="noopener"
                :class="['aa-source-result', source.status]"
              >
                <span><strong>{{ source.donor_name }}</strong><small>{{ source.message || source.role }}</small></span>
                <b>{{ source.status === "parsed" ? "Найдена" : "Нет данных" }}</b>
              </a>
            </div>
          </section>

          <section class="aa-card aa-attributes">
            <div class="aa-card-head">
              <div>
                <span class="aa-step">Проверка</span>
                <h2>Атрибуты товара</h2>
              </div>
              <span class="aa-muted">Заполненные значения защищены</span>
            </div>

            <div v-for="[group, values] in valuesByGroup" :key="group" class="aa-attribute-group">
              <h3>{{ group }}</h3>
              <article v-for="value in values" :key="value.id" :class="['aa-attribute', `is-${value.status}`]">
                <div class="aa-attribute-name">
                  <strong>{{ value.name }}</strong>
                  <small>{{ value.source || "Источник ещё не найден" }}</small>
                </div>
                <div class="aa-attribute-value">
                  <template v-if="value.current_value">
                    <strong>{{ value.current_value }}</strong>
                    <small>Исходное значение · не изменяется</small>
                  </template>
                  <template v-else-if="value.final_value">
                    <strong>{{ value.final_value }}</strong>
                    <small>{{ value.status === "dash" ? value.dash_reason : "Подтверждено" }}</small>
                  </template>
                  <template v-else-if="value.proposed_value">
                    <strong>{{ value.proposed_value }}</strong>
                    <small>{{ value.reason }}</small>
                  </template>
                  <template v-else>
                    <span class="aa-not-found">Не найдено</span>
                    <small>{{ value.reason || "Проверьте доноров или задайте значение вручную" }}</small>
                  </template>
                </div>
                <div class="aa-confidence">
                  <b v-if="value.confidence">{{ value.confidence }}%</b>
                  <span v-if="value.status === 'conflict'" class="aa-badge danger">Конфликт</span>
                  <span v-else-if="value.status === 'unknown'" class="aa-badge warning">Нет в справочнике</span>
                </div>
                <div class="aa-value-actions">
                  <button v-if="value.proposed_value && !value.final_value" class="accept" @click="valueAction(value, 'accept')">Принять</button>
                  <button v-if="value.proposed_value && !value.final_value" @click="valueAction(value, 'reject')">Отклонить</button>
                  <button v-if="!value.current_value && !value.final_value" @click="valueAction(value, 'dash')">Поставить «-»</button>
                </div>

                <div v-if="value.status === 'conflict'" class="aa-detail-line">
                  <span>Выберите вариант:</span>
                  <button
                    v-for="(candidate, index) in value.source_details.candidates || []"
                    :key="index"
                    @click="valueAction(value, 'accept', String(candidate.value || ''))"
                  >
                    {{ candidate.value }} · {{ candidate.source }}
                  </button>
                </div>
                <div v-for="(unknown, index) in value.source_details.unknown_values || []" :key="`unknown-${index}`" class="aa-detail-line">
                  <span>Новое значение: <strong>{{ unknown.value }}</strong></span>
                  <span v-if="unknown.suggestions?.length">Ближайшее: {{ unknown.suggestions.join(", ") }}</span>
                  <button @click="addUnknown(value, unknown)">Добавить в справочник</button>
                </div>
              </article>
            </div>
          </section>
        </main>
      </div>
    </template>
  </div>
</template>

<style src="../assets/css/attribute-assistant.css"></style>

