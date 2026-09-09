<script setup lang="ts">
import { opencartApi, type AttributeShop, type AttributeShopForm } from "~/services/opencart.service";

const emit = defineEmits<{ synced: [] }>();
const shops = ref<AttributeShop[]>([]);
const loading = ref(true);
const busy = ref(false);
const runningId = ref<number | null>(null);
const error = ref("");
const notice = ref("");
const showForm = ref(false);
const editId = ref<number | null>(null);
const form = reactive<AttributeShopForm>({
  name: "", endpoint: "", api_key: "", language_code: "ru-ru", enabled: true,
});
const available = computed(() => shops.value.filter((shop) => shop.enabled));

function errorText(value: unknown): string {
  const candidate = value as { data?: { error?: unknown }; message?: unknown };
  if (typeof candidate?.data?.error === "string") return candidate.data.error;
  return "Не удалось выполнить запрос. Проверьте подключение и повторите.";
}
async function load() {
  try { shops.value = await opencartApi.list(); }
  catch (caught) { error.value = errorText(caught); }
  finally { loading.value = false; }
}
function edit(shop?: AttributeShop) {
  editId.value = shop?.id ?? null;
  Object.assign(form, {
    name: shop?.name ?? "", endpoint: shop?.endpoint ?? "", api_key: "",
    language_code: shop?.language_code ?? "ru-ru", enabled: shop?.enabled ?? true,
  });
  showForm.value = true;
  error.value = "";
}
async function save() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const saved = await opencartApi.save({ ...form }, editId.value);
    shops.value = [...shops.value.filter((s) => s.id !== saved.id), saved].sort((a, b) => a.id - b.id);
    form.api_key = "";
    showForm.value = false;
    notice.value = "Подключение сохранено. Теперь можно синхронизировать шаблоны.";
  } catch (caught) { error.value = errorText(caught); }
  finally { busy.value = false; }
}
async function synchronize(selected: AttributeShop[]) {
  if (busy.value || !selected.length) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  let completed = 0;
  const failed: string[] = [];
  try {
    for (const shop of selected) {
      runningId.value = shop.id;
      try {
        const result = await opencartApi.sync(shop.id);
        shops.value = shops.value.map((s) => s.id === shop.id ? result.shop : s);
        completed++;
      } catch (caught) {
        const message = errorText(caught);
        failed.push(shop.name + ": " + message);
        shops.value = shops.value.map((s) => s.id === shop.id ? { ...s, last_error: message } : s);
      }
    }
    if (completed) {
      notice.value = "Синхронизировано магазинов: " + completed + ".";
      emit("synced");
    }
    error.value = failed.join(" ");
  } finally { busy.value = false; runningId.value = null; }
}
async function remove(shop: AttributeShop) {
  if (!window.confirm("Удалить подключение «" + shop.name + "»? Импортированные шаблоны сохранятся.")) return;
  busy.value = true;
  error.value = "";
  try {
    await opencartApi.remove(shop.id);
    shops.value = shops.value.filter((s) => s.id !== shop.id);
    if (editId.value === shop.id) { showForm.value = false; form.api_key = ""; }
  } catch (caught) { error.value = errorText(caught); }
  finally { busy.value = false; }
}
function timeLabel(value: string) {
  return value ? new Date(value).toLocaleString("ru-RU") : "Ещё не синхронизирован";
}
onMounted(load);
</script>

<template>
  <UCard as="section" variant="outline" class="mb-5">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">Шаблоны из магазинов</h2>
        <p class="mt-1 text-sm text-muted">
          Подключите OpenCart или ocStore с модулем Attribut&amp;co. Категории станут шаблонами, значения — справочниками.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <UButton color="neutral" variant="soft" icon="i-lucide-plus" :disabled="busy" @click="edit()">Добавить магазин</UButton>
        <UButton icon="i-lucide-refresh-cw" :disabled="busy || loading || !available.length" :loading="busy && runningId !== null" @click="synchronize(available)">
          Синхронизировать все
        </UButton>
      </div>
    </div>
    <UAlert v-if="error" class="mt-4" color="error" variant="subtle" :description="error" />
    <UAlert v-if="notice" class="mt-4" color="success" variant="subtle" :description="notice" />

    <form v-if="showForm" class="mt-5 grid gap-4 rounded-lg border border-default p-4 sm:grid-cols-2" @submit.prevent="save">
      <UFormField label="Название магазина" required>
        <UInput v-model="form.name" class="w-full" maxlength="160" required :disabled="busy" />
      </UFormField>
      <UFormField label="URL API из настроек модуля" required>
        <UInput v-model="form.endpoint" class="w-full" type="url" placeholder="https://магазин.ru/index.php?route=extension/module/attribute_bridge" required :disabled="busy" />
      </UFormField>
      <UFormField label="Ключ доступа" :description="editId ? 'Оставьте пустым, чтобы сохранить действующий ключ.' : 'Скопируйте ключ, созданный модулем магазина.'" :required="!editId">
        <UInput v-model="form.api_key" class="w-full" type="password" autocomplete="new-password" :required="!editId" :disabled="busy" />
      </UFormField>
      <UFormField label="Язык магазина" description="Для русского языка обычно ru-ru.">
        <UInput v-model="form.language_code" class="w-full" maxlength="12" required :disabled="busy" />
      </UFormField>
      <UCheckbox v-model="form.enabled" label="Включить синхронизацию" :disabled="busy" />
      <div class="flex justify-end gap-2">
        <UButton color="neutral" variant="ghost" :disabled="busy" @click="showForm = false; form.api_key = ''">Отмена</UButton>
        <UButton type="submit" :loading="busy && runningId === null" :disabled="busy">Сохранить подключение</UButton>
      </div>
    </form>

    <p v-if="loading" class="mt-5 text-sm text-muted">Загрузка подключений…</p>
    <p v-else-if="!shops.length" class="mt-5 text-sm text-muted">
      Установите модуль API на магазин, затем добавьте его URL и ключ доступа.
    </p>
    <div v-else class="divide-y divide-default">
      <article v-for="shop in shops" :key="shop.id" class="flex flex-wrap items-start justify-between gap-4 py-4">
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="font-semibold">{{ shop.name }}</h3>
            <UBadge v-if="!shop.enabled" color="neutral" variant="subtle">Выключен</UBadge>
          </div>
          <p class="mt-1 break-all text-xs text-muted">{{ shop.endpoint }}</p>
          <p class="mt-1 text-sm text-muted">{{ timeLabel(shop.last_sync_at) }}</p>
          <p v-if="shop.last_report.created !== undefined" class="mt-2 text-sm">
            Создано: {{ shop.last_report.created }} · обновлено: {{ shop.last_report.updated }} · без изменений: {{ shop.last_report.unchanged }}.
            Добавлено значений: {{ shop.last_report.values_added }}.
          </p>
          <p v-if="shop.last_report.categories_missing || shop.last_report.fields_missing || shop.last_report.values_missing" class="mt-1 text-sm text-warning">
            На сайте больше нет категорий: {{ shop.last_report.categories_missing }}, атрибутов в категориях: {{ shop.last_report.fields_missing }}, значений: {{ shop.last_report.values_missing }}. Данные в сервисе сохранены.
          </p>
          <p v-if="shop.last_report.local_changes_preserved" class="mt-1 text-sm text-muted">
            Сохранено местных изменений: {{ shop.last_report.local_changes_preserved }}.
          </p>
          <p v-if="shop.last_error" class="mt-1 text-sm text-error">{{ shop.last_error }}</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <UButton size="sm" icon="i-lucide-refresh-cw" :loading="runningId === shop.id" :disabled="busy || !shop.enabled" @click="synchronize([shop])">Синхронизировать</UButton>
          <UButton size="sm" color="neutral" variant="soft" :disabled="busy" @click="edit(shop)">Настройки</UButton>
          <UButton size="sm" color="error" variant="ghost" icon="i-lucide-trash-2" :disabled="busy" :aria-label="'Удалить подключение ' + shop.name" @click="remove(shop)" />
        </div>
      </article>
    </div>
    <p v-if="shops.length" class="mt-2 text-xs text-muted">
      Синхронизация добавляет новые данные и сохраняет местные синонимы и правила. Удалённые на сайте данные остаются в шаблонах.
    </p>
  </UCard>
</template>
