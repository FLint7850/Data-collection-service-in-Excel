<script setup lang="ts">
import { feedComparisonService } from "~/services/feed-comparison.service";
import type { FeedComparisonData, OwnSite, SupplierFeed } from "~/types/api";
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
    applyData(await feedComparisonService.saveOwnSite(site));
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
    applyData(await feedComparisonService.saveSupplier(supplier));
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
    applyData(await feedComparisonService.removeOwnSite(site.id));
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function removeSupplier(supplier: SupplierFeed) {
  if (!supplier.id) return;
  try {
    applyData(await feedComparisonService.removeSupplier(supplier.id));
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function start() {
  actionLoading.value = "start";
  try {
    const state = await feedComparisonService.start();
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
    applyData(await feedComparisonService.stop());
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

useProgressPolling(
  async () => {
    if (isActive.value) applyData(await feedComparisonService.get());
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

      <div class="comparison-grid">
        <UCard as="section" variant="outline" class="panel feed-column">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ЭТАЛОН</p>
              <h3>Фиды моих сайтов</h3>
              <p>Они также используются в мониторинге новинок и импорте файлов.</p>
            </div>
            <UButton
              color="neutral"
              variant="soft"
              icon="i-lucide-plus"
              :disabled="isActive"
              @click="addOwnSite"
            >
              Фид
            </UButton>
          </div>

          <div class="feed-list">
            <FeedEditorCard
              v-for="site in data.own_sites"
              :key="`own-${site.id}`"
              kind="own-site"
              :item="site"
              :disabled="isActive"
              :saving="savingKey === `own-${site.id}`"
              @save="saveOwnSite($event as OwnSite)"
              @remove="removeOwnSite($event as OwnSite)"
            />
            <FeedEditorCard
              v-for="(site, index) in pendingOwnSites"
              :key="`new-own-${index}`"
              kind="own-site"
              :item="site"
              :disabled="isActive"
              :saving="savingKey === `own-${index}`"
              @save="saveOwnSite($event as OwnSite, index)"
              @remove="pendingOwnSites.splice(index, 1)"
            />
          </div>

          <EmptyState
            v-if="!data.own_sites.length && !pendingOwnSites.length"
            icon="i-lucide-store"
            title="Нет фидов сайтов"
            description="Добавьте хотя бы один XML-фид своего магазина."
          >
            <UButton color="primary" variant="soft" icon="i-lucide-plus" @click="addOwnSite">Добавить</UButton>
          </EmptyState>
        </UCard>

        <UCard as="section" variant="outline" class="panel feed-column">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ИСТОЧНИКИ</p>
              <h3>Фиды поставщиков</h3>
              <p>Для каждого поставщика укажите точное имя XML-поля с моделью.</p>
            </div>
            <UButton
              color="neutral"
              variant="soft"
              icon="i-lucide-plus"
              :disabled="isActive"
              @click="addSupplier"
            >
              Поставщик
            </UButton>
          </div>

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

          <EmptyState
            v-if="!data.suppliers.length && !pendingSuppliers.length"
            icon="i-lucide-truck"
            title="Нет поставщиков"
            description="Добавьте XML-фид поставщика для сравнения."
          >
            <UButton color="primary" variant="soft" icon="i-lucide-plus" @click="addSupplier">Добавить</UButton>
          </EmptyState>
        </UCard>
      </div>

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
