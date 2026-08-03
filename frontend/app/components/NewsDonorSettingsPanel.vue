<script setup lang="ts">
import type { NewsMonitor } from "~/types/api";

const monitor = defineModel<NewsMonitor>({ required: true });
defineProps<{ connectionOptions: Array<{ label: string; value: string }> }>();

const scheduleOptions = [
  { label: "Каждый день", value: "daily" },
  { label: "Раз в неделю", value: "weekly" },
  { label: "Один раз", value: "once" },
];
const weekdayOptions = [
  "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье",
].map((label, value) => ({ label, value }));
</script>

<template>
  <UCard as="section" variant="outline" class="panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">ОСНОВНОЕ</p>
        <h2><strong>Донор и расписание</strong></h2>
      </div>
    </div>

    <div class="form-grid">
      <UFormField label="Бренд"><UInput v-model="monitor.brand" class="w-full" /></UFormField>
      <UFormField label="Сайт донора"><UInput v-model="monitor.site_url" placeholder="https://example.ru" class="w-full" /></UFormField>
      <UFormField label="Расписание"><USelect v-model="monitor.schedule_type" :items="scheduleOptions" class="w-full" /></UFormField>
      <UFormField label="Время"><UInput v-model="monitor.scan_time" type="time" class="w-full" /></UFormField>
      <UFormField v-if="monitor.schedule_type === 'weekly'" label="День недели">
        <USelect v-model="monitor.weekday" :items="weekdayOptions" class="w-full" />
      </UFormField>
      <UFormField v-if="monitor.schedule_type === 'once'" label="Дата запуска">
        <UInput v-model="monitor.next_run_at" type="datetime-local" class="w-full" />
      </UFormField>
      <UFormField label="Потоки"><UInput v-model.number="monitor.thread_count" type="number" :min="1" :max="16" class="w-full" /></UFormField>
      <UFormField>
        <template #label>
          <div class="flex gap-3">Подключение <USwitch v-model="monitor.auto_connection_fallback" /><strong>Авто</strong></div>
        </template>
        <USelect v-model="monitor.connection_method" :items="connectionOptions" class="w-full" />
      </UFormField>
      <UFormField label="Стартовые URL" class="field-span-2">
        <UTextarea
          :model-value="monitor.start_urls.join('\n')"
          :rows="5"
          class="w-full"
          placeholder="По одной ссылке на строку"
          @update:model-value="monitor.start_urls = String($event).split(/\r?\n/).map((item) => item.trim()).filter(Boolean)"
        />
      </UFormField>
    </div>
  </UCard>
</template>
