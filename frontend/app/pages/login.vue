<script setup lang="ts">
import {authService} from "~/services/auth.service";
import {errorMessage, errorStatusCode} from "~/utils/format";

definePageMeta({
  layout: "auth",
  title: "Вход",
});

const route = useRoute();
const username = ref("");
const password = ref("");
const showPassword = ref(false);
const loading = ref(false);
const error = ref("");

async function submit() {
  error.value = "";
  loading.value = true;
  try {
    useState("auth-session").value = await authService.login(username.value.trim(), password.value);
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/projects";
    await navigateTo(redirect);
  } catch (caught) {
    const statusCode = errorStatusCode(caught);
    if (statusCode === 401) {
      error.value = "Неверный логин или пароль";
    } else if (!statusCode || statusCode >= 500) {
      error.value = "Сервис авторизации недоступен. Проверьте, что backend запущен, и повторите попытку.";
    } else {
      error.value = errorMessage(caught, "Не удалось войти в сервис");
    }
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <UCard variant="outline" class="auth-card" :ui="{ body: 'auth-card-body' }">
    <div class="auth-brand">
      <span class="brand-mark brand-mark--large">
        <UIcon name="i-lucide-sheet" />
      </span>
      <div class="brand-copy">
        <strong>Excel</strong>
        <span>Collector</span>
      </div>
    </div>

    <div class="auth-copy">
      <p class="eyebrow mint">DATA WORKSPACE</p>
      <h1>Добро пожаловать</h1>
      <p>Войдите, чтобы управлять проектами сбора, фидами и мониторингом новинок.</p>
    </div>

    <form class="auth-form" @submit.prevent="submit">
      <UFormField label="Логин" required>
        <UInput
          v-model="username"
          autocomplete="username"
          autofocus
          icon="i-lucide-user"
          size="xl"
          class="w-full"
        />
      </UFormField>
      <UFormField label="Пароль" required>
        <UInput
          v-model="password"
          :type="showPassword ? 'text' : 'password'"
          autocomplete="current-password"
          icon="i-lucide-lock-keyhole"
          size="xl"
          class="w-full"
          :ui="{ trailing: 'pe-1' }"
        >
          <template #trailing>
            <UButton
              color="neutral"
              variant="link"
              size="sm"
              :icon="showPassword ? 'i-lucide-eye-off' : 'i-lucide-eye'"
              :aria-label="showPassword ? 'Скрыть пароль' : 'Показать пароль'"
              @click="showPassword = !showPassword"
            />
          </template>
        </UInput>
      </UFormField>

      <UAlert
        v-if="error"
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :description="error"
      />

      <UButton
        type="submit"
        color="primary"
        size="xl"
        block
        icon="i-lucide-log-in"
        :loading="loading"
        :disabled="!username.trim() || !password"
      >
        Войти в сервис
      </UButton>
    </form>
  </UCard>
</template>

<style src="../assets/css/auth.css"></style>
