<script setup lang="ts">
import {
  newsService,
  type MonitorPayload,
} from "~/services/news.service";
import type {
  ConnectionMethod,
  NewsMonitor,
  NewsMonitorSummary,
} from "~/types/api";
import { errorMessage } from "~/utils/format";
import { mergeProgressState } from "~/utils/progress-state";

const props = defineProps<{
  monitorId: string;
  connectionMethods: ConnectionMethod[];
  liveMonitors: NewsMonitorSummary[];
}>();

const emit = defineEmits<{
  close: [];
  changed: [monitors: NewsMonitor[]];
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
let lastSavedPayload: MonitorPayload | null = null;
let liveSyncPending = false;
let membershipSyncing = false;

const connectionOptions = computed(() =>
  props.connectionMethods.map((method) => ({ label: method.name, value: method.code })),
);
const activeUrls = computed(() =>
  (draft.value?.state.active_urls || []).filter(
    (url): url is string => Boolean(url?.trim()),
  ),
);
const selected = computed(() => monitors.value.find((item) => item.id === selectedId.value) || null);
const isActive = computed(() =>
  ["running", "queued", "pausing", "stopping"].includes(draft.value?.state.status || ""),
);
const canResume = computed(() => draft.value?.state.status === "partial");

function cloneMonitor(monitor: NewsMonitor): NewsMonitor {
  return JSON.parse(JSON.stringify(monitor)) as NewsMonitor;
}

function prepareMonitor(monitor: NewsMonitor): NewsMonitor {
  const next = cloneMonitor(monitor);
  next.extraction_rules = {
    ...next.extraction_rules,
    model_start_marker: next.extraction_rules.model_start_marker || "",
    model_end_marker: next.extraction_rules.model_end_marker || "",
  };
  next.selector_settings = {
    ...next.selector_settings,
    availability_exclusions: [...(next.selector_settings.availability_exclusions || [])],
  };
  return next;
}

function monitorPayload(monitor: NewsMonitor): MonitorPayload {
  return {
    brand: monitor.brand,
    site_url: monitor.site_url,
    start_urls: monitor.start_urls,
    enabled: monitor.enabled,
    schedule_type: monitor.schedule_type,
    scan_time: monitor.scan_time,
    weekday: monitor.weekday,
    next_run_at: monitor.next_run_at,
    thread_count: monitor.thread_count,
    connection_method: monitor.connection_method,
    auto_connection_fallback: monitor.auto_connection_fallback,
    exclusions: monitor.exclusions,
    product_url_filters: monitor.product_url_filters,
    product_url_exclusions: monitor.product_url_exclusions,
    extraction_rules: monitor.extraction_rules,
    selector_settings: monitor.selector_settings,
    primary_donor_id: selectedId.value,
  };
}

function changedMonitorPayload(current: MonitorPayload): MonitorPayload {
  if (!lastSavedPayload) return current;
  const changes: MonitorPayload = {};
  for (const key of Object.keys(current) as (keyof MonitorPayload)[]) {
    if (JSON.stringify(current[key]) !== JSON.stringify(lastSavedPayload[key])) {
      (changes as Record<string, unknown>)[key] = current[key];
    }
  }
  return changes;
}

function emitChanged() {
  emit("changed", monitors.value.map(cloneMonitor));
}

function setDraft(monitor: NewsMonitor) {
  const next = prepareMonitor(monitor);
  selectedId.value = monitor.id;
  draft.value = next;
  lastSavedPayload = JSON.parse(
    JSON.stringify({
      ...monitorPayload(next),
      primary_donor_id:
        next.primary_donor_id == null
          ? selectedId.value
          : String(next.primary_donor_id),
    }),
  ) as MonitorPayload;
}

async function mergeLiveMonitors(incoming: NewsMonitorSummary[]) {
  const currentBrandId = draft.value?.brand_id ?? monitors.value[0]?.brand_id;
  const currentGroup = draft.value?.group ?? monitors.value[0]?.group;
  const currentBrand = draft.value?.brand ?? monitors.value[0]?.brand;
  const brandIncoming = incoming.filter((monitor) =>
    currentBrandId != null
      ? String(monitor.brand_id ?? "") === String(currentBrandId)
      : monitor.group === currentGroup && monitor.brand === currentBrand,
  );
  if (!brandIncoming.length) {
    monitors.value = [];
    draft.value = null;
    lastSavedPayload = null;
    emit("close");
    return;
  }

  const incomingIds = new Set(brandIncoming.map((monitor) => String(monitor.id)));
  monitors.value = monitors.value
    .filter((monitor) => incomingIds.has(String(monitor.id)))
    .map((monitor) => {
      const live = brandIncoming.find(
        (item) => String(item.id) === String(monitor.id),
      );
      if (!live) return monitor;
      return {
        ...monitor,
        brand_id: live.brand_id,
        primary_donor_id: live.primary_donor_id,
        group: live.group,
        brand: live.brand,
        site_url: live.site_url,
        enabled: live.enabled,
        state: mergeProgressState(monitor.state, live.state),
      };
    });

  const missingIds = brandIncoming
    .map((monitor) => String(monitor.id))
    .filter((id) => !monitors.value.some((monitor) => String(monitor.id) === id));
  if (missingIds.length && !membershipSyncing) {
    membershipSyncing = true;
    try {
      const response = await newsService.getMonitor(missingIds[0]!);
      const latestIds = new Set(
        props.liveMonitors
          .filter((monitor) =>
            currentBrandId != null
              ? String(monitor.brand_id ?? "") === String(currentBrandId)
              : monitor.group === currentGroup && monitor.brand === currentBrand,
          )
          .map((monitor) => String(monitor.id)),
      );
      for (const monitor of response.monitors) {
        if (
          latestIds.has(String(monitor.id)) &&
          !monitors.value.some((current) => String(current.id) === String(monitor.id))
        ) {
          monitors.value.push(prepareMonitor(monitor));
        }
      }
    } catch (caught) {
      error.value = errorMessage(caught, "Не удалось обновить список доноров");
    } finally {
      membershipSyncing = false;
    }
  }

  const live = brandIncoming.find(
    (item) => String(item.id) === String(selectedId.value),
  );
  if (!live) {
    const next = monitors.value[0];
    if (next) setDraft(next);
    else {
      draft.value = null;
      lastSavedPayload = null;
      emit("close");
    }
    return;
  }
  if (draft.value && String(draft.value.id) === String(live.id)) {
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
    monitors.value = response.monitors;
    const monitor = monitors.value.find(
      (item) => String(item.id) === String(selectedId.value || props.monitorId),
    ) || monitors.value[0];
    if (!monitor) throw new Error("Донор не найден");
    setDraft(monitor);
  } catch (caught) {
    const failure = caught as {
      status?: number;
      statusCode?: number;
      response?: { status?: number };
    };
    const status = Number(
      failure.statusCode || failure.status || failure.response?.status || 0,
    );
    if (status === 404) emit("close");
    else error.value = errorMessage(caught, "Не удалось открыть настройки донора");
  } finally {
    loading.value = false;
    if (liveSyncPending && draft.value) {
      liveSyncPending = false;
      void mergeLiveMonitors(props.liveMonitors);
    }
  }
}

watch(selectedId, (id, previous) => {
  if (!id || id === previous) return;
  const monitor = monitors.value.find((item) => item.id === id);
  if (monitor) setDraft(monitor);
});

watch(
  () => props.liveMonitors,
  (incoming) => {
    if (loading.value || !draft.value) {
      liveSyncPending = true;
      return;
    }
    void mergeLiveMonitors(incoming);
  },
);

async function save(showToast = true) {
  if (!draft.value) return null;
  const current = monitorPayload(draft.value);
  const changes = changedMonitorPayload(current);
  if (!Object.keys(changes).length) return draft.value;
  saving.value = true;
  try {
    const response = await newsService.updateMonitor(draft.value.id, changes);
    const index = monitors.value.findIndex((item) => item.id === response.monitor.id);
    if (index >= 0) monitors.value[index] = response.monitor;
    setDraft(response.monitor);
    emitChanged();
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
    const runMonitorId = String(draft.value.state.run_monitor_id || "");
    const actionMonitorId = action === "scan" || action === "reset-visual"
      ? draft.value.id
      : monitors.value.find((item) => String(item.id) === runMonitorId)?.id || draft.value.id;
    const response = await newsService.action(actionMonitorId, action);
    const index = monitors.value.findIndex((item) => item.id === response.monitor.id);
    const currentMonitor = monitors.value[index];
    if (currentMonitor) {
      currentMonitor.state = mergeProgressState(
        currentMonitor.state,
        response.monitor.state,
      );
    }
    draft.value.state = mergeProgressState(draft.value.state, response.monitor.state);
    emitChanged();
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
    const response = await newsService.updateMonitor(draft.value.id, {
      primary_donor_id: value,
    });
    const index = monitors.value.findIndex((item) => item.id === response.monitor.id);
    if (index >= 0) monitors.value[index] = response.monitor;
    emitChanged();
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
    emitChanged();
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
    monitors.value = response.monitors;
    confirmDelete.value = false;
    const next = monitors.value[0];
    if (next) setDraft(next);
    else emit("close");
    if (monitors.value.length) emitChanged();
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
      </div>
    </template>
    <template #actions>
      <NewsRunActions
        v-if="draft"
        v-model:enabled="draft.enabled"
        :state="draft.state"
        :monitor-id="draft.id"
        :action-loading="actionLoading"
        :active="isActive"
        :can-resume="canResume"
        @action="runAction"
      />
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
            <NewsDonorSelector
              v-model:selected-id="selectedId"
              v-model:add-url="addDonorUrl"
              :monitors="monitors"
              :adding="addingDonor"
              @add="addDonor"
            />

            <NewsDonorSettingsPanel v-model="draft" :connection-options="connectionOptions" />

            <NewsRulesPanel v-model="draft" />
          </div>

          <aside class="news-progress-column">
            <ProgressPanel
              :state="draft.state"
              :show-status="false"
              :show-active-urls="false"
            />
          </aside>
        </div>

        <div v-if="activeUrls.length" class="active-url-list news-modal-active-urls">
          <div class="active-url-list-title">
            <span>Сейчас собираются</span>
            <UBadge color="primary" variant="subtle">{{ activeUrls.length }}</UBadge>
          </div>
          <div v-for="url in activeUrls" :key="url" class="active-url-item">
            <span class="tiny-dot" />
            <span>{{ url }}</span>
          </div>
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
