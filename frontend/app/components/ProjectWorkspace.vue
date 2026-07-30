<script setup lang="ts">
import {
  projectService,
  type ProjectSavePayload,
} from "~/services/project.service";
import type { ProgressPayload, Project } from "~/types/api";
import { errorMessage } from "~/utils/format";
import { normalizeProjectRouteId } from "~/utils/route-id";

const props = withDefaults(defineProps<{ projectId?: string }>(), { projectId: "" });
const toast = useToast();
const {
  projects,
  progressCursor,
  connectionMethods,
  loading,
  load,
  loadProject,
  upsert,
  mergeProgress,
} = useProjects();

const activeProjectId = ref(normalizeProjectRouteId(props.projectId));
const draft = ref<Project | null>(null);
const detailLoading = ref(false);
const saving = ref(false);
const initialized = ref(false);
const workspaceReady = ref(false);
const createOpen = ref(false);
const deleteOpen = ref(false);
const newProjectName = ref("");
const creating = ref(false);
const deleting = ref(false);
const actionLoading = ref("");
const pageError = ref("");
let saveTimer: ReturnType<typeof setTimeout> | undefined;
let lastSavedPayload: ProjectSavePayload | null = null;

const activeProject = computed(
  () => projects.value.find((item) => item.id === activeProjectId.value) || null,
);
const activeState = computed(() => activeProject.value?.state || draft.value?.state);
const connectionOptions = computed(() =>
  connectionMethods.value.map((method) => ({ label: method.name, value: method.code })),
);
const isActive = computed(() =>
  ["running", "queued", "pausing", "stopping"].includes(activeState.value?.status || ""),
);
const canResume = computed(() =>
  ["paused", "partial"].includes(activeState.value?.status || ""),
);
const startButtonLabel = computed(() => (canResume.value ? "Продолжить" : "Запустить сбор"));

function cloneProject(project: Project) {
  return JSON.parse(JSON.stringify(project)) as Project;
}

async function selectProject(projectId: string, updateRoute = true) {
  const normalizedId = normalizeProjectRouteId(projectId);
  if (!normalizedId || normalizedId === activeProjectId.value && draft.value) return false;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = undefined;
  initialized.value = false;
  detailLoading.value = true;
  pageError.value = "";
  activeProjectId.value = normalizedId;
  draft.value = null;
  lastSavedPayload = null;
  try {
    const project = await loadProject(normalizedId);
    draft.value = cloneProject(project);
    lastSavedPayload = JSON.parse(
      JSON.stringify(savePayload()),
    ) as ProjectSavePayload;
    if (updateRoute && useRoute().path !== `/projects/edit/${normalizedId}`) {
      await navigateTo(`/projects/edit/${normalizedId}`);
    }
    await nextTick();
    initialized.value = true;
    return true;
  } catch (caught) {
    pageError.value = errorMessage(caught, "Не удалось открыть проект");
    activeProjectId.value = "";
    return false;
  } finally {
    detailLoading.value = false;
  }
}

function savePayload(): ProjectSavePayload | null {
  if (!draft.value) return null;
  return {
    name: draft.value.name.trim(),
    start_urls: draft.value.start_urls,
    thread_count: Number(draft.value.thread_count || 4),
    connection_method: draft.value.connection_method,
    auto_connection_fallback: draft.value.auto_connection_fallback,
    persist_profile: draft.value.persist_profile,
    product_url_filters: draft.value.product_url_filters,
    product_url_exclusions: draft.value.product_url_exclusions,
    extraction_rules: draft.value.extraction_rules,
  };
}

function changedSavePayload(
  current: ProjectSavePayload,
): Partial<ProjectSavePayload> {
  if (!lastSavedPayload) return current;
  const changes: Partial<ProjectSavePayload> = {};
  for (const key of Object.keys(current) as (keyof ProjectSavePayload)[]) {
    if (JSON.stringify(current[key]) !== JSON.stringify(lastSavedPayload[key])) {
      (changes as Record<string, unknown>)[key] = current[key];
    }
  }
  return changes;
}

async function save(silent = false) {
  const payload = savePayload();
  if (!payload || !activeProjectId.value || draft.value?.id !== activeProjectId.value) return;
  const changes = changedSavePayload(payload);
  if (!Object.keys(changes).length) return true;
  saving.value = true;
  try {
    const response = await projectService.update(activeProjectId.value, changes);
    upsert(response.project);
    if (draft.value) draft.value.state = response.project.state;
    lastSavedPayload = JSON.parse(JSON.stringify(payload)) as ProjectSavePayload;
    if (!silent) toast.add({ title: "Проект сохранён", color: "success" });
    return true;
  } catch (caught) {
    const message = errorMessage(caught, "Не удалось сохранить проект");
    pageError.value = message;
    if (!silent) toast.add({ title: message, color: "error" });
  } finally {
    saving.value = false;
  }
}

function scheduleSave() {
  if (
    !initialized.value ||
    !draft.value ||
    draft.value.id !== activeProjectId.value ||
    isActive.value
  ) return;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => void save(true), 800);
}

watch(
  () => props.projectId,
  (id) => {
    const normalizedId = normalizeProjectRouteId(id);
    if (normalizedId && normalizedId !== activeProjectId.value) {
      void selectProject(normalizedId, false);
    }
  },
);

watch(
  () => {
    const payload = savePayload();
    return payload ? JSON.stringify(payload) : "";
  },
  () => scheduleSave(),
);

async function createProject() {
  const name = newProjectName.value.trim() || `Проект ${projects.value.length + 1}`;
  creating.value = true;
  try {
    const response = await projectService.create(name);
    upsert(response.project);
    createOpen.value = false;
    newProjectName.value = "";
    await selectProject(response.project.id);
    toast.add({ title: "Проект создан", color: "success" });
  } catch (caught) {
    toast.add({ title: errorMessage(caught), color: "error" });
  } finally {
    creating.value = false;
  }
}

async function deleteProject() {
  if (!activeProjectId.value) return;
  deleting.value = true;
  try {
    await projectService.remove(activeProjectId.value);
    const deletedId = activeProjectId.value;
    projects.value = projects.value.filter((item) => item.id !== deletedId);
    deleteOpen.value = false;
    const next = projects.value[0];
    if (next) await selectProject(next.id);
    toast.add({ title: "Проект удалён", color: "success" });
  } catch (caught) {
    toast.add({ title: errorMessage(caught), color: "error" });
  } finally {
    deleting.value = false;
  }
}

function collectionKey(
  collection: "exclusions" | "product-url-filters" | "product-url-exclusions",
) {
  return collection === "exclusions"
    ? "exclusions"
    : collection === "product-url-filters"
      ? "product_url_filters"
      : "product_url_exclusions";
}

async function addPattern(
  collection: "exclusions" | "product-url-filters" | "product-url-exclusions",
  pattern: string,
) {
  if (!draft.value) return;
  try {
    const response = await projectService.addPattern(draft.value.id, collection, pattern);
    const key = collectionKey(collection);
    if (!draft.value[key].includes(response.pattern)) {
      draft.value[key].push(response.pattern);
    }
    const current = activeProject.value;
    if (current) current[key] = [...draft.value[key]];
    if (lastSavedPayload && key !== "exclusions") {
      lastSavedPayload[key] = [...draft.value[key]];
    }
  } catch (caught) {
    toast.add({ title: errorMessage(caught), color: "error" });
  }
}

async function removePattern(
  collection: "exclusions" | "product-url-filters" | "product-url-exclusions",
  index: number,
) {
  if (!draft.value) return;
  try {
    const response = await projectService.removePattern(
      draft.value.id,
      collection,
      index,
    );
    const key = collectionKey(collection);
    const localIndex = draft.value[key].indexOf(response.removed);
    if (localIndex >= 0) draft.value[key].splice(localIndex, 1);
    const current = activeProject.value;
    if (current) current[key] = [...draft.value[key]];
    if (lastSavedPayload && key !== "exclusions") {
      lastSavedPayload[key] = [...draft.value[key]];
    }
  } catch (caught) {
    toast.add({ title: errorMessage(caught), color: "error" });
  }
}

async function startOrResume() {
  if (!draft.value) return;
  actionLoading.value = canResume.value ? "resume" : "start";
  pageError.value = "";
  try {
    let state;
    if (canResume.value) {
      state = await projectService.action(draft.value.id, "resume");
    } else {
      const saved = await save(true);
      if (!saved) return;
      state = await projectService.start(draft.value.id);
    }
    draft.value.state = state;
    if (activeProject.value) activeProject.value.state = state;
  } catch (caught) {
    pageError.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

async function runAction(action: "pause" | "soft-pause" | "stop" | "restart") {
  if (!draft.value) return;
  actionLoading.value = action;
  pageError.value = "";
  try {
    const state = await projectService.action(draft.value.id, action);
    draft.value.state = state;
    if (activeProject.value) activeProject.value.state = state;
  } catch (caught) {
    pageError.value = errorMessage(caught);
  } finally {
    actionLoading.value = "";
  }
}

async function pollProgress() {
  const payload = await $fetch<ProgressPayload>("/progress", {
    query: {
      once: 1,
      projects: 1,
      news: 0,
      cursor: progressCursor.value || undefined,
    },
  });
  mergeProgress(payload);
  if (activeProjectId.value && !activeProject.value) {
    draft.value = null;
    lastSavedPayload = null;
    const next = projects.value[0];
    if (next) await selectProject(next.id);
    return;
  }
  if (draft.value && activeProject.value) {
    draft.value.state = { ...draft.value.state, ...activeProject.value.state };
  }
}

useProgressPolling(
  pollProgress,
  workspaceReady,
);

onMounted(async () => {
  try {
    await load(true);
    workspaceReady.value = true;
    const requested = normalizeProjectRouteId(props.projectId);
    if (requested) {
      const selected = projects.value.find((item) => item.id === requested);
      if (!selected) {
        activeProjectId.value = "";
        pageError.value = "Проект не найден";
        return;
      }
      await selectProject(selected.id, false);
      return;
    }
    const selected = projects.value[0];
    if (selected) await selectProject(selected.id);
  } catch (caught) {
    pageError.value = errorMessage(caught, "Не удалось загрузить проекты");
  }
});

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer);
});
</script>

<template>
  <div>
    <SectionHeader
      eyebrow="РАБОЧЕЕ ПРОСТРАНСТВО"
      title="Проекты парсинга"
      description="У каждого проекта собственные ссылки, правила, прогресс и итоговый CSV."
    >
      <template #actions>
        <span v-if="saving" class="save-indicator">
          <UIcon name="i-lucide-loader-circle" class="spin" />
          Сохранение
        </span>
        <UButton
          icon="i-lucide-plus"
          color="primary"
          @click="createOpen = true"
        >
          Новый проект
        </UButton>
      </template>
    </SectionHeader>

    <UAlert
      v-if="pageError"
      color="error"
      variant="subtle"
      icon="i-lucide-triangle-alert"
      :description="pageError"
      :close="{ color: 'error', variant: 'ghost' }"
      class="page-error"
      @update:open="pageError = ''"
    />

    <div v-if="loading && !projects.length" class="loading-state">
      <span class="loading-logo"><UIcon name="i-lucide-sheet" /></span>
      <p>Загружаем проекты…</p>
    </div>

    <EmptyState
      v-else-if="!projects.length"
      icon="i-lucide-folder-plus"
      title="Пока нет проектов"
      description="Создайте первый проект и добавьте стартовую ссылку каталога."
    >
      <UButton color="primary" icon="i-lucide-plus" @click="createOpen = true">
        Создать проект
      </UButton>
    </EmptyState>

    <div v-else class="project-layout">
      <UCard as="aside" variant="outline" class="project-rail panel">
        <div class="panel-header">
          <div>
            <p class="eyebrow">СПИСОК</p>
            <h3>Проекты</h3>
          </div>
          <UBadge color="neutral" variant="subtle">{{ projects.length }}</UBadge>
        </div>
        <div class="project-list">
          <button
            v-for="project in projects"
            :key="project.id"
            type="button"
            class="project-list-item"
            :class="{ active: project.id === activeProjectId }"
            @click="selectProject(project.id)"
          >
            <span class="project-list-icon">
              <UIcon name="i-lucide-folder-kanban" />
            </span>
            <span>
              <strong>{{ project.name }}</strong>
              <small>
                {{ project.start_urls_count ?? project.start_urls?.length ?? 0 }}
                стартовых URL
              </small>
            </span>
            <StatusBadge :status="project.state.status" />
          </button>
        </div>
      </UCard>

      <UCard v-if="detailLoading" variant="outline" class="panel project-loading-card">
        <UIcon name="i-lucide-loader-circle" class="spin" />
        Загружаем настройки проекта…
      </UCard>

      <UCard v-else-if="!draft" variant="outline" class="panel project-loading-card project-error-card">
        <UIcon name="i-lucide-folder-x" />
        <span>{{ pageError || "Выберите существующий проект" }}</span>
      </UCard>

      <div v-else class="project-main">
        <UCard as="section" variant="outline" class="panel project-editor-panel">
          <div class="panel-header">
            <div>
              <p class="eyebrow">НАСТРОЙКИ СБОРА</p>
              <h2><strong>{{ draft.name || "Без названия" }}</strong></h2>
            </div>
            <div class="project-panel-actions">
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-save"
                :loading="saving"
                :disabled="isActive"
                @click="save()"
              >
                Сохранить
              </UButton>
              <UButton
                color="error"
                variant="ghost"
                icon="i-lucide-trash-2"
                :disabled="projects.length <= 1 || isActive"
                @click="deleteOpen = true"
              >
                Удалить
              </UButton>
            </div>
          </div>

          <div class="form-grid project-form-grid">
            <UFormField label="Название проекта" class="field-span-2">
              <UInput
                v-model="draft.name"
                :disabled="isActive"
                placeholder="Например, Каталог MAUNFELD"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Количество потоков">
              <UInput
                v-model.number="draft.thread_count"
                type="number"
                :min="1"
                :max="16"
                :disabled="isActive"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Способ подключения">
              <USelect
                v-model="draft.connection_method"
                :items="connectionOptions"
                :disabled="isActive"
                class="w-full"
              />
            </UFormField>
            <UFormField
              label="Стартовые URL"
              description="По одной ссылке на строку"
              class="field-span-2"
            >
              <UTextarea
                :model-value="draft.start_urls.join('\n')"
                :disabled="isActive"
                :rows="5"
                autoresize
                class="w-full"
                placeholder="https://www.maunfeld.ru/catalog/..."
                @update:model-value="draft.start_urls = String($event).split(/\r?\n/).map((item) => item.trim()).filter(Boolean)"
              />
            </UFormField>
          </div>

          <div class="switch-grid">
            <UCard
              as="label"
              variant="subtle"
              class="switch-card"
              :ui="{ body: 'switch-card-body' }"
            >
              <USwitch v-model="draft.auto_connection_fallback" :disabled="isActive" />
              <span>
                <strong>Автопереключение</strong>
                <small>Пробовать резервный способ подключения при блокировке.</small>
              </span>
            </UCard>
            <UCard
              as="label"
              variant="subtle"
              class="switch-card"
              :ui="{ body: 'switch-card-body' }"
            >
              <USwitch v-model="draft.persist_profile" :disabled="isActive" />
              <span>
                <strong>Сохранять профиль</strong>
                <small>Повторно использовать cookies браузерной сессии.</small>
              </span>
            </UCard>
          </div>

          <div class="run-actions">
            <UButton
              color="primary"
              icon="i-lucide-play"
              :loading="actionLoading === 'start' || actionLoading === 'resume'"
              :disabled="isActive && activeState?.status !== 'paused'"
              @click="startOrResume"
            >
              {{ startButtonLabel }}
            </UButton>
            <UButton
              color="neutral"
              variant="soft"
              :icon="activeState?.status === 'paused' ? 'i-lucide-play' : 'i-lucide-pause'"
              :loading="actionLoading === 'soft-pause'"
              :disabled="!['running', 'paused'].includes(activeState?.status || '')"
              @click="activeState?.status === 'paused' ? startOrResume() : runAction('soft-pause')"
            >
              {{ activeState?.status === "paused" ? "Продолжить" : "Пауза" }}
            </UButton>
            <UButton
              color="warning"
              variant="soft"
              icon="i-lucide-file-check-2"
              :loading="actionLoading === 'pause'"
              :disabled="activeState?.status !== 'running'"
              @click="runAction('pause')"
            >
              Пауза с результатом
            </UButton>
            <UButton
              color="neutral"
              variant="soft"
              icon="i-lucide-rotate-cw"
              :loading="actionLoading === 'restart'"
              :disabled="isActive"
              @click="runAction('restart')"
            >
              Перезапустить
            </UButton>
            <UButton
              color="error"
              variant="soft"
              icon="i-lucide-square"
              :loading="actionLoading === 'stop'"
              :disabled="!isActive && activeState?.status === 'idle'"
              @click="runAction('stop')"
            >
              Остановить
            </UButton>
          </div>
        </UCard>

        <ProgressPanel
          :state="activeState!"
          :download-url="`/api/projects/${draft.id}/download`"
        />

        <UCard as="section" variant="outline" class="panel settings-stack">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ФИЛЬТРАЦИЯ</p>
              <h2><strong>Исключения и URL-фильтры</strong></h2>
            </div>
          </div>

          <SettingsCollapsible class="mt-3">
            <template #label>
              Исключения разделов
              <UBadge color="neutral" variant="subtle">{{ draft.exclusions.length }}</UBadge>
            </template>
            <PatternEditor
              :model-value="draft.exclusions"
              placeholder="/catalog/rasprodazha/"
              :disabled="isActive"
              @add="addPattern('exclusions', $event)"
              @remove="removePattern('exclusions', $event)"
            />
          </SettingsCollapsible>

          <SettingsCollapsible>
            <template #label>
              Фильтр товарных URL
              <UBadge color="neutral" variant="subtle">{{ draft.product_url_filters.length }}</UBadge>
            </template>
            <PatternEditor
              :model-value="draft.product_url_filters"
              placeholder="-qyron-"
              :disabled="isActive"
              @add="addPattern('product-url-filters', $event)"
              @remove="removePattern('product-url-filters', $event)"
            />
          </SettingsCollapsible>

          <SettingsCollapsible>
            <template #label>
              Исключения товарных ссылок
              <UBadge color="neutral" variant="subtle">{{ draft.product_url_exclusions.length }}</UBadge>
            </template>
            <PatternEditor
              :model-value="draft.product_url_exclusions"
              placeholder="/recommend"
              :disabled="isActive"
              @add="addPattern('product-url-exclusions', $event)"
              @remove="removePattern('product-url-exclusions', $event)"
            />
          </SettingsCollapsible>
        </UCard>

        <UCard as="section" variant="outline" class="panel settings-stack">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ТОЧНАЯ НАСТРОЙКА</p>
              <h2><strong>Селекторы и правила модели</strong></h2>
            </div>
          </div>

          <SettingsCollapsible content-class="form-grid" class="mt-3">
            <template #label>CSS-селекторы карточек</template>
            <UFormField label="Карточка товара">
              <UInput v-model="draft.extraction_rules.product_card_selector" placeholder=".product-card" class="w-full" />
            </UFormField>
            <UFormField label="Ссылка товара">
              <UInput v-model="draft.extraction_rules.product_url_selector" placeholder="a[href]" class="w-full" />
            </UFormField>
            <UFormField label="Модель">
              <UInput v-model="draft.extraction_rules.model_selector" placeholder=".product-title" class="w-full" />
            </UFormField>
            <UFormField label="Цена">
              <UInput v-model="draft.extraction_rules.price_selector" placeholder=".price" class="w-full" />
            </UFormField>
          </SettingsCollapsible>

          <SettingsCollapsible content-class="form-grid">
            <template #label>Маркеры и поиск/замена</template>
            <UFormField label="Начальный маркер">
              <UInput v-model="draft.extraction_rules.model_start_marker" placeholder="<h1 class=&quot;detail__title&quot;>" class="w-full" />
            </UFormField>
            <UFormField label="Конечный маркер">
              <UInput v-model="draft.extraction_rules.model_end_marker" placeholder="</h1>" class="w-full" />
            </UFormField>
            <UFormField label="Правила замены" class="field-span-2">
              <UTextarea
                v-model="draft.extraction_rules.model_replace_rules"
                :rows="5"
                class="w-full code-input"
                placeholder="{reg[#[^A-Za-z0-9./\-\s]#]}|"
              />
            </UFormField>
          </SettingsCollapsible>
        </UCard>
      </div>
    </div>

    <UModal
      v-model:open="createOpen"
      title="Создать проект"
      description="Добавьте отдельное рабочее пространство для нового каталога."
      :ui="{ content: 'max-w-md' }"
    >
      <template #body>
        <UFormField label="Название проекта">
          <UInput
            v-model="newProjectName"
            autofocus
            placeholder="Например, Каталог бренда"
            class="w-full"
            @keyup.enter="createProject"
          />
        </UFormField>
      </template>
      <template #footer>
        <UButton color="neutral" variant="soft" @click="createOpen = false">Отмена</UButton>
        <UButton color="primary" :loading="creating" @click="createProject">Создать</UButton>
      </template>
    </UModal>

    <UModal
      v-model:open="deleteOpen"
      title="Удалить проект?"
      :description="`Проект «${activeProject?.name || ''}» и его настройки будут удалены. Это действие нельзя отменить.`"
      :ui="{ content: 'max-w-md' }"
    >
      <template #footer>
        <UButton color="neutral" variant="soft" @click="deleteOpen = false">Отмена</UButton>
        <UButton color="error" :loading="deleting" @click="deleteProject">Удалить</UButton>
      </template>
    </UModal>
  </div>
</template>
