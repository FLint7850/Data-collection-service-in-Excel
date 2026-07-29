<script setup lang="ts">
import { logService } from "~/services/log.service";
import type { LogEntry, LogsResponse } from "~/types/api";
import { errorMessage, formatDateTime } from "~/utils/format";

definePageMeta({
  title: "Логи",
  eyebrow: "СИСТЕМНЫЕ СОБЫТИЯ",
});

const toast = useToast();
const data = ref<LogsResponse | null>(null);
const loading = ref(true);
const refreshing = ref(false);
const clearing = ref(false);
const confirmClear = ref(false);
const search = ref("");
const level = ref("all");
const error = ref("");

const levelOptions = [
  { label: "Все уровни", value: "all" },
  { label: "Информация", value: "info" },
  { label: "Успешно", value: "success" },
  { label: "Предупреждения", value: "warning" },
  { label: "Ошибки", value: "error" },
];

const filteredLogs = computed(() => {
  const query = search.value.trim().toLocaleLowerCase("ru");
  return (data.value?.logs || [])
    .filter((item) => level.value === "all" || item.level === level.value)
    .filter((item) => {
      if (!query) return true;
      return [item.message, item.project_name, item.brand, item.group]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("ru").includes(query));
    })
    .slice()
    .reverse();
});

const counters = computed(() => {
  const logs = data.value?.logs || [];
  return {
    total: data.value?.logs_total || logs.length,
    success: logs.filter((item) => item.level === "success").length,
    warning: logs.filter((item) => item.level === "warning").length,
    error: logs.filter((item) => item.level === "error").length,
  };
});

function logIcon(item: LogEntry) {
  return {
    success: "i-lucide-circle-check",
    warning: "i-lucide-triangle-alert",
    error: "i-lucide-circle-x",
    info: "i-lucide-info",
  }[item.level] || "i-lucide-dot";
}

async function load(silent = false) {
  if (!silent) refreshing.value = true;
  try {
    data.value = await logService.list();
  } catch (caught) {
    error.value = errorMessage(caught, "Не удалось загрузить логи");
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

async function toggleAutoCleanup(value: boolean) {
  if (!data.value) return;
  data.value.auto_cleanup = value;
  try {
    const result = await logService.setAutoCleanup(value);
    data.value.auto_cleanup = result.auto_cleanup;
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function clearLogs() {
  clearing.value = true;
  try {
    await logService.clear();
    confirmClear.value = false;
    await load();
    toast.add({ title: "Логи очищены", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    clearing.value = false;
  }
}

let timer: ReturnType<typeof setInterval> | undefined;
onMounted(async () => {
  await load();
  timer = setInterval(() => void load(true), 5000);
});
onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div>
    <SectionHeader
      eyebrow="ЖУРНАЛ ПРИЛОЖЕНИЯ"
      title="Логи"
      description="События проектов, мониторинга, импорта и системных процессов в одном потоке."
    >
      <template #actions>
        <UButton
          color="neutral"
          variant="soft"
          icon="i-lucide-refresh-cw"
          :loading="refreshing"
          @click="load()"
        >
          Обновить
        </UButton>
        <UButton
          color="error"
          variant="soft"
          icon="i-lucide-trash-2"
          @click="confirmClear = true"
        >
          Очистить
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

    <div class="metrics-grid">
      <MetricCard label="Всего событий" :value="counters.total" icon="i-lucide-list-tree" tone="blue" />
      <MetricCard label="Успешно" :value="counters.success" icon="i-lucide-circle-check" tone="mint" />
      <MetricCard label="Предупреждений" :value="counters.warning" icon="i-lucide-triangle-alert" tone="amber" />
      <MetricCard label="Ошибок" :value="counters.error" icon="i-lucide-circle-x" tone="red" />
    </div>

    <UCard as="section" variant="outline" class="panel logs-panel">
      <div class="logs-toolbar">
        <div class="logs-filters">
          <UInput
            v-model="search"
            icon="i-lucide-search"
            placeholder="Поиск по сообщениям"
            class="log-search"
          />
          <USelect v-model="level" :items="levelOptions" class="level-select" />
        </div>
        <label class="cleanup-toggle">
          <USwitch
            :model-value="data?.auto_cleanup || false"
            @update:model-value="toggleAutoCleanup"
          />
          <span>
            <strong>Автоочистка</strong>
            <small>Удалять события старше 7 суток</small>
          </span>
        </label>
      </div>

      <div v-if="loading" class="loading-state logs-loading">
        <UIcon name="i-lucide-loader-circle" class="spin" />
        <p>Загружаем события…</p>
      </div>

      <EmptyState
        v-else-if="!filteredLogs.length"
        icon="i-lucide-scroll-text"
        title="Событий не найдено"
        description="Измените фильтр или дождитесь новых действий в сервисе."
      />

      <div v-else class="logs-list">
        <UCard
            v-for="(item, index) in filteredLogs"
            :key="`${item.time}-${index}`"
            as="article"
            variant="subtle"
            class="log-item shrink-0"
            :class="`log-item--${item.level}`"
            :ui="{ body: 'log-item-body' }"
        >
          <span class="log-icon"><UIcon :name="logIcon(item)" /></span>
          <div class="log-copy">
            <div>
              <strong>{{ item.project_name || item.brand || item.group || "Система" }}</strong>
              <span>{{ formatDateTime(item.time) }}</span>
            </div>
            <p>{{ item.message }}</p>
          </div>
          <UBadge :color="item.level === 'error' ? 'error' : item.level === 'warning' ? 'warning' : item.level === 'success' ? 'success' : 'neutral'" variant="subtle">
            {{ item.level }}
          </UBadge>
        </UCard>
      </div>
    </UCard>

    <UModal
      v-model:open="confirmClear"
      title="Удалить все логи?"
      description="Журнал событий будет очищен для всех разделов."
      :ui="{ content: 'max-w-md' }"
    >
      <template #footer>
        <UButton color="neutral" variant="soft" @click="confirmClear = false">Отмена</UButton>
        <UButton color="error" :loading="clearing" @click="clearLogs">Очистить</UButton>
      </template>
    </UModal>
  </div>
</template>
