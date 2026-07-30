<script setup lang="ts">
import { newsService } from "~/services/news.service";
import type { ConnectionMethod, NewsMonitor } from "~/types/api";
import { errorMessage, hostFromUrl } from "~/utils/format";
import { mergeProgressState } from "~/utils/progress-state";

const props = defineProps<{
  monitorId: string;
  connectionMethods: ConnectionMethod[];
  liveMonitors: NewsMonitor[];
}>();

const emit = defineEmits<{
  close: [];
  changed: [];
}>();

const toast = useToast();
const loading = ref(true);
const saving = ref(false);
const actionLoading = ref("");
const monitors = ref<NewsMonitor[]>([]);
const selectedId = ref(props.monitorId);
const draft = ref<NewsMonitor | null>(null);
const addDonorUrl = ref("");
const addingDonor = ref(false);
const confirmDelete = ref(false);
const error = ref("");

const connectionOptions = computed(() =>
  props.connectionMethods.map((method) => ({ label: method.name, value: method.code })),
);
const selected = computed(() => monitors.value.find((item) => item.id === selectedId.value) || null);
const isActive = computed(() =>
  ["running", "queued", "pausing", "stopping"].includes(draft.value?.state.status || ""),
);
const canResume = computed(() => draft.value?.state.status === "partial");

function setDraft(monitor: NewsMonitor) {
  const next = structuredClone(toRaw(monitor));
  next.extraction_rules = {
    ...next.extraction_rules,
    model_start_marker: next.extraction_rules.model_start_marker || "",
    model_end_marker: next.extraction_rules.model_end_marker || "",
  };
  next.selector_settings = {
    ...next.selector_settings,
    availability_exclusions: [...(next.selector_settings.availability_exclusions || [])],
  };
  selectedId.value = monitor.id;
  draft.value = next;
}

function mergeLiveState(incoming: NewsMonitor[]) {
  if (!incoming.length) return;
  monitors.value = monitors.value.map((monitor) => {
    const live = incoming.find((item) => String(item.id) === String(monitor.id));
    return live
      ? { ...monitor, state: mergeProgressState(monitor.state, live.state) }
      : monitor;
  });
  const live = incoming.find((item) => String(item.id) === String(selectedId.value));
  if (live && draft.value && String(draft.value.id) === String(live.id)) {
    draft.value.state = mergeProgressState(draft.value.state, live.state);
  }
}

function handleModalOpen(open: boolean) {
  if (!open) emit("close");
}

async function load() {
  loading.value = true;
  error.value = "";
  draft.value = null;
  try {
    const response = await newsService.getMonitor(selectedId.value || props.monitorId);
    monitors.value = response.brand_monitors.length
      ? response.brand_monitors
      : [response.monitor];
    const monitor =
      monitors.value.find((item) => item.id === selectedId.value) ||
      response.monitor;
    setDraft(monitor);
  } catch (caught) {
    error.value = errorMessage(caught, "Не удалось открыть настройки донора");
  } finally {
    loading.value = false;
  }
}

watch(selectedId, (id, previous) => {
  if (!id || id === previous) return;
  const monitor = monitors.value.find((item) => item.id === id);
  if (monitor) setDraft(monitor);
});

watch(
  () => props.liveMonitors,
  (incoming) => mergeLiveState(incoming),
);

async function save(showToast = true) {
  if (!draft.value) return null;
  saving.value = true;
  try {
    const response = await newsService.updateMonitor(draft.value.id, {
      brand: draft.value.brand,
      site_url: draft.value.site_url,
      start_urls: draft.value.start_urls,
      enabled: draft.value.enabled,
      schedule_type: draft.value.schedule_type,
      scan_time: draft.value.scan_time,
      weekday: draft.value.weekday,
      next_run_at: draft.value.next_run_at,
      thread_count: draft.value.thread_count,
      connection_method: draft.value.connection_method,
      auto_connection_fallback: draft.value.auto_connection_fallback,
      exclusions: draft.value.exclusions,
      product_url_filters: draft.value.product_url_filters,
      product_url_exclusions: draft.value.product_url_exclusions,
      extraction_rules: draft.value.extraction_rules,
      selector_settings: draft.value.selector_settings,
      primary_donor_id: selectedId.value,
    });
    const index = monitors.value.findIndex((item) => item.id === response.monitor.id);
    if (index >= 0) monitors.value[index] = response.monitor;
    setDraft(response.monitor);
    emit("changed");
    if (showToast) toast.add({ title: "Настройки сохранены", color: "success" });
    return response.monitor;
  } catch (caught) {
    error.value = errorMessage(caught);
    return null;
  } finally {
    saving.value = false;
  }
}

async function runAction(action: "scan" | "pause" | "resume" | "stop" | "reset-visual") {
  if (!draft.value) return;
  actionLoading.value = action;
  error.value = "";
  try {
    if (action === "scan") {
      const saved = await save(false);
      if (!saved) return;
    }
    const response = await newsService.action(draft.value.id, action);
    const index = monitors.value.findIndex((item) => item.id === response.monitor.id);
    if (index >= 0) monitors.value[index] = { ...monitors.value[index], ...response.monitor };
    draft.value.state = { ...draft.value.state, ...response.monitor.state };
    emit("changed");
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

async function choosePrimary(value: string | number) {
  if (!draft.value) return;
  selectedId.value = String(value);
  try {
    await newsService.updateMonitor(draft.value.id, { primary_donor_id: value });
    emit("changed");
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function addDonor() {
  if (!draft.value || !addDonorUrl.value.trim()) return;
  addingDonor.value = true;
  try {
    await save(false);
    const response = await newsService.createMonitor({
      group: draft.value.group,
      brand: draft.value.brand,
      site_url: addDonorUrl.value.trim(),
    });
    monitors.value.push(response.monitor);
    addDonorUrl.value = "";
    setDraft(response.monitor);
    emit("changed");
    toast.add({ title: "Донор добавлен", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    addingDonor.value = false;
  }
}

async function deleteDonor() {
  if (!draft.value) return;
  try {
    const response = await newsService.removeMonitor(draft.value.id);
    monitors.value = response.monitors.filter(
      (item) => item.group === draft.value?.group && item.brand === draft.value?.brand,
    );
    confirmDelete.value = false;
    const next = monitors.value[0];
    if (next) setDraft(next);
    else emit("close");
    emit("changed");
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

onMounted(load);
</script>

<template>
  <UModal
    :open="true"
    :description="draft ? `${draft.group} · ${monitors.length} ${monitors.length === 1 ? 'донор' : 'донора'}` : 'Параметры мониторинга бренда'"
    :scrollable="false"
    :close="false"
    :ui="{
      content: 'news-monitor-panel max-w-[1320px]',
      description: 'mt-0',
      body: 'p-0',
      footer: 'news-modal-footer',
    }"
    @update:open="handleModalOpen"
  >
    <template #title>
      <div class="flex gap-3 items-center">
        {{draft?.brand || 'Настройки донора'}}
        <div v-if="draft">
          <USwitch v-model="draft.enabled" />
        </div>
      </div>
    </template>
    <template #actions>
      <div v-if="draft" class="news-run-actions flex-1 justify-between">
        <StatusBadge :status="draft.state.status" context="news" size="xl" />
        <div class="flex gap-1">
          <UButton
              v-if="draft.state.csv_ready"
              :to="`/api/news/monitors/${draft.id}/download`"
              external
              color="primary"
              variant="soft"
              icon="i-lucide-download"
          >
            Скачать CSV
          </UButton>
          <UButton
              v-if="!isActive && !canResume"
              icon="i-lucide-radar"
              :loading="actionLoading === 'scan'"
              @click="runAction('scan')"
          >
            Проверить новинки
          </UButton>
          <UButton
              v-if="canResume"
              color="primary"
              icon="i-lucide-play"
              :loading="actionLoading === 'resume'"
              @click="runAction('resume')"
          >
            Продолжить
          </UButton>
          <UButton
              v-if="['running', 'queued'].includes(draft.state.status)"
              color="warning"
              variant="soft"
              icon="i-lucide-pause"
              :loading="actionLoading === 'pause'"
              @click="runAction('pause')"
          >
            Пауза
          </UButton>
          <UButton
              v-if="isActive"
              color="error"
              variant="soft"
              icon="i-lucide-square"
              :loading="actionLoading === 'stop'"
              @click="runAction('stop')"
          >
            Стоп
          </UButton>
          <UButton
              v-if="!isActive"
              color="neutral"
              variant="ghost"
              icon="i-lucide-rotate-ccw"
              @click="runAction('reset-visual')"
          >
            Сбросить
          </UButton>
        </div>
      </div>
    </template>

    <template #body>
      <div v-if="loading" class="loading-state modal-loading">
        <UIcon name="i-lucide-loader-circle" class="spin" />
        <p>Загружаем настройки…</p>
      </div>

      <div v-else-if="!draft" class="modal-error-state">
        <UIcon name="i-lucide-circle-alert" />
        <h3>Не удалось открыть настройки</h3>
        <p>{{ error || "Данные донора не найдены." }}</p>
        <div class="modal-actions">
          <UButton color="primary" icon="i-lucide-refresh-cw" @click="load">
            Повторить
          </UButton>
          <UButton color="neutral" variant="soft" @click="emit('close')">
            Закрыть
          </UButton>
        </div>
      </div>

      <div v-else class="news-modal-body">
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-triangle-alert"
          :description="error"
          close
          @update:open="error = ''"
        />

        <div class="news-modal-grid">
          <div class="news-settings-column">
            <UCard as="section" variant="outline" class="panel">
              <div class="panel-header">
                <div>
                  <p class="eyebrow">ДОНОРЫ</p>
                  <h2><strong>Добавить сайт</strong></h2>
                </div>
              </div>
              <div class="add-donor-form">
                <UInput v-model="addDonorUrl" placeholder="https://supplier.ru" class="w-full" />
                <UButton
                    color="neutral"
                    variant="soft"
                    icon="i-lucide-plus"
                    :loading="addingDonor"
                    :disabled="!addDonorUrl.trim()"
                    @click="addDonor"
                >
                  Добавить
                </UButton>
              </div>
              <div class="donor-mini-list">
                <button
                    v-for="monitor in monitors"
                    :key="monitor.id"
                    type="button"
                    :class="{ active: monitor.id === selectedId }"
                    @click="selectedId = monitor.id"
                >
                  <span class="tiny-dot" />
                  <span>
                    <strong>{{ hostFromUrl(monitor.site_url || monitor.start_urls?.[0]) }}</strong>
                    <small>{{ monitor.start_urls.length }} стартовых URL</small>
                  </span>
                </button>
              </div>
            </UCard>

            <UCard as="section" variant="outline" class="panel">
              <div class="panel-header">
                <div>
                  <p class="eyebrow">ОСНОВНОЕ</p>
                  <h2><strong>Донор и расписание</strong></h2>
                </div>
              </div>

              <div class="form-grid">
                <UFormField label="Бренд">
                  <UInput v-model="draft.brand" class="w-full" />
                </UFormField>
                <UFormField label="Сайт донора">
                  <UInput v-model="draft.site_url" placeholder="https://example.ru" class="w-full" />
                </UFormField>
                <UFormField label="Расписание">
                  <USelect
                    v-model="draft.schedule_type"
                    :items="[
                      { label: 'Каждый день', value: 'daily' },
                      { label: 'Раз в неделю', value: 'weekly' },
                      { label: 'Один раз', value: 'once' },
                    ]"
                    class="w-full"
                  />
                </UFormField>
                <UFormField label="Время">
                  <UInput v-model="draft.scan_time" type="time" class="w-full" />
                </UFormField>
                <UFormField v-if="draft.schedule_type === 'weekly'" label="День недели">
                  <USelect
                    v-model="draft.weekday"
                    :items="[
                      { label: 'Понедельник', value: 0 },
                      { label: 'Вторник', value: 1 },
                      { label: 'Среда', value: 2 },
                      { label: 'Четверг', value: 3 },
                      { label: 'Пятница', value: 4 },
                      { label: 'Суббота', value: 5 },
                      { label: 'Воскресенье', value: 6 },
                    ]"
                    class="w-full"
                  />
                </UFormField>
                <UFormField v-if="draft.schedule_type === 'once'" label="Дата запуска">
                  <UInput v-model="draft.next_run_at" type="datetime-local" class="w-full" />
                </UFormField>
                <UFormField label="Потоки">
                  <UInput v-model.number="draft.thread_count" type="number" :min="1" :max="16" class="w-full" />
                </UFormField>
                <UFormField label="Подключение">
                  <template #label>
                    <div class="flex gap-3">
                      Подключение
                      <USwitch v-model="draft.auto_connection_fallback" />
                      <span>
                      <strong>Авто</strong>
                    </span>
                    </div>

                  </template>
                  <USelect v-model="draft.connection_method" :items="connectionOptions" class="w-full" />
                </UFormField>
                <UFormField label="Стартовые URL" class="field-span-2">
                  <UTextarea
                    :model-value="draft.start_urls.join('\n')"
                    :rows="5"
                    class="w-full"
                    placeholder="По одной ссылке на строку"
                    @update:model-value="draft.start_urls = String($event).split(/\r?\n/).map((item) => item.trim()).filter(Boolean)"
                  />
                </UFormField>
              </div>

            </UCard>

            <UCard as="section" variant="outline" class="panel settings-stack">
              <div class="panel-header">
                <div>
                  <p class="eyebrow">ФИЛЬТРЫ</p>
                  <h2><strong>Правила обхода</strong></h2>
                </div>
              </div>
              <SettingsCollapsible class="mt-3">
                <template #label>
                  Исключения разделов
                  <UBadge color="neutral" variant="subtle">{{ draft.exclusions.length }}</UBadge>
                </template>
                <PatternEditor
                  :model-value="draft.exclusions"
                  placeholder="/catalog/sale/"
                  @add="draft.exclusions.push($event)"
                  @remove="draft.exclusions.splice($event, 1)"
                />
              </SettingsCollapsible>
              <SettingsCollapsible>
                <template #label>
                  Фильтр товарных URL
                  <UBadge color="neutral" variant="subtle">{{ draft.product_url_filters.length }}</UBadge>
                </template>
                <PatternEditor
                  :model-value="draft.product_url_filters"
                  placeholder="-model-"
                  @add="draft.product_url_filters.push($event)"
                  @remove="draft.product_url_filters.splice($event, 1)"
                />
              </SettingsCollapsible>
              <SettingsCollapsible>
                <template #label>
                  Исключения товарных URL
                  <UBadge color="neutral" variant="subtle">{{ draft.product_url_exclusions.length }}</UBadge>
                </template>
                <PatternEditor
                  :model-value="draft.product_url_exclusions"
                  placeholder="/recommend"
                  @add="draft.product_url_exclusions.push($event)"
                  @remove="draft.product_url_exclusions.splice($event, 1)"
                />
              </SettingsCollapsible>
              <SettingsCollapsible content-class="form-grid">
                <template #label>Селекторы и правила модели</template>
                <UFormField label="Селектор названия">
                  <UInput v-model="draft.selector_settings.name_selector" placeholder="h1" class="w-full" />
                </UFormField>
                <UFormField label="Селектор наличия">
                  <UInput v-model="draft.selector_settings.availability_selector" placeholder=".stock" class="w-full" />
                </UFormField>
                <UFormField label="Карточка товара">
                  <UInput v-model="draft.extraction_rules.product_card_selector" placeholder=".product-card" class="w-full" />
                </UFormField>
                <UFormField label="Ссылка товара">
                  <UInput v-model="draft.extraction_rules.product_url_selector" placeholder="a[href]" class="w-full" />
                </UFormField>
                <UFormField label="Селектор модели">
                  <UInput v-model="draft.extraction_rules.model_selector" placeholder=".model" class="w-full" />
                </UFormField>
                <UFormField label="Селектор цены">
                  <UInput v-model="draft.extraction_rules.price_selector" placeholder=".price" class="w-full" />
                </UFormField>
                <UFormField label="Начало парсинга модели" class="field-span-2">
                  <UInput
                    v-model="draft.extraction_rules.model_start_marker"
                    placeholder="<h1 class=&quot;detail__title&quot;>"
                    class="w-full"
                  />
                </UFormField>
                <UFormField label="Конец парсинга модели" class="field-span-2">
                  <UInput
                    v-model="draft.extraction_rules.model_end_marker"
                    placeholder="</h1>"
                    class="w-full"
                  />
                </UFormField>
                <UFormField label="Правила замены" class="field-span-2">
                  <UTextarea v-model="draft.extraction_rules.model_replace_rules" :rows="4" class="w-full code-input" />
                </UFormField>
              </SettingsCollapsible>
              <SettingsCollapsible>
                <template #label>
                  Исключения по статусу
                  <UBadge color="neutral" variant="subtle">
                    {{ draft.selector_settings.availability_exclusions?.length || 0 }}
                  </UBadge>
                </template>
                <UFormField
                  label="Статусы, при которых товар не считается новинкой"
                  description="По одному фрагменту статуса на строку."
                >
                  <UTextarea
                    :model-value="(draft.selector_settings.availability_exclusions || []).join('\n')"
                    :rows="4"
                    class="w-full"
                    placeholder="Снят с производства&#10;Нет в наличии"
                    @update:model-value="draft.selector_settings.availability_exclusions = String($event).split(/\r?\n/).map((item) => item.trim()).filter(Boolean)"
                  />
                </UFormField>
              </SettingsCollapsible>
            </UCard>
          </div>

          <aside class="news-progress-column">
            <ProgressPanel :state="draft.state" :show-status="false" />
          </aside>
        </div>
      </div>
    </template>

    <template v-if="draft" #footer>
      <UButton
        color="error"
        variant="ghost"
        icon="i-lucide-trash-2"
        :disabled="monitors.length <= 1 || isActive"
        @click="confirmDelete = true"
      >
        Удалить донора
      </UButton>
      <span class="modal-footer-spacer" />
      <UButton color="neutral" variant="soft" @click="emit('close')">Закрыть</UButton>
      <UButton color="primary" icon="i-lucide-save" :loading="saving" @click="save()">
        Сохранить
      </UButton>
    </template>
  </UModal>

  <UModal
    v-model:open="confirmDelete"
    title="Удалить донора?"
    description="Настройки и результаты выбранного сайта-донора будут удалены."
    :ui="{ content: 'max-w-md' }"
  >
    <template #footer>
      <UButton color="neutral" variant="soft" @click="confirmDelete = false">Отмена</UButton>
      <UButton color="error" @click="deleteDonor">Удалить</UButton>
    </template>
  </UModal>
</template>
