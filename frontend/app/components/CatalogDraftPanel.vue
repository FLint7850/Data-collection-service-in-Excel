<script setup lang="ts">
import type { AttributeProduct } from "~/types/attribute-assistant";
import { attributeAssistantService as api } from "~/services/attribute-assistant.service";
import { errorMessage } from "~/utils/format";

const props = defineProps<{ product: AttributeProduct }>();
const emit = defineEmits<{ saved: [] }>();
const toast = useToast();
const busy = ref(false);
const error = ref("");
const shops = ref<Array<{ id: number; name: string }>>([]);
const preflight = ref<Awaited<ReturnType<typeof api.catalogPreflight>> | null>(null);
const withAttributes = ref(true);
const draft = reactive({
  name: "", model: "", brand: "", category_name: "", price: "",
  description: "", images: "", shop_id: null as number | null,
});

function syncDraft() {
  const catalog = props.product.catalog_draft;
  draft.name = props.product.name;
  draft.model = props.product.model;
  draft.brand = props.product.brand;
  draft.category_name = props.product.category_name;
  draft.price = catalog?.price || "";
  draft.description = catalog?.description || "";
  draft.images = (catalog?.images || []).join("\n");
  draft.shop_id = catalog?.shop_id || null;
}

watch(() => props.product, syncDraft, { immediate: true });

onMounted(async () => {
  try {
    shops.value = (await api.catalogShops()).items;
    await check();
  } catch (caught) {
    error.value = errorMessage(caught);
  }
});

async function check() {
  try {
    preflight.value = await api.catalogPreflight(props.product.id);
  } catch (caught) {
    error.value = errorMessage(caught);
  }
}

async function save() {
  busy.value = true;
  error.value = "";
  try {
    await api.catalogUpdate(props.product.id, {
      ...draft,
      images: draft.images.split(/\r?\n/).map((url) => url.trim()).filter(Boolean),
      expected_version: props.product.version,
    });
    toast.add({ color: "success", title: "Черновик сохранён" });
    emit("saved");
    await check();
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    busy.value = false;
  }
}

async function downloadAttributes() {
  busy.value = true;
  error.value = "";
  try {
    const result = await api.catalogAttributesExport(props.product.batch_id!, props.product.id);
    window.location.assign(result.download_url);
  } catch (caught) {
    error.value = errorMessage(caught);
  } finally {
    busy.value = false;
  }
}

async function download() {
  busy.value = true;
  error.value = "";
  try {
    const result = await api.catalogExport(props.product.batch_id!, [props.product.id], withAttributes.value);
    window.location.assign(result.download_url);
    toast.add({ color: "success", title: "CSV подготовлен. Импортируйте его в CSV Price Pro после проверки." });
  } catch (caught) {
    error.value = errorMessage(caught);
    await check();
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UCard variant="outline" class="mb-4">
    <template #header>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="font-semibold">Черновик нового товара</h3>
          <p class="text-sm text-muted">Цена, изображения и подготовка CSV Price Pro</p>
        </div>
        <UBadge :color="preflight?.ok ? 'success' : 'warning'" variant="subtle">
          {{ preflight?.ok ? 'Структура проверена' : 'Требуется проверка' }}
        </UBadge>
      </div>
    </template>
    <div class="grid gap-4 md:grid-cols-2">
      <UFormField label="Название"><UInput v-model="draft.name" class="w-full" /></UFormField>
      <UFormField label="Модель"><UInput v-model="draft.model" class="w-full" /></UFormField>
      <UFormField label="Производитель"><UInput v-model="draft.brand" class="w-full" /></UFormField>
      <UFormField label="Категория назначения"><UInput v-model="draft.category_name" class="w-full" /></UFormField>
      <UFormField label="Цена"><UInput v-model="draft.price" class="w-full" placeholder="12345.0000" /></UFormField>
      <UFormField label="Целевой магазин (справочно)">
        <USelect v-model="draft.shop_id" :items="[{ label: 'Выбрать при импорте CSV', value: null }, ...shops.map((shop) => ({ label: shop.name, value: shop.id }))]" class="w-full" />
      </UFormField>
      <UFormField label="Описание"><UTextarea v-model="draft.description" :rows="3" class="w-full" /></UFormField>
      <UFormField label="Фото по HTTPS, по одной ссылке в строке" description="Первая — главная. Не загружаются до фактического импорта в магазин.">
        <UTextarea v-model="draft.images" :rows="4" class="w-full" />
      </UFormField>
    </div>
    <div v-if="preflight" class="mt-4 rounded-lg border border-default p-3 text-sm">
      <p>Поля шаблона: {{ preflight.total_fields || 0 }}; пустых: {{ preflight.blank_fields || 0 }}.</p>
      <p v-for="item in preflight.errors" :key="item" class="text-error mt-1">{{ item }}</p>
      <p v-for="item in preflight.warnings" :key="item" class="text-warning mt-1">{{ item }}</p>
    </div>
    <UAlert v-if="error" class="mt-4" color="error" variant="subtle" :description="error" />
    <div class="mt-4 flex flex-wrap items-center gap-3">
      <UButton icon="i-lucide-save" :loading="busy" @click="save">Сохранить черновик</UButton>
      <UButton color="neutral" variant="soft" :disabled="busy" @click="check">Проверить шаблон</UButton>
      <UCheckbox v-model="withAttributes" label="Включить _ATTRIBUTES_ в CSV" />
      <UButton icon="i-lucide-file-down" color="primary" :loading="busy" :disabled="!preflight?.ok" @click="download">Подготовить CSV для импорта</UButton>
      <UButton color="neutral" variant="soft" icon="i-lucide-list-checks" :disabled="busy || !preflight?.ok" @click="downloadAttributes">Отдельный CSV атрибутов</UButton>
    </div>
    <p class="mt-2 text-sm text-muted">CSV загружает изображения только если это настроено в вашем профиле CSV Price Pro. Кнопка не отправляет товар в магазин.</p>
  </UCard>
</template>
