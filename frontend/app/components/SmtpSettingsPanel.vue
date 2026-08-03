<script setup lang="ts">
export interface SmtpFormModel {
  host: string;
  port: number;
  security: string;
  username: string;
  password: string;
  recipients: string;
}

defineProps<{ passwordSet?: boolean; testing?: boolean }>();
const smtp = defineModel<SmtpFormModel>({ required: true });
const emit = defineEmits<{ test: [] }>();
const showPassword = ref(false);
</script>

<template>
  <UCard as="section" variant="outline" class="panel">
    <div class="panel-header">
      <div>
        <p class="eyebrow">УВЕДОМЛЕНИЯ</p>
        <h2><strong>SMTP-почта</strong></h2>
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
        :description="passwordSet ? 'Пароль уже сохранён. Оставьте поле пустым, чтобы не менять.' : ''"
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
              aria-label="Показать или скрыть пароль"
              @click="showPassword = !showPassword"
            />
          </template>
        </UInput>
      </UFormField>
      <UFormField label="Получатели" description="По одному адресу на строку">
        <UTextarea v-model="smtp.recipients" :rows="4" placeholder="manager@example.ru" class="w-full" />
      </UFormField>
    </div>

    <div class="settings-actions">
      <UButton
        color="neutral"
        variant="soft"
        icon="i-lucide-send"
        :loading="testing"
        @click="emit('test')"
      >
        Отправить тест
      </UButton>
    </div>
  </UCard>
</template>
