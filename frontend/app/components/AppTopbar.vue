<script setup lang="ts">
import { authService } from "~/services/auth.service";
import type { AuthSession } from "~/types/api";

const route = useRoute();
const mobileOpen = useState<boolean>("mobile-nav-open", () => false);
const session = useState<AuthSession | null>("auth-session", () => null);
const loggingOut = ref(false);
const clientReady = ref(false);

const title = computed(() => String(route.meta.title || "Рабочее пространство"));
const eyebrow = computed(() => String(route.meta.eyebrow || "DATA WORKSPACE"));
const displayedUsername = computed(() =>
  clientReady.value ? session.value?.username || "Администратор" : "Администратор",
);

onMounted(() => {
  clientReady.value = true;
});

async function logout() {
  loggingOut.value = true;
  try {
    await authService.logout();
    clearDomainCache();
    session.value = { authenticated: false, username: "" };
    await navigateTo("/login");
  } finally {
    loggingOut.value = false;
  }
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-title">
      <UButton
        class="mobile-menu-button"
        icon="i-lucide-menu"
        color="neutral"
        variant="ghost"
        aria-label="Открыть меню"
        @click="mobileOpen = true"
      />
      <div>
        <p class="eyebrow">{{ eyebrow }}</p>
        <h1>{{ title }}</h1>
      </div>
    </div>

    <div class="topbar-actions">
      <UDropdownMenu
        :items="[
          [
            {
              label: 'Выйти',
              icon: 'i-lucide-log-out',
              disabled: loggingOut,
              onSelect: logout,
            },
          ],
        ]"
      >
        <UButton
          color="neutral"
          variant="ghost"
          trailing-icon="i-lucide-chevron-down"
          class="user-button"
        >
          <span class="avatar">{{ displayedUsername.slice(0, 2).toUpperCase() }}</span>
          <span class="user-copy">
            <strong>{{ displayedUsername }}</strong>
            <small>Администратор</small>
          </span>
        </UButton>
      </UDropdownMenu>
    </div>
  </header>
</template>
