<script setup lang="ts">
import { newsService } from "~/services/news.service";
import type {
  NewsBrandSearchResult,
  NewsMonitor,
  NewsMonitorSummary,
  NewsSummaryState,
  ProgressPayload,
} from "~/types/api";
import { errorMessage } from "~/utils/format";
import { mergeProgressState } from "~/utils/progress-state";

const props = withDefaults(defineProps<{ brandId?: string }>(), { brandId: "" });
const toast = useToast();
const route = useRoute();
const {
  data,
  progressCursor,
  loading,
  loaded,
  load,
  mergeProgress,
  upsertMonitor,
} = useNews();
const modalOpen = ref(false);
const selectedMonitorId = ref("");
const createOpen = ref(false);
const createGroup = ref("Маржа");
const createBrand = ref("");
const creating = ref(false);
const deletingKey = ref("");
const deleteOpen = ref(false);
const pageError = ref("");

interface BrandGroup {
  key: string;
  group: string;
  brand: string;
  brandId?: number;
  monitors: NewsMonitorSummary[];
  state: NewsSummaryState;
}

function aggregateState(monitors: NewsMonitorSummary[]): NewsSummaryState {
  const active =
    monitors.find((item) =>
      ["running", "queued", "pausing", "stopping"].includes(item.state?.status),
    ) ||
    monitors.find((item) => item.state?.status === "partial") ||
    monitors[0];
  if (!active) {
    return {
      status: "idle",
      percent: 0,
      currenturl: "",
      totalprocessed: 0,
      processed_products: 0,
      found_products: 0,
      error: "",
      elapsed_seconds: 0,
    };
  }
  return {
    ...active.state,
    new_count: Math.max(...monitors.map((item) => Number(item.state?.new_count || 0))),
    found_products: Math.max(...monitors.map((item) => Number(item.state?.found_products || 0))),
    failed_pages: monitors.reduce(
      (total, item) => total + Number(item.state?.failed_pages || 0),
      0,
    ),
  };
}

const brands = computed<BrandGroup[]>(() => {
  const map = new Map<string, NewsMonitorSummary[]>();
  for (const monitor of data.value?.monitors || []) {
    const key = `${monitor.group || "Без группы"}::${monitor.brand || "Без бренда"}`;
    const list = map.get(key) || [];
    list.push(monitor);
    map.set(key, list);
  }
  return [...map.entries()]
    .map(([key, monitors]) => ({
      key,
      group: monitors[0]?.group || "Без группы",
      brand: monitors[0]?.brand || "Без бренда",
      brandId: monitors[0]?.brand_id,
      monitors,
      state: aggregateState(monitors),
    }))
    .sort((left, right) =>
      `${left.group}-${left.brand}`.localeCompare(`${right.group}-${right.brand}`, "ru"),
    );
});

const groupedBrands = computed(() => {
  const map = new Map<string, BrandGroup[]>();
  for (const brand of brands.value) {
    const list = map.get(brand.group) || [];
    list.push(brand);
    map.set(brand.group, list);
  }
  return [...map.entries()].map(([group, items]) => ({ group, items }));
});

const totals = computed(() => ({
  brands: brands.value.length,
  donors: data.value?.monitors.length || 0,
  active: brands.value.filter((brand) =>
    ["running", "queued", "pausing", "stopping"].includes(brand.state.status),
  ).length,
  news: brands.value.reduce((total, brand) => total + Number(brand.state.new_count || 0), 0),
}));

const brandSearchItems = computed<NewsBrandSearchResult[]>(() =>
  brands.value
    .filter((brand) => brand.brandId != null)
    .map((brand) => ({ id: Number(brand.brandId), name: brand.brand }))
    .sort((left, right) => left.name.localeCompare(right.name, "ru")),
);

async function openBrand(brand: BrandGroup) {
  const selected =
    brand.monitors.find((item) => String(item.id) === String(item.primary_donor_id)) ||
    brand.monitors[0];
  if (!selected) return;

  if (brand.brandId && route.path !== `/news/edit/${brand.brandId}`) {
    await navigateTo(`/news/edit/${brand.brandId}`, { replace: true });
    return;
  }

  selectedMonitorId.value = selected.id;
  modalOpen.value = true;
}

async function openRequestedBrand(brandId: string) {
  const brand = brands.value.find(
    (item) => String(item.brandId || "") === String(brandId),
  );
  if (!brand) {
    pageError.value = "Бренд не найден";
    return;
  }
  await openBrand(brand);
}

async function openSearchedBrand(brand: NewsBrandSearchResult | undefined) {
  if (!brand) return;
  const brandId = String(brand.id);
  const target = `/news/edit/${brandId}`;

  if (route.path === target) {
    await openRequestedBrand(brandId);
    return;
  }
  await navigateTo(target);
}

async function closeModal() {
  modalOpen.value = false;
  selectedMonitorId.value = "";
  if (route.path.startsWith("/news/edit/")) {
    await navigateTo("/news", { replace: true });
  }
}

async function createMonitor() {
  creating.value = true;
  try {
    const result = await newsService.createMonitor({
      group: createGroup.value.trim() || "Маржа",
      brand: createBrand.value.trim() || "Новый бренд",
      create_new_brand: true,
    });
    upsertMonitor(result.monitor);
    createOpen.value = false;
    createBrand.value = "";
    const created = brands.value.find((item) =>
      item.monitors.some((monitor) => monitor.id === result.monitor.id),
    );
    if (created) await openBrand(created);
  } catch (caught) {
    toast.add({ title: errorMessage(caught), color: "error" });
  } finally {
    creating.value = false;
  }
}

async function runBrandAction(brand: BrandGroup, action: "pause" | "resume" | "stop" | "reset-visual") {
  const monitor =
    brand.monitors.find((item) =>
      action === "resume"
        ? item.state.status === "partial"
        : ["running", "queued", "pausing", "stopping"].includes(item.state.status),
    ) || brand.monitors[0];
  if (!monitor) return;
  try {
    const result = await newsService.action(monitor.id, action);
    monitor.state = mergeProgressState(monitor.state, result.monitor.state);
  } catch (caught) {
    pageError.value = errorMessage(caught);
  }
}

function requestDelete(brand: BrandGroup) {
  deletingKey.value = brand.key;
  deleteOpen.value = true;
}

async function deleteBrand() {
  const brand = brands.value.find((item) => item.key === deletingKey.value);
  const monitor = brand?.monitors[0];
  if (!monitor) return;
  try {
    const result = await newsService.removeMonitor(monitor.id, "brand");
    if (data.value) {
      const removed = new Set(result.removed_ids);
      data.value.monitors = data.value.monitors.filter(
        (item) => !removed.has(item.id),
      );
    }
    deleteOpen.value = false;
    toast.add({ title: "Бренд удалён", color: "success" });
  } catch (caught) {
    toast.add({ title: errorMessage(caught), color: "error" });
  }
}

function handleModalChanged(incoming: NewsMonitor[]) {
  if (!data.value || !incoming.length) return;
  const brandId = incoming[0]?.brand_id;
  if (brandId != null) {
    const incomingIds = new Set(incoming.map((monitor) => monitor.id));
    data.value.monitors = data.value.monitors.filter(
      (monitor) =>
        monitor.brand_id !== brandId || incomingIds.has(monitor.id),
    );
  }
  for (const monitor of incoming) upsertMonitor(monitor);
}

async function pollProgress() {
  const payload = await $fetch<ProgressPayload>("/progress", {
    query: {
      once: 1,
      projects: 0,
      news: 1,
      cursor: progressCursor.value || undefined,
    },
  });
  mergeProgress(payload);
}

useProgressPolling(pollProgress, computed(() => Boolean(data.value)));

onMounted(async () => {
  try {
    if (!loaded.value) await load(true);
    if (props.brandId) {
      await openRequestedBrand(props.brandId);
    }
  } catch (caught) {
    pageError.value = errorMessage(caught, "Не удалось загрузить мониторинг");
  }
});

</script>

<template>
  <div>
    <SectionHeader
      eyebrow="МОНИТОРИНГ НОВИНОК"
      title="Бренды и доноры"
      description="Сверяйте каталоги поставщиков с собственными фидами и выгружайте только новые модели."
    >
      <template #actions>
        <NewsBrandToolbar
          :brands="brandSearchItems"
          @select="openSearchedBrand"
          @create="createOpen = true"
        />
      </template>
    </SectionHeader>

    <div class="metrics-grid">
      <MetricCard label="Брендов" :value="totals.brands" icon="i-lucide-tags" tone="mint" />
      <MetricCard label="Доноров" :value="totals.donors" icon="i-lucide-globe-2" tone="blue" />
      <MetricCard label="Активных проверок" :value="totals.active" icon="i-lucide-radar" tone="amber" />
      <MetricCard label="Новых моделей" :value="totals.news" icon="i-lucide-sparkles" tone="purple" />
    </div>

    <UAlert
      v-if="pageError"
      color="error"
      variant="subtle"
      icon="i-lucide-triangle-alert"
      :description="pageError"
      close
      class="page-error"
      @update:open="pageError = ''"
    />

    <div v-if="loading && !data" class="loading-state">
      <span class="loading-logo"><UIcon name="i-lucide-sparkles" /></span>
      <p>Загружаем бренды…</p>
    </div>

    <EmptyState
      v-else-if="loaded && !brands.length"
      icon="i-lucide-radar"
      title="Мониторинг ещё не настроен"
      description="Добавьте бренд, укажите сайт-донора и стартовые URL."
    >
      <UButton color="primary" icon="i-lucide-plus" @click="createOpen = true">
        Добавить бренд
      </UButton>
    </EmptyState>

    <NewsBrandGroups
      v-else-if="loaded"
      :groups="groupedBrands"
      @open="openBrand"
      @action="runBrandAction"
      @remove="requestDelete"
    />

    <LazyNewsMonitorModal
      v-if="modalOpen && selectedMonitorId"
      :monitor-id="selectedMonitorId"
      :connection-methods="data?.connection_methods || []"
      :live-monitors="data?.monitors || []"
      @close="closeModal"
      @changed="handleModalChanged"
    />

    <NewsBrandDialogs
      v-model:create-open="createOpen"
      v-model:delete-open="deleteOpen"
      v-model:create-group="createGroup"
      v-model:create-brand="createBrand"
      :creating="creating"
      @create="createMonitor"
      @remove="deleteBrand"
    />
  </div>
</template>

<style src="../assets/css/news.css"></style>
