<script setup lang="ts">
import { newsService } from "~/services/news.service";
import type { NewsConfiguration, OwnSite, SmtpSettings } from "~/types/api";
import { errorMessage, formatFileSize } from "~/utils/format";

definePageMeta({
  title: "Настройки",
  eyebrow: "ФИДЫ · УВЕДОМЛЕНИЯ",
});

const toast = useToast();
const data = ref<NewsConfiguration | null>(null);
const loading = ref(true);
const saving = ref(false);
const testing = ref(false);
const showPassword = ref(false);
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

function addSite() {
  sites.value.push({
    name: "",
    feed_url: "",
    feed_generate_url: "",
  });
}

function removeSite(index: number) {
  sites.value.splice(index, 1);
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
      <UCard as="section" variant="outline" class="panel settings-main-panel">
        <div class="panel-header">
          <div>
            <p class="eyebrow">ИСТОЧНИКИ ДАННЫХ</p>
            <h3>Фиды моих сайтов</h3>
            <p>Используются в мониторинге новинок, импорте файлов и сравнении поставщиков.</p>
          </div>
          <UButton color="neutral" variant="soft" icon="i-lucide-plus" @click="addSite">
            Добавить фид
          </UButton>
        </div>

        <div v-if="sites.length" class="site-settings-list">
          <UCard
            v-for="(site, index) in sites"
            :key="index"
            as="article"
            variant="subtle"
            class="site-settings-card"
            :ui="{ body: 'site-settings-card-body' }"
          >
            <span class="feed-card-icon mint-icon"><UIcon name="i-lucide-store" /></span>
            <div class="site-settings-fields">
              <UFormField label="Название">
                <UInput v-model="site.name" placeholder="Мой магазин" class="w-full" />
              </UFormField>
              <UFormField label="XML-фид">
                <UInput v-model="site.feed_url" type="url" placeholder="https://example.ru/feed.xml" class="w-full" />
              </UFormField>
              <UFormField label="Ссылка генерации">
                <UInput v-model="site.feed_generate_url" type="url" placeholder="https://example.ru/index.php" class="w-full" />
              </UFormField>
            </div>
            <UButton
              color="error"
              variant="ghost"
              icon="i-lucide-trash-2"
              aria-label="Удалить фид"
              @click="removeSite(index)"
            />
          </UCard>
        </div>

        <EmptyState
          v-else
          icon="i-lucide-store"
          title="Нет фидов сайтов"
          description="Добавьте XML-фид хотя бы одного собственного магазина."
        >
          <UButton color="primary" variant="soft" icon="i-lucide-plus" @click="addSite">
            Добавить фид
          </UButton>
        </EmptyState>
      </UCard>

      <aside class="settings-side-column">
        <UCard as="section" variant="outline" class="panel">
          <div class="panel-header">
            <div>
              <p class="eyebrow">УВЕДОМЛЕНИЯ</p>
              <h3>SMTP-почта</h3>
              <p>Отправка результатов мониторинга ответственным сотрудникам.</p>
            </div>
            <span class="settings-icon amber-icon"><UIcon name="i-lucide-mail" /></span>
          </div>

          <div class="form-stack smtp-form">
            <div class="form-grid">
              <UFormField label="SMTP-сервер">
                <UInput v-model="smtp.host" placeholder="smtp.yandex.ru" class="w-full" />
              </UFormField>
              <UFormField label="Порт">
                <UInput v-model.number="smtp.port" type="number" :min="1" :max="65535" class="w-full" />
              </UFormField>
              <UFormField label="Защита">
                <USelect
                  v-model="smtp.security"
                  :items="[
                    { label: 'SSL / TLS', value: 'ssl' },
                    { label: 'STARTTLS', value: 'starttls' },
                    { label: 'Без шифрования', value: 'none' },
                  ]"
                  class="w-full"
                />
              </UFormField>
              <UFormField label="Логин">
                <UInput v-model="smtp.username" type="email" autocomplete="off" class="w-full" />
              </UFormField>
            </div>
            <UFormField
              label="Пароль приложения"
              :description="data.smtp.password_set ? 'Пароль уже сохранён. Оставьте поле пустым, чтобы не менять.' : ''"
            >
              <UInput
                v-model="smtp.password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="new-password"
                class="w-full"
              >
                <template #trailing>
                  <UButton
                    color="neutral"
                    variant="link"
                    :icon="showPassword ? 'i-lucide-eye-off' : 'i-lucide-eye'"
                    @click="showPassword = !showPassword"
                  />
                </template>
              </UInput>
            </UFormField>
            <UFormField label="Получатели" description="По одному адресу на строку">
              <UTextarea
                v-model="smtp.recipients"
                :rows="4"
                placeholder="manager@example.ru"
                class="w-full"
              />
            </UFormField>
          </div>

          <div class="settings-actions">
            <UButton
              color="neutral"
              variant="soft"
              icon="i-lucide-send"
              :loading="testing"
              @click="testEmail"
            >
              Отправить тест
            </UButton>
          </div>
        </UCard>

        <UCard as="section" variant="outline" class="panel">
          <div class="panel-header">
            <div>
              <p class="eyebrow">ХРАНИЛИЩЕ</p>
              <h3>Последние фиды</h3>
            </div>
            <span class="settings-icon blue-icon"><UIcon name="i-lucide-database" /></span>
          </div>

          <div v-if="data.feed_storage.length" class="stored-feed-list">
            <a
              v-for="feed in data.feed_storage"
              :key="`${feed.source}-${feed.filename}`"
              :href="`/api/news/feeds/${encodeURIComponent(feed.source || '')}/${encodeURIComponent(feed.filename || '')}`"
              class="stored-feed-item"
            >
              <span><UIcon name="i-lucide-file-code-2" /></span>
              <div>
                <strong>{{ feed.label || feed.filename }}</strong>
                <small>{{ formatFileSize(feed.size) }} · {{ feed.created_at || "сохранённый снимок" }}</small>
              </div>
              <UIcon name="i-lucide-download" />
            </a>
          </div>
          <p v-else class="inline-empty">Снимки фидов появятся после первого мониторинга.</p>
        </UCard>
      </aside>
    </div>
  </div>
</template>
