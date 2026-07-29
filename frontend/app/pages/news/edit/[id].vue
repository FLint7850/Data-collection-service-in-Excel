<script setup lang="ts">
import { normalizeBrandRouteId } from "~/utils/route-id";

definePageMeta({
  title: "Новинки",
  eyebrow: "МОНИТОРИНГ БРЕНДОВ",
  middleware: (route) => {
    if (!normalizeBrandRouteId(route.params.id)) {
      return navigateTo("/news", { redirectCode: 302, replace: true });
    }
  },
});

const route = useRoute();
const brandId = computed(() => normalizeBrandRouteId(route.params.id));
</script>

<template>
  <NewsWorkspace :brand-id="brandId" />
</template>
