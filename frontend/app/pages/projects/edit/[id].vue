<script setup lang="ts">
import { normalizeProjectRouteId } from "~/utils/route-id";

definePageMeta({
  title: "Проекты",
  eyebrow: "СБОР КАТАЛОГОВ",
  middleware: (route) => {
    if (!normalizeProjectRouteId(route.params.id)) {
      return navigateTo("/projects", { redirectCode: 302, replace: true });
    }
  },
});

const route = useRoute();
const projectId = computed(() => normalizeProjectRouteId(route.params.id));
</script>

<template>
  <ProjectWorkspace :project-id="projectId" />
</template>
