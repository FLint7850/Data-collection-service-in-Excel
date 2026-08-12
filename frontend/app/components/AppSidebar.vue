<script setup lang="ts">
const mobileOpen = useState<boolean>("mobile-nav-open", () => false);

const navItems: Array<{
  label: string;
  caption: string;
  to: string;
  icon: string;
  onSelect: () => void;
}> = [
  {
    label: "Проекты",
    caption: "Сбор каталогов",
    to: "/projects",
    icon: "i-lucide-panels-top-left",
    onSelect: () => {
      mobileOpen.value = false;
    },
  },
  {
    label: "Новинки",
    caption: "Мониторинг брендов",
    to: "/news",
    icon: "i-lucide-sparkles",
    onSelect: () => {
      mobileOpen.value = false;
    },
  },
  {
    label: "Выгрузка",
    caption: "CSV и Excel",
    to: "/file-import",
    icon: "i-lucide-file-spreadsheet",
    onSelect: () => {
      mobileOpen.value = false;
    },
  },
  {
    label: "Конвертер",
    caption: "Прайсы поставщиков",
    to: "/price-converter",
    icon: "i-lucide-file-output",
    onSelect: () => {
      mobileOpen.value = false;
    },
  },
  {
    label: "Атрибуты",
    caption: "OpenCart / ocStore",
    to: "/attribute-assistant",
    icon: "i-lucide-list-checks",
    onSelect: () => {
      mobileOpen.value = false;
    },
  },
  {
    label: "Сравнение",
    caption: "Фиды поставщиков",
    to: "/feed-comparison",
    icon: "i-lucide-git-compare-arrows",
    onSelect: () => {
      mobileOpen.value = false;
    },
  },
  {
    label: "Настройки",
    caption: "Фиды и почта",
    to: "/settings",
    icon: "i-lucide-settings-2",
    onSelect: () => {
      mobileOpen.value = false;
    },
  },
  {
    label: "Логи",
    caption: "Все события",
    to: "/logs",
    icon: "i-lucide-scroll-text",
    onSelect: () => {
      mobileOpen.value = false;
    },
  },
];
</script>

<template>
  <aside class="sidebar" :class="{ 'sidebar--open': mobileOpen }">
    <NuxtLink class="brand" to="/projects" @click="mobileOpen = false">
      <span class="brand-mark">
        <UIcon name="i-lucide-sheet" />
      </span>
      <span class="brand-copy">
        <strong>Excel</strong>
        <span>Collector</span>
      </span>
    </NuxtLink>

    <UNavigationMenu
      :items="navItems"
      orientation="vertical"
      color="primary"
      variant="pill"
      highlight
      class="main-nav"
      aria-label="Основная навигация"
      :ui="{
        list: 'gap-1',
        link: 'nav-item min-h-12 rounded-xl px-3',
        linkLeadingIcon: 'nav-icon',
        linkLabel: 'w-full',
      }"
    >
      <template #item-label="{ item }">
        <span class="nav-copy">
          <strong>{{ item.label }}</strong>
          <small>{{ item.caption }}</small>
        </span>
      </template>
    </UNavigationMenu>
  </aside>

  <button
    v-if="mobileOpen"
    class="sidebar-backdrop"
    type="button"
    aria-label="Закрыть меню"
    @click="mobileOpen = false"
  />
</template>
