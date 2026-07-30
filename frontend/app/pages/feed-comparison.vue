<script setup lang="ts">
import { feedComparisonService } from "~/services/feed-comparison.service";
import type {
  FeedComparisonData,
  FeedComparisonProgress,
  OwnSite,
  SupplierFeed,
} from "~/types/api";
import { errorMessage } from "~/utils/format";
import { mergeProgressState } from "~/utils/progress-state";

definePageMeta({
  title: "Сравнение с фидами",
  eyebrow: "ПОСТАВЩИКИ · САЙТЫ",
});

const toast = useToast();
const data = ref<FeedComparisonData | null>(null);
const loading = ref(true);
const savingKey = ref("");
const actionLoading = ref("");
const error = ref("");
const pendingOwnSites = ref<OwnSite[]>([]);
const pendingSuppliers = ref<SupplierFeed[]>([]);

const isActive = computed(() =>
  ["running", "queued", "stopping"].includes(data.value?.state.status || ""),
);

function applyData(value: FeedComparisonData) {
  data.value = {
    ...(data.value || value),
    ...value,
    state: mergeProgressState(data.value?.state, value.state),
  };
}

function applyProgress(value: FeedComparisonProgress) {
  if (!data.value) return;
  data.value.state = mergeProgressState(data.value.state, value.state);
  data.value.result_ready = value.result_ready;
  data.value.result_filename = value.result_filename;
}

async function load() {
  try {
    applyData(await feedComparisonService.get());
  } catch (caught) {
    error.value = errorMessage(caught, "Не удалось загрузить фиды");
  } finally {
    loading.value = false;
  }
}

function addOwnSite() {
  pendingOwnSites.value.push({
    name: "",
    feed_url: "",
    feed_generate_url: "",
  });
}

function addSupplier() {
  pendingSuppliers.value.push({
    name: "",
    feed_url: "",
    model_field: "",
    exclusions: "",
    replace_rules: "",
  });
}

async function saveOwnSite(site: OwnSite, pendingIndex?: number) {
  savingKey.value = `own-${site.id || pendingIndex}`;
  try {
    const response = await feedComparisonService.saveOwnSite(site);
    const index = data.value?.own_sites.findIndex(
      (item) => item.id === response.own_site.id,
    ) ?? -1;
    if (data.value) {
      if (index >= 0) data.value.own_sites[index] = response.own_site;
      else data.value.own_sites.push(response.own_site);
    }
    if (pendingIndex != null) pendingOwnSites.value.splice(pendingIndex, 1);
    toast.add({ title: "Фид сайта сохранён", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    savingKey.value = "";
  }
}

async function saveSupplier(supplier: SupplierFeed, pendingIndex?: number) {
  savingKey.value = `supplier-${supplier.id || pendingIndex}`;
  try {
    const response = await feedComparisonService.saveSupplier(supplier);
    const index = data.value?.suppliers.findIndex(
      (item) => item.id === response.supplier.id,
    ) ?? -1;
    if (data.value) {
      if (index >= 0) data.value.suppliers[index] = response.supplier;
      else data.value.suppliers.push(response.supplier);
    }
    if (pendingIndex != null) pendingSuppliers.value.splice(pendingIndex, 1);
    toast.add({ title: "Фид поставщика сохранён", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    savingKey.value = "";
  }
}

async function removeOwnSite(site: OwnSite) {
  if (!site.id) return;
  try {
    const response = await feedComparisonService.removeOwnSite(site.id);
    if (data.value) {
      data.value.own_sites = data.value.own_sites.filter(
        (item) => item.id !== response.id,
      );
    }
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function removeSupplier(supplier: SupplierFeed) {
  if (!supplier.id) return;
  try {
    const response = await feedComparisonService.removeSupplier(supplier.id);
    if (data.value) {
      data.value.suppliers = data.value.suppliers.filter(
        (item) => item.id !== response.id,
      );
    }
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function start() {
  actionLoading.value = "start";
  try {
    applyProgress(await feedComparisonService.start());
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

async function stop() {
  actionLoading.value = "stop";
  try {
    applyProgress(await feedComparisonService.stop());
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

useProgressPolling(
  async () => {
    if (isActive.value) applyProgress(await feedComparisonService.getProgress());
  },
  computed(() => isActive.value),
);

onMounted(load);
</script>

<template>
  <div>
    <SectionHeader
      eyebrow="СВЕРКА АССОРТИМЕНТА"
      title="Сравнение с фидами"
      description="Покажите, какие модели поставщиков ещё не представлены на ваших сайтах."
    >
      <template #actions>
        <UButton
          v-if="data?.result_ready"
          to="/api/feed-comparison/download"
          external
          color="primary"
          variant="soft"
          icon="i-lucide-download"
        >
          Скачать XLSX
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
      <span class="loading-logo"><UIcon name="i-lucide-git-compare-arrows" /></span>
      <p>Загружаем фиды…</p>
    </div>

    <template v-else-if="data">
      <div class="metrics-grid">
        <MetricCard label="Моих фидов" :value="data.own_sites.length" icon="i-lucide-store" tone="mint" />
        <MetricCard label="Поставщиков" :value="data.suppliers.length" icon="i-lucide-truck" tone="blue" />
        <MetricCard label="Сравнено моделей" :value="data.state.processed_rows" icon="i-lucide-scan-search" tone="amber" />
        <MetricCard label="Не найдено" :value="data.state.missing_rows" icon="i-lucide-package-x" tone="red" />
      </div>

      <UCard as="section" variant="outline" class="panel feed-column">
        <UCollapsible>
          <template #default="{ open }">
            <div class="panel-header">
              <div>
                <p class="eyebrow">ИСТОЧНИКИ</p>
                <h3>Фиды поставщиков</h3>
                <p>Для каждого поставщика укажите точное имя XML-поля с моделью.</p>
              </div>
              <div class="flex flex-col gap-3">
                <UIcon
                    name="i-lucide-chevron-down"
                    class="settings-details-chevron"
                    :class="{ open }"
                />
                <UButton
                    color="neutral"
                    variant="soft"
                    icon="i-lucide-plus"
                    :disabled="isActive"
                    @click.stop="addSupplier"
                >
                  Поставщик
                </UButton>
              </div>
            </div>
          </template>
          <template #content>
            <div class="feed-list">
              <FeedEditorCard
                  v-for="supplier in data.suppliers"
                  :key="`supplier-${supplier.id}`"
                  kind="supplier"
                  :item="supplier"
                  :disabled="isActive"
                  :saving="savingKey === `supplier-${supplier.id}`"
                  @save="saveSupplier($event as SupplierFeed)"
                  @remove="removeSupplier($event as SupplierFeed)"
              />
              <FeedEditorCard
                  v-for="(supplier, index) in pendingSuppliers"
                  :key="`new-supplier-${index}`"
                  kind="supplier"
                  :item="supplier"
                  :disabled="isActive"
                  :saving="savingKey === `supplier-${index}`"
                  @save="saveSupplier($event as SupplierFeed, index)"
                  @remove="pendingSuppliers.splice(index, 1)"
              />
            </div>
          </template>
        </UCollapsible>

        <EmptyState
          v-if="!data.suppliers.length && !pendingSuppliers.length"
          icon="i-lucide-truck"
          title="Нет поставщиков"
          description="Добавьте XML-фид поставщика для сравнения."
        >
          <UButton color="primary" variant="soft" icon="i-lucide-plus" @click="addSupplier">Добавить</UButton>
        </EmptyState>
      </UCard>


      <UCard as="section" variant="outline" class="panel comparison-progress-panel">
        <div class="panel-header">
          <div>
            <p class="eyebrow">РЕЗУЛЬТАТ</p>
            <h3>Сравнение фидов</h3>
            <p>В итоговом XLSX каждый поставщик будет на отдельном листе.</p>
          </div>
          <StatusBadge :status="data.state.status" />
        </div>

        <div class="comparison-progress-grid">
          <div class="comparison-progress-main">
            <div class="progress-value-row">
              <strong>{{ data.state.percent }}%</strong>
              <span>{{ data.state.stage || "Готово к запуску" }}</span>
            </div>
            <UProgress :model-value="data.state.percent" color="primary" size="sm" />
            <p class="current-supplier">
              <UIcon name="i-lucide-truck" />
              {{ data.state.current_supplier || "Текущий поставщик появится после запуска" }}
            </p>
          </div>

          <div class="comparison-progress-metrics">
            <div>
              <strong>{{ data.state.suppliers_done }} / {{ data.state.suppliers_total }}</strong>
              <span>поставщиков</span>
            </div>
            <div>
              <strong>{{ data.state.processed_rows }}</strong>
              <span>моделей</span>
            </div>
            <div>
              <strong>{{ data.state.missing_rows }}</strong>
              <span>не найдено</span>
            </div>
          </div>
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
            v-if="!isActive"
            color="primary"
            icon="i-lucide-play"
            :loading="actionLoading === 'start'"
            :disabled="!data.own_sites.length || !data.suppliers.length"
            @click="start"
          >
            Запустить сравнение
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
            to="/api/feed-comparison/download"
            external
            color="primary"
            variant="soft"
            icon="i-lucide-download"
          >
            Скачать XLSX
          </UButton>
        </div>
      </UCard>
    </template>
  </div>
</template>
