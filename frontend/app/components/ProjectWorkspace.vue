<script setup lang="ts">
import {
  projectService,
  type ProjectSavePayload,
} from "~/services/project.service";
import type { ProgressPayload, Project } from "~/types/api";
import { errorMessage } from "~/utils/format";
import { mergeRemoteDraft } from "~/utils/remote-draft";
import { normalizeProjectRouteId } from "~/utils/route-id";

const props = withDefaults(defineProps<{ projectId?: string }>(), { projectId: "" });
const toast = useToast();
const {
  projects,
  progressCursor,
  connectionMethods,
  loading,
  loaded,
  load,
  loadProject,
  upsert,
  mergeProgress,
} = useProjects();

const activeProjectId = ref(normalizeProjectRouteId(props.projectId));
const draft = ref<Project | null>(null);
const detailLoading = ref(false);
const saving = ref(false);
const workspaceReady = ref(false);
const createOpen = ref(false);
const deleteOpen = ref(false);
const newProjectName = ref("");
const creating = ref(false);
const deleting = ref(false);
const actionLoading = ref("");
const pageError = ref("");
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
    return true;
  } catch (caught) {
    pageError.value = errorMessage(caught, "Не удалось открыть проект");
    activeProjectId.value = "";
    return false;
  } finally {
    detailLoading.value = false;
  }
}

function projectPayload(project: Project): ProjectSavePayload {
  return {
    name: project.name.trim(),
    start_urls: project.start_urls,
    thread_count: Number(project.thread_count || 4),
    connection_method: project.connection_method,
    auto_connection_fallback: project.auto_connection_fallback,
    persist_profile: project.persist_profile,
    exclusions: project.exclusions,
    product_url_filters: project.product_url_filters,
    product_url_exclusions: project.product_url_exclusions,
    extraction_rules: project.extraction_rules,
  };
}

function savePayload(): ProjectSavePayload | null {
  return draft.value ? projectPayload(draft.value) : null;
}

function syncRemoteProject(remote: Project) {
  if (!draft.value || draft.value.id !== remote.id) return;
  const currentPayload = projectPayload(draft.value);
  const remotePayload = projectPayload(remote);
  draft.value = mergeRemoteDraft(
    draft.value,
    cloneProject(remote),
    lastSavedPayload,
    currentPayload,
  );
  lastSavedPayload = JSON.parse(
    JSON.stringify(remotePayload),
  ) as ProjectSavePayload;
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

watch(
  () => props.projectId,
  (id) => {
    const normalizedId = normalizeProjectRouteId(id);
    if (normalizedId && normalizedId !== activeProjectId.value) {
      void selectProject(normalizedId, false);
    }
  },
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
    if (action === "restart") {
      const saved = await save(true);
      if (!saved) return;
    }
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
      project_detail: activeProjectId.value || undefined,
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
  if (payload.project_detail) {
    syncRemoteProject(payload.project_detail);
  } else if (draft.value && activeProject.value) {
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

    <div v-if="loading" class="loading-state">
      <span class="loading-logo"><UIcon name="i-lucide-sheet" /></span>
      <p>Загружаем проекты…</p>
    </div>

    <EmptyState
      v-else-if="loaded && !projects.length"
      icon="i-lucide-folder-plus"
      title="Пока нет проектов"
      description="Создайте первый проект и добавьте стартовую ссылку каталога."
    >
      <UButton color="primary" icon="i-lucide-plus" @click="createOpen = true">
        Создать проект
      </UButton>
    </EmptyState>

    <div v-else-if="loaded" class="project-layout">
      <ProjectRail
        :projects="projects"
        :active-project-id="activeProjectId"
        @select="selectProject"
      />

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

          <ProjectRunActions
            :status="activeState?.status || 'idle'"
            :action-loading="actionLoading"
            :active="isActive"
            :start-button-label="startButtonLabel"
            @start="startOrResume"
            @action="runAction"
          />
        </UCard>

        <ProgressPanel
          :state="activeState!"
          :download-url="`/api/projects/${draft.id}/download`"
        />

        <ProjectFiltersPanel v-model="draft" :disabled="isActive" />

        <ProjectExtractionPanel v-model="draft" :disabled="isActive" />
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

<style src="../assets/css/project.css"></style>
