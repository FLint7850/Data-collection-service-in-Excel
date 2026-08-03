<script setup lang="ts">
import { newsService } from "~/services/news.service";
import type { NewsConfiguration, OwnSite, SmtpSettings } from "~/types/api";
import { errorMessage } from "~/utils/format";

definePageMeta({
  title: "Настройки",
  eyebrow: "ФИДЫ · УВЕДОМЛЕНИЯ",
});

const toast = useToast();
const data = ref<NewsConfiguration | null>(null);
const loading = ref(true);
const saving = ref(false);
const testing = ref(false);
const error = ref("");
const sites = ref<OwnSite[]>([]);
const smtp = reactive({
  host: "",
  port: 465,
  security: "ssl",
  username: "",
  password: "",
  recipients: "",
});
let lastSavedSites = "";
let lastSavedSmtp = "";

function smtpPayload(): Partial<SmtpSettings> {
  return {
    host: smtp.host.trim(),
    port: Number(smtp.port || 465),
    security: smtp.security,
    username: smtp.username.trim(),
    recipients: smtp.recipients
      .split(/\r?\n|,/)
      .map((item) => item.trim())
      .filter(Boolean),
  };
}

function applyData(value: NewsConfiguration) {
  data.value = value;
  sites.value = JSON.parse(JSON.stringify(value.own_sites || [])) as OwnSite[];
  smtp.host = value.smtp.host || "";
  smtp.port = Number(value.smtp.port || 465);
  smtp.security = value.smtp.security || "ssl";
  smtp.username = value.smtp.username || "";
  smtp.password = "";
  smtp.recipients = (value.smtp.recipients || []).join("\n");
  lastSavedSites = JSON.stringify(sites.value);
  lastSavedSmtp = JSON.stringify(smtpPayload());
}

async function load() {
  try {
    applyData(await newsService.getSettings());
  } catch (caught) {
    error.value = errorMessage(caught, "Не удалось загрузить настройки");
  } finally {
    loading.value = false;
  }
}

async function save(showToast = true) {
  saving.value = true;
  error.value = "";
  try {
    const currentSites = sites.value.filter((site) => site.feed_url.trim());
    const currentSmtp = smtpPayload();
    const body: Parameters<typeof newsService.updateSettings>[0] = {};
    if (JSON.stringify(currentSites) !== lastSavedSites) {
      body.own_sites = currentSites;
    }
    if (
      JSON.stringify(currentSmtp) !== lastSavedSmtp ||
      smtp.password.trim()
    ) {
      body.smtp = currentSmtp;
      if (smtp.password.trim()) body.smtp.password = smtp.password.trim();
    }
    if (!Object.keys(body).length) {
      if (showToast) toast.add({ title: "Изменений нет", color: "neutral" });
      return true;
    }
    const response = await newsService.updateSettings(body);
    applyData(response);
    if (showToast) toast.add({ title: "Настройки сохранены", color: "success" });
    return true;
  } catch (caught) {
    error.value = errorMessage(caught);
    return false;
  } finally {
    saving.value = false;
  }
}

async function testEmail() {
  testing.value = true;
  try {
    if (!(await save(false))) return;
    await newsService.testEmail();
    toast.add({ title: "Тестовое письмо отправлено", color: "success" });
  } catch (caught) {
    error.value = errorMessage(caught, "Не удалось отправить тестовое письмо");
  } finally {
    testing.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div>
    <SectionHeader
      eyebrow="ОБЩИЕ НАСТРОЙКИ"
      title="Фиды и уведомления"
      description="Единые источники собственных каталогов и SMTP-параметры для всех разделов."
    >
      <template #actions>
        <UButton color="primary" icon="i-lucide-save" :loading="saving" @click="save()">
          Сохранить изменения
        </UButton>
      </template>
    </SectionHeader>

    <UAlert
      v-if="error"
      color="error"
      variant="subtle"
      icon="i-lucide-triangle-alert"
      :description="error"
      close
      class="page-error"
      @update:open="error = ''"
    />

    <div v-if="loading" class="loading-state">
      <span class="loading-logo"><UIcon name="i-lucide-settings-2" /></span>
      <p>Загружаем настройки…</p>
    </div>

    <div v-else-if="data" class="settings-page-grid">
      <OwnSiteSettingsPanel v-model="sites" />

      <aside class="settings-side-column">
        <SmtpSettingsPanel
          v-model="smtp"
          :password-set="data.smtp.password_set"
          :testing="testing"
          @test="testEmail"
        />
        <FeedStoragePanel :feeds="data.feed_storage" />
      </aside>
    </div>
  </div>
</template>

<style src="../assets/css/file-import.css"></style>
<style src="../assets/css/feed-comparison.css"></style>
<style src="../assets/css/settings.css"></style>
