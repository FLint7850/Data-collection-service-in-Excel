<script setup lang="ts">
import type { Project } from "~/types/api";

defineProps<{
  projects: Project[];
  activeProjectId: string;
}>();

const emit = defineEmits<{
  select: [projectId: string];
}>();
</script>

<template>
  <UCard as="aside" variant="outline" class="project-rail panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">СПИСОК</p>
        <h3>Проекты</h3>
      </div>
      <UBadge color="neutral" variant="subtle">{{ projects.length }}</UBadge>
    </div>
    <div class="project-list">
      <UButton
        v-for="project in projects"
        :key="project.id"
        type="button"
        color="neutral"
        variant="ghost"
        block
        class="project-list-item"
        :class="{ active: project.id === activeProjectId }"
        @click="emit('select', project.id)"
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
      </UButton>
    </div>
  </UCard>
</template>
