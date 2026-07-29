<script setup lang="ts">
import { scanStatusColor, scanStatusLabel } from "~/utils/format";

const props = defineProps<{ status?: string }>();
</script>

<template>
  <UBadge
    :color="scanStatusColor(props.status)"
    variant="subtle"
    size="sm"
    class="status-badge"
  >
    <span class="status-dot-mini" />
    {{ scanStatusLabel(props.status) }}
  </UBadge>
</template>
