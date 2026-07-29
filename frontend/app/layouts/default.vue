<template>
  <div class="app-shell">
    <AppSidebar />
    <main class="main-area">
      <AppTopbar />
      <div class="page-content">
        <slot />
      </div>
    </main>
  </div>
</template>
