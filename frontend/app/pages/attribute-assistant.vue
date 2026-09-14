<script setup lang="ts">
import {
  attributeValuesMatch,
  hasPendingProposal,
  displayedProposal,
  displayedProposalConfidence,
  displayedProposalSource,
  finalAllowedMenuKey,
  formatHistoryDate,
  inputModeItems,
  originalValueHints,
  isTechnicalDash,
  processingModeItems,
  selectedFinalParts,
  selectedFinalValue,
  sourceKind,
  sourceKindLabel,
  sourceStatusText,
  sourceTitle,
  templateFieldTypeItems,
  templateUpdateModeItems,
  unknownAllowedMenuKey,
  unknownSelectionKey,
  valueStatusColor,
  valueStatusLabel,
} from "~/utils/attribute-assistant";

definePageMeta({
  title: "Атрибуты",
  eyebrow: "Автоматическое заполнение",
});

const assistant = useAttributeAssistant();

const allowedValuesState = useAttributeAllowedValues();

const templatesState = useAttributeTemplates(assistant);

const reviewState = useAttributeReview(
    assistant,
    allowedValuesState,
);

const routeState = useAttributeAssistantRoute(
    assistant,
    templatesState,
    reviewState,
);

/**
 * Основное состояние страницы.
 */
const {
  loading,
  busy,
  error,
  tab,
  inputMode,
  workspace,
  templates,
  selectedTemplateId,
  productFile,
  urlsText,
  processingMode,
  chatGpt,
  deviceLogin,
  appDialog,
  templateSelectItems,
  productTemplateItems,
  loadWorkspace,
  loadChatGpt,
  loginChatGpt,
  logoutChatGpt,
} = assistant;

/**
 * Шаблоны.
 */
const {
  templateFile,
  templateDetails,
  templatePreview,
  templateUpdateFile,
  templateUpdateMode,
  templateRevisions,
  templateRevisionsLoading,
  mappingRules,
  valueMappingRules,
  loadedTemplateFieldIds,
  loadingTemplateFieldIds,
  templateFieldQueries,
  templateFieldMatchedCounts,
  showNewTemplateField,
  allowedValueEditor,
  templateFieldEditor,
  fieldValueEditor,
  templateForm,
  newTemplateField,
  previewNewTemplate,
  importTemplate,
  openTemplate,
  onShopSynced,
  handleTemplateHistoryOpen,
  handleTemplateFieldOpen,
  queueTemplateFieldValueSearch,
  updateTemplateCsv,
  copyCurrentTemplate,
  toggleTemplateActive,
  removeTemplate,
  removeMapping,
  removeValueMapping,
  createTemplateField,
  removeTemplateField,
  restoreTemplateVersion,
  editField,
  addTemplateFieldSynonym,
  removeTemplateFieldSynonym,
  saveTemplateFieldEdit,
  addFieldValue,
  saveFieldValue,
  editAllowedValue,
  closeAllowedValueEditor,
  addAllowedValueSynonym,
  removeAllowedValueSynonym,
  saveAllowedValue,
  allowedValueMenuItems,
} = templatesState;

/**
 * Проверка товаров / batch / доноры / атрибуты.
 */
const {
  selectedBatch,
  selectedProduct,
  loadingProductId,
  selectedDonors,
  unknownSelections,
  donorUrlOverrides,
  historyItems,
  batchOperation,
  productQuery,
  productStatusFilter,
  attributeStatusFilter,
  displayedDonors,
  selectedDonorRows,
  filteredProducts,
  productStatusItems,
  attributeValues,
  filteredAttributeValues,
  attributeStatusItems,
  valuesByGroup,
  batchOperationRunning,
  batchChatGptLoading,
  displayedProductSources,
  productListIndicator,
  currentValueCaption,
  createBatch,
  processAllProducts,
  askChatGptForAllProducts,
  openBatch,
  removeBatch,
  openProduct,
  toggleDonor,
  moveDonor,
  processDonors,
  useSimilar,
  askChatGpt,
  assignCurrentTemplate,
  exportReadyOnly,
  restoreHistory,
  valueAction,
  removeOutsideTemplateValue,
  selectFinalValue,
  addUnknown,
  rememberUnknownValue,
  bulk,
  exportBatch,
} = reviewState;

/**
 * Поиск и lazy-loading значений справочника.
 */
const {
  searchingAllowedValueIds,
  optionsFor,
  queueAllowedSearch,
  allowedSelectRef,
  handleAllowedMenuOpen,
} = allowedValuesState;

/**
 * Роутинг.
 */
const {
  mainTabItems,
  applyAssistantRoute,
  changeMainTab,
  useTemplateForNewBatch,
} = routeState;

/**
 * Первичная загрузка страницы.
 */
onMounted(async () => {
  try {
    await Promise.all([
      loadWorkspace(),
      loadChatGpt(),
    ]);
    await applyAssistantRoute();
  } finally {
    loading.value = false;
  }
});

/**
 * Очистка polling, debounce, listeners и timers.
 */
onBeforeUnmount(() => {
  routeState.dispose();
  reviewState.dispose();
  templatesState.dispose();
  assistant.dispose();
});
</script>

<template>
  <div>
    <SectionHeader
      eyebrow="АВТОМАТИЧЕСКОЕ ЗАПОЛНЕНИЕ"
      title="Атрибуты"
      description="Загрузите товары, выберите доноров — сервис найдёт страницы по модели и подготовит значения к проверке."
    >
      <template #actions>
        <UTooltip text="Прокси используется только для подключения ChatGPT">
          <UBadge
            :color="chatGpt?.authenticated ? 'success' : 'neutral'"
            variant="subtle"
            size="lg"
            :icon="chatGpt?.authenticated ? 'i-lucide-circle-check' : 'i-lucide-circle-off'"
          >
            ChatGPT {{ chatGpt?.authenticated ? "подключён" : "не подключён" }}
          </UBadge>
        </UTooltip>
      </template>
    </SectionHeader>

    <UTabs
      :model-value="tab"
      :items="mainTabItems"
      :content="false"
      variant="link"
      size="lg"
      class="aa-tabs"
      aria-label="Разделы вкладки"
      @update:model-value="changeMainTab"
    />

    <UAlert
      v-if="error"
      color="error"
      variant="subtle"
      icon="i-lucide-circle-alert"
      :description="error"
      orientation="horizontal"
      :close="{ color: 'error', variant: 'ghost' }"
      class="aa-alert"
      @update:open="(open) => { if (!open) error = '' }"
    />

    <USkeleton v-if="loading" class="aa-loading h-24 w-full" />

    <template v-else-if="tab === 'start'">
      <div class="aa-metrics aa-dashboard">
        <MetricCard label="Товаров в работе" :value="workspace.dashboard.products" icon="i-lucide-package-search" tone="blue" />
        <MetricCard label="Готово" :value="workspace.dashboard.ready" icon="i-lucide-circle-check-big" tone="mint" />
        <MetricCard label="Конфликтов" :value="workspace.dashboard.conflicts" icon="i-lucide-triangle-alert" tone="red" />
        <MetricCard label="Активных шаблонов" :value="workspace.dashboard.active_templates" icon="i-lucide-layout-template" tone="purple" />
      </div>
      <div class="aa-grid aa-grid--start">
        <UCard as="section" variant="outline" class="aa-card aa-card--main">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Шаг 1</span>
              <h2>Что обрабатываем?</h2>
            </div>
            <UTabs
              v-model="inputMode"
              :items="inputModeItems"
              :content="false"
              size="sm"
              class="aa-switch"
            />
          </div>

          <UFileUpload
            v-if="inputMode === 'csv'"
            v-model="productFile"
            class="aa-drop"
            accept=".csv,text/csv"
            icon="i-lucide-upload-cloud"
            :label="productFile?.name || 'Выберите CSV с товарами'"
            description="CP1251 или UTF-8 · разделитель определяется автоматически"
            :preview="false"
          />
          <UFormField
            v-else
            label="Ссылки на товары — по одной в строке"
            description="Категорию попробуем определить по странице. Если не получится — используем выбранный ниже шаблон."
          >
            <UTextarea v-model="urlsText" :rows="7" placeholder="https://site.ru/product/model" class="w-full" />
          </UFormField>

          <div class="aa-form-row">
            <UFormField label="Шаблон категории">
              <USelect v-model="selectedTemplateId" :items="templateSelectItems" class="w-full" />
            </UFormField>
            <UFormField label="Режим обработки">
              <USelect v-model="processingMode" :items="processingModeItems" class="w-full" />
            </UFormField>
          </div>

          <UButton
            color="primary"
            size="lg"
            trailing-icon="i-lucide-arrow-right"
            class="aa-create-action"
            :loading="busy === 'batch-import' || busy === 'url-import'"
            :disabled="Boolean(busy)"
            @click="createBatch"
          >
            Создать обработку
          </UButton>
        </UCard>

        <aside class="aa-side">
          <UCard as="section" variant="outline" class="aa-card">
            <div class="aa-card-head">
              <div>
                <span class="aa-step">ChatGPT</span>
                <h2>Умные подсказки</h2>
              </div>
              <UBadge :color="chatGpt?.authenticated ? 'success' : 'neutral'" variant="subtle">
                {{ chatGpt?.authenticated ? "Готов" : "Отключён" }}
              </UBadge>
            </div>
            <p class="aa-muted" v-if="!chatGpt?.available">{{ chatGpt?.error || "Codex App Server недоступен" }}</p>
            <template v-else-if="chatGpt?.authenticated">
              <p class="aa-muted">{{ chatGpt.account?.email || "Авторизация ChatGPT активна" }}</p>
              <UButton color="neutral" variant="soft" @click="logoutChatGpt">Отключить аккаунт</UButton>
            </template>
            <template v-else>
              <p class="aa-muted">Авторизация через код устройства. Ключ API не нужен.</p>
              <UButton color="neutral" variant="soft" :disabled="busy === 'chatgpt-login'" @click="loginChatGpt">
                Подключить ChatGPT
              </UButton>
            </template>
            <div v-if="deviceLogin" class="aa-device-code">
              <small>Введите код на открывшейся странице</small>
              <strong>{{ deviceLogin.user_code }}</strong>
              <UButton as="a" color="primary" variant="link" trailing-icon="i-lucide-external-link" :href="deviceLogin.verification_url" target="_blank" rel="noopener">Открыть страницу входа</UButton>
            </div>
            <p class="aa-privacy">При ручном запуске в ChatGPT передаются точная URL карточки и видимый текст страницы. CSV-файл и данные других товаров не передаются.</p>
          </UCard>

          <UCard as="section" variant="outline" class="aa-card">
            <div class="aa-card-head"><h2>Последние обработки</h2></div>
            <article
              v-for="batch in workspace.batches.slice(0, 5)"
              :key="batch.id"
              class="aa-history-entry"
            >
              <UButton color="neutral" variant="ghost" block class="aa-history" @click="openBatch(batch.id)">
                <span><strong>{{ batch.name }}</strong><small>{{ batch.template.category }}</small></span>
                <b>{{ batch.summary.needs_review }}</b>
              </UButton>
              <UButton
                color="error"
                variant="ghost"
                icon="i-lucide-trash-2"
                square

                :loading="busy === `batch-remove-${batch.id}`"
                :title="`Удалить обработку «${batch.name}»`"
                :aria-label="`Удалить обработку «${batch.name}»`"
                @click="removeBatch(batch)"
              />
            </article>
            <p v-if="!workspace.batches.length" class="aa-muted">Пока ничего не загружено.</p>
          </UCard>
        </aside>
      </div>
    </template>



    <template v-else-if="tab === 'templates'">
      <AttributeShopSync @synced="onShopSynced" />
      <div class="aa-grid aa-grid--templates">
        <UCard as="section" variant="outline" class="aa-card">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Импорт</span>
              <h2>Новый шаблон категории</h2>
            </div>
          </div>
          <p class="aa-muted">Каждый столбец — атрибут. Формат заголовка: «Атрибут (Группа)». Строки столбца станут разрешёнными значениями.</p>
          <div class="aa-form-stack">
            <UFormField label="CSV шаблона">
              <UFileUpload
                v-model="templateFile"
                accept=".csv,text/csv"
                variant="button"
                label="Выбрать CSV"
                class="w-full"
              />
            </UFormField>
            <UFormField label="Категория" required>
              <UInput v-model="templateForm.category" placeholder="Бытовая техника → Стиральные машины" class="w-full" />
            </UFormField>
            <UFormField label="Название шаблона" required>
              <UInput v-model="templateForm.name" placeholder="Стиральные машины" class="w-full" />
            </UFormField>
            <UFormField label="Тип товара" hint="необязательно">
              <UInput v-model="templateForm.product_type" placeholder="Стиральная машина" class="w-full" />
            </UFormField>
          </div>
          <div class="aa-inline-actions">
            <UButton color="neutral" variant="soft" icon="i-lucide-file-search" :loading="busy === 'template-preview'" :disabled="Boolean(busy)" @click="previewNewTemplate">Проверить файл</UButton>
            <UButton color="primary" icon="i-lucide-file-plus-2" :loading="busy === 'template-import'" :disabled="Boolean(busy) || !templatePreview?.can_import" @click="importTemplate">
              Подтвердить импорт
            </UButton>
          </div>
          <div v-if="templatePreview" class="aa-preview">
            <strong>Строк: {{ templatePreview.rows }} · атрибутов: {{ templatePreview.fields.length }}</strong>
            <span v-if="templatePreview.removed_fields.length">Будут отсутствовать в файле: {{ templatePreview.removed_fields.length }}</span>
            <p v-for="warning in templatePreview.warnings" :key="warning" class="aa-warning-text">{{ warning }}</p>
          </div>
        </UCard>

        <UCard as="section" variant="outline" class="aa-card aa-card--main">
          <div class="aa-card-head">
            <div>
              <span class="aa-step">Справочник</span>
              <h2>Шаблоны категорий</h2>
            </div>
            <UBadge color="neutral" variant="subtle">{{ templates.length }}</UBadge>
          </div>
          <div v-if="templates.length" class="aa-template-list">
            <article v-for="item in templates" :key="item.id" class="aa-template-row">
              <span class="aa-template-icon"><UIcon name="i-lucide-folders" /></span>
              <span>
                <strong>{{ item.name }}</strong>
                <small>{{ item.category }}</small>
              </span>
              <b>{{ item.field_count }} атр.</b>
              <span class="aa-template-row-actions">
                <UButton
                  color="neutral"
                  variant="soft"
                  icon="i-lucide-folder-open"
                  :loading="busy === `template-open-${item.id}`"
                  @click="openTemplate(item.id)"
                />
                <UButton
                  color="error"
                  variant="ghost"
                  icon="i-lucide-trash-2"
                  :loading="busy === `template-remove-${item.id}`"
                  @click="removeTemplate(item)"
                />
              </span>
            </article>
          </div>
          <EmptyState
            v-else
            icon="i-lucide-layout-template"
            title="Сначала импортируйте шаблон"
            description="Он задаст порядок, группы, типы и разрешённые значения."
          />
        </UCard>
      </div>

      <UCard as="section" variant="outline" v-if="templateDetails" class="aa-card aa-template-editor">
        <div class="aa-card-head">
          <div>
            <span class="aa-step">Редактор</span>
            <h2>{{ templateDetails.name }}</h2>
            <p>{{ templateDetails.category }} · {{ templateDetails.field_count }} атрибутов</p>
          </div>
          <div class="aa-inline-actions">
            <UButton color="neutral" variant="soft" @click="copyCurrentTemplate">Создать копию</UButton>
            <UButton
              :color="templateDetails.is_active ? 'error' : 'success'"
              variant="soft"
              :icon="templateDetails.is_active ? 'i-lucide-circle-off' : 'i-lucide-circle-check'"
              :loading="busy === 'template-active'"
              @click="toggleTemplateActive"
            >
              {{ templateDetails.is_active ? "Деактивировать" : "Активировать" }}
            </UButton>
            <UButton color="primary" @click="useTemplateForNewBatch(templateDetails.id)">Использовать</UButton>
            <UButton
              color="error"
              variant="soft"
              icon="i-lucide-trash-2"
              :loading="busy === `template-remove-${templateDetails.id}`"
              @click="removeTemplate(templateDetails)"
            >Удалить шаблон</UButton>
          </div>
        </div>

        <div class="aa-template-update">
          <UFormField label="Обновить из CSV">
            <UFileUpload
              v-model="templateUpdateFile"
              accept=".csv,text/csv"
              variant="button"
              label="Выбрать CSV"
              class="w-full"
            />
          </UFormField>
          <UFormField label="Режим обновления">
            <USelect v-model="templateUpdateMode" :items="templateUpdateModeItems" class="w-full" />
          </UFormField>
          <UButton color="primary" icon="i-lucide-refresh-cw" :loading="busy === 'template-update'" :disabled="!templateUpdateFile" @click="updateTemplateCsv">Проверить diff и обновить</UButton>
        </div>
        <div class="aa-template-field-toolbar">
          <div>
            <strong>Поля шаблона</strong>
            <small>Добавляйте, редактируйте и удаляйте атрибуты шаблона.</small>
          </div>
          <UButton color="primary" @click="showNewTemplateField = !showNewTemplateField">
            {{ showNewTemplateField ? "Отмена" : "+ Добавить атрибут" }}
          </UButton>
        </div>

        <form v-if="showNewTemplateField" class="aa-new-template-field" @submit.prevent="createTemplateField">
          <UFormField label="Группа" required><UInput v-model="newTemplateField.group_name" class="w-full" /></UFormField>
          <UFormField label="Название" required><UInput v-model="newTemplateField.name" class="w-full" /></UFormField>
          <UFormField label="Тип значения">
            <USelect v-model="newTemplateField.value_type" :items="templateFieldTypeItems" class="w-full" />
          </UFormField>
          <UCheckbox v-model="newTemplateField.is_required" label="Обязательный" />
          <UCheckbox v-model="newTemplateField.is_composite" label="Составной через /" />
          <UButton color="primary" icon="i-lucide-plus" type="submit" :loading="busy === 'field-create'">Добавить</UButton>
        </form>


        <div class="aa-template-fields">
          <UCollapsible
            v-for="field in templateDetails.fields"
            :key="field.id"
            class="aa-template-field"
            @update:open="handleTemplateFieldOpen($event, field.id)"
          >
            <template #default="{ open }">
              <UButton color="neutral" variant="ghost" block class="aa-template-field-trigger">
                <span class="aa-template-field-title">
                  <strong>{{ field.group_name }} · {{ field.name }}</strong>
                  <small>
                    {{ field.value_type }} · {{ field.allowed_values_count }} значений
                    <template v-if="field.synonyms?.length"> · {{ field.synonyms.length }} синон.</template>
                  </small>
                </span>
                <UIcon name="i-lucide-chevron-down" :class="['aa-template-field-chevron', { open }]" />
              </UButton>
            </template>
            <template #content>
              <div class="aa-template-field-content">
                <div class="aa-inline-actions aa-template-field-actions">
                  <UButton color="neutral" variant="soft" icon="i-lucide-pencil" @click="editField(field)">Изменить</UButton>
                  <UButton color="primary" variant="soft" icon="i-lucide-plus" @click="addFieldValue(field)">Добавить значение</UButton>
                  <UButton
                    color="error"
                    variant="soft"
                    icon="i-lucide-trash-2"
                    :loading="busy === `field-remove-${field.id}`"
                    @click="removeTemplateField(field)"
                  >Удалить</UButton>
                </div>
                <div class="aa-value-chips">
                  <div class="aa-template-value-tools">
                    <UInput
                      :value="templateFieldQueries[field.id] || ''"
                      type="search"
                      icon="i-lucide-search"
                      placeholder="Найти значение или синоним…"
                      class="w-full"
                      @input="queueTemplateFieldValueSearch(field.id, $event)"
                    />
                    <small v-if="templateFieldQueries[field.id]">Найдено: {{ templateFieldMatchedCounts[field.id] ?? 0 }}</small>
                    <small v-else>Показаны первые {{ Math.min(field.allowed_values.length, 80) }} из {{ field.allowed_values_count }}</small>
                  </div>
                  <div v-if="loadingTemplateFieldIds.has(field.id)" class="aa-template-values-loading">
                    <USkeleton v-for="index in 4" :key="index" class="h-8 w-28 rounded-full" />
                  </div>
                  <div
                    v-for="allowed in field.allowed_values.slice(0, 80)"
                    :key="allowed.id"
                    :class="['aa-value-chip', { inactive: !allowed.is_active }]"
                  >
                    <UButton
                      color="neutral"
                      variant="soft"
                      class="aa-value-chip-main"
                      :title="allowed.synonyms?.length ? `Синонимы: ${allowed.synonyms.join(', ')}` : 'Изменить значение'"
                      @click="editAllowedValue(field.name, allowed)"
                    >
                      <span>{{ allowed.value }}</span>
                      <UBadge v-if="allowed.is_combination" color="neutral" variant="subtle" size="xs">комбинация</UBadge>
                      <UBadge v-if="allowed.synonyms?.length" color="primary" variant="subtle" size="xs">{{ allowed.synonyms.length }} синон.</UBadge>
                    </UButton>
                    <UDropdownMenu :items="allowedValueMenuItems(field.name, allowed)">
                      <UButton
                        color="neutral"
                        variant="ghost"
                        icon="i-lucide-ellipsis"
                        square
                        aria-label="Действия со значением"
                      />
                    </UDropdownMenu>
                  </div>
                  <EmptyState
                    v-if="loadedTemplateFieldIds.has(field.id) && !field.allowed_values.length"
                    icon="i-lucide-search-x"
                    :title="templateFieldQueries[field.id] ? 'Совпадений не найдено' : 'Разрешённых значений пока нет'"
                    description="Измените запрос или добавьте новое значение в справочник."
                  />
                </div>
              </div>
            </template>
          </UCollapsible>
        </div>
        <SettingsCollapsible class="aa-template-history" content-class="aa-template-history-content">
          <template #label>
            <span>Сохранённые сопоставления доноров</span>
            <UBadge color="neutral" variant="subtle" size="sm">{{ mappingRules.length }}</UBadge>
          </template>
          <div v-for="rule in mappingRules" :key="rule.id" class="aa-history-row">
            <span><strong>{{ rule.donor_name }}: {{ rule.donor_attribute_name }}</strong><small>→ {{ rule.field_name }}</small></span>
            <UButton color="error" variant="ghost" icon="i-lucide-trash-2" :loading="busy === `mapping-remove-${rule.id}`" @click="removeMapping(rule.id)">Удалить</UButton>
          </div>
          <EmptyState
            v-if="!mappingRules.length"
            icon="i-lucide-git-compare-arrows"
            title="Сопоставлений пока нет"
            description="Правила появятся после действия «Запомнить и применить» у характеристики донора."
          />
        </SettingsCollapsible>
        <SettingsCollapsible class="aa-template-history" content-class="aa-template-history-content">
          <template #label>
            <span>Сопоставления значений доноров</span>
            <UBadge color="neutral" variant="subtle" size="sm">{{ valueMappingRules.length }}</UBadge>
          </template>
          <div v-for="rule in valueMappingRules" :key="rule.id" class="aa-history-row">
            <span>
              <strong>{{ rule.donor_name }}: {{ rule.raw_value }} → {{ rule.allowed_value }}</strong>
              <small>{{ rule.field_name }}</small>
            </span>
            <UButton color="error" variant="ghost" icon="i-lucide-trash-2" :loading="busy === `value-mapping-remove-${rule.id}`" @click="removeValueMapping(rule.id)">Удалить</UButton>
          </div>
          <EmptyState
            v-if="!valueMappingRules.length"
            icon="i-lucide-book-open-check"
            title="Сопоставлений значений пока нет"
            description="Они появятся после сохранения выбранного значения для конкретного донора."
          />
        </SettingsCollapsible>
        <SettingsCollapsible
          class="aa-template-history"
          content-class="aa-template-history-content"
          @update:open="handleTemplateHistoryOpen"
        >
          <template #label>
            <span>История шаблона</span>
            <UBadge color="neutral" variant="subtle" size="sm">{{ templateRevisions.length }}</UBadge>
          </template>
          <div v-if="templateRevisionsLoading" class="space-y-2">
            <USkeleton v-for="index in 3" :key="index" class="h-10 w-full" />
          </div>
          <div v-for="revision in templateRevisions" :key="revision.id" class="aa-history-row">
            <span><strong>Версия {{ revision.version }}</strong><small>{{ revision.action }} · {{ revision.created_at }}</small></span>
            <UButton color="neutral" variant="soft" icon="i-lucide-history" @click="restoreTemplateVersion(revision.id)">Восстановить</UButton>
          </div>
        </SettingsCollapsible>
      </UCard>
    </template>

    <template v-else-if="tab === 'review' && selectedBatch">
      <div class="aa-review-head">
        <div>
          <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-left" @click="changeMainTab('start')">← К загрузке</UButton>
          <h2>{{ selectedBatch.name }}</h2>
          <p>{{ selectedBatch.template.category }} · {{ selectedBatch.summary.products }} товаров</p>
        </div>
        <div class="aa-review-actions">
          <UButton color="neutral" variant="soft" @click="bulk('accept_high')">Принять уверенные</UButton>
          <UButton color="neutral" variant="soft" @click="bulk('fill_dashes')">Заполнить пропуски «-»</UButton>

          <UButton v-if="selectedBatch.original_ready" :to="`/api/attribute-assistant/batches/${selectedBatch.id}/original/download`" external color="neutral" variant="soft" icon="i-lucide-file-spreadsheet">Исходный CSV</UButton>
          <UButton :to="`/api/attribute-assistant/batches/${selectedBatch.id}/report/download`" external color="neutral" variant="soft" icon="i-lucide-file-text">Скачать отчёт</UButton>
          <UButton color="neutral" variant="soft" :disabled="Boolean(busy)" @click="exportReadyOnly">Экспортировать готовые</UButton>
          <UButton color="primary" :disabled="Boolean(busy)" @click="exportBatch">
            <UIcon name="i-lucide-download" /> Экспорт всех
          </UButton>
          <UButton
            color="error"
            variant="soft"
            icon="i-lucide-trash-2"
            :loading="busy === `batch-remove-${selectedBatch.id}`"
            @click="removeBatch(selectedBatch)"
          >Удалить обработку</UButton>
        </div>
      </div>

      <div class="aa-metrics">
        <MetricCard label="Готово" :value="selectedBatch.summary.ready" icon="i-lucide-circle-check-big" tone="mint" />
        <MetricCard label="Предложений" :value="selectedBatch.summary.suggestions" icon="i-lucide-lightbulb" tone="blue" />
        <MetricCard label="Конфликтов" :value="selectedBatch.summary.conflicts" icon="i-lucide-triangle-alert" tone="red" />
        <MetricCard label="Не найдено" :value="selectedBatch.summary.missing" icon="i-lucide-circle-help" tone="amber" />
      </div>


      <div class="aa-workspace">
        <aside class="aa-products">
          <div class="aa-products-title">Товары</div>
          <div class="aa-product-controls">
            <UInput v-model="productQuery" icon="i-lucide-search" class="aa-product-filter" placeholder="Модель, название, бренд" />
            <USelect v-model="productStatusFilter" :items="productStatusItems" value-key="value" class="aa-product-filter" />
            <small class="aa-muted">Показано {{ filteredProducts.length }} из {{ selectedBatch.products?.length || 0 }}</small>
          </div>
          <div class="aa-product-list">
            <UButton
              v-for="product in filteredProducts"
              :key="product.id"
              color="neutral"
              variant="ghost"
              block
              :class="['aa-product', { active: selectedProduct?.id === product.id }]"
              :loading="loadingProductId === product.id"
              :disabled="loadingProductId === product.id"
              @click="openProduct(product.id)"
            >
              <span>
                <strong>{{ product.model }}</strong>
                <small style="text-wrap-mode: wrap">{{ product.name || "Без названия" }}</small>
              </span>
              <b :class="product.status">{{ productListIndicator(product) }}</b>
            </UButton>
          </div>
        </aside>

        <main v-if="selectedProduct" class="aa-product-work">
          <UCard as="section" variant="outline" class="aa-card aa-source-card">
            <div class="aa-product-title">
              <div>
                <span class="aa-step">Текущий товар</span>
                <h2>{{ selectedProduct.model }}</h2>
                <p>{{ selectedProduct.name }}</p>
              </div>
              <UBadge :color="selectedProduct.status === 'ready' ? 'success' : 'warning'" variant="subtle">
                {{ selectedProduct.status === "ready" ? "Готов" : "Нужна проверка" }}
              </UBadge>
            </div>

            <div class="aa-product-settings">
              <UFormField label="Шаблон этого товара">
                <USelect
                  :model-value="selectedProduct.template?.id"
                  :items="productTemplateItems"
                  placeholder="Выберите шаблон"
                  class="w-full"
                  @update:model-value="assignCurrentTemplate"
                />
              </UFormField>
              <SettingsCollapsible class="aa-history-menu" content-class="aa-product-history">
                <template #label>
                  <span>История изменений</span>
                  <UBadge color="neutral" variant="subtle" size="sm">{{ historyItems.length }}</UBadge>
                </template>
                <article v-for="item in historyItems" :key="item.id" class="aa-product-history-item">
                  <span>
                    <strong>{{ item.label }}</strong>
                    <small>{{ formatHistoryDate(item.created_at) }} · изменено: {{ item.changed_count }}</small>
                  </span>
                  <UButton color="neutral" variant="soft" icon="i-lucide-undo-2" :loading="busy === 'history-restore'" @click="restoreHistory(item.id)">Вернуть</UButton>
                </article>
                <EmptyState
                  v-if="!historyItems.length"
                  icon="i-lucide-history"
                  title="Изменений пока нет"
                  description="Здесь появятся точки восстановления товара."
                />
              </SettingsCollapsible>
            </div>

            <div class="aa-source-grid">
              <div class="aa-donor-picker">
                <div class="aa-section-title">
                  <span><strong>Доноры</strong><small>Отметьте нужные сайты</small></span>
                  <b>{{ selectedDonors.length }}</b>
                </div>
                <label v-for="donor in displayedDonors" :key="donor.id" :class="['aa-donor-check', { recommended: donor.recommended }]">
                  <UCheckbox
                    :model-value="selectedDonors.includes(donor.id)"
                    @update:model-value="toggleDonor(donor.id)"
                  />
                  <span><strong>{{ donor.name }} <em v-if="donor.recommended">рекомендуем {{ donor.score }}%</em></strong><small>{{ donor.site_url }} · {{ donor.connection_name }}<template v-if="donor.reasons?.length"> · {{ donor.reasons.join("; ") }}</template></small></span>
                </label>
              </div>

              <div class="aa-priority-list">
                <div class="aa-section-title">
                  <span><strong>Порядок проверки</strong><small>Первая строка имеет наивысший приоритет</small></span>
                </div>
                <div v-if="selectedDonorRows.length" class="aa-priority-rows">
                  <div v-for="(donor, index) in selectedDonorRows" :key="donor.id" class="aa-priority-row">
                    <b>{{ index + 1 }}</b>
                    <span>
                      <strong>{{ donor.name }}</strong>
                      <small>{{ index === 0 ? "Главный источник данных" : "Проверка и дополнение" }}</small>
                    </span>
                    <UInput v-model="donorUrlOverrides[String(donor.id)]" class="aa-url-override" :placeholder="`URL товара вручную (необязательно)`" />
                    <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-up" square :disabled="index === 0" aria-label="Поднять донора" @click="moveDonor(index, -1)" />
                    <UButton color="neutral" variant="ghost" icon="i-lucide-arrow-down" square :disabled="index === selectedDonorRows.length - 1" aria-label="Опустить донора" @click="moveDonor(index, 1)" />
                  </div>
                </div>
                <div v-else class="aa-priority-empty">Выберите доноров слева. Ссылка на товар будет найдена по модели автоматически.</div>
                <div class="aa-inline-actions">
                  <UButton color="primary" :disabled="batchOperationRunning || busy === 'process' || !selectedDonors.length" @click="processDonors">
                    <UIcon name="i-lucide-wand-sparkles" /> Найти и проверить
                  </UButton>
                  <UButton
                    color="primary"
                    variant="soft"
                    icon="i-lucide-sparkles"
                    :loading="busy === 'chatgpt-product'"
                    :disabled="batchOperationRunning || !chatGpt?.authenticated"
                    :title="chatGpt?.authenticated ? 'Проанализировать страницу выбранного товара через ChatGPT' : 'Сначала подключите ChatGPT'"
                    @click="askChatGpt"
                  >Спросить ChatGPT</UButton>
                  <UButton color="neutral" variant="soft" :disabled="batchOperationRunning || busy === 'similar'" @click="useSimilar">Похожие товары</UButton>
                </div>
              </div>
            </div>

            <div class="aa-batch-operation">
              <div class="aa-batch-operation-head">
                <span>
                  <strong>Все товары текущей проверки</strong>
                  <small>Массовая обработка продолжится в фоне, даже если выбрать другой товар</small>
                </span>
                <div class="aa-inline-actions">
                  <UButton
                    color="primary"
                    icon="i-lucide-scan-search"
                    :loading="busy === 'process-all'"
                    :disabled="batchOperationRunning || !selectedDonors.length"
                    @click="processAllProducts"
                  >Найти и проверить (все товары)</UButton>
                  <UButton
                    color="primary"
                    variant="soft"
                    icon="i-lucide-sparkles"
                    :loading="batchChatGptLoading"
                    :disabled="batchChatGptLoading || batchOperationRunning || !batchOperation || !chatGpt?.authenticated"
                    @click="askChatGptForAllProducts"
                  >Спросить ChatGPT (все товары)</UButton>
                </div>
              </div>
              <div v-if="batchOperation?.kind === 'donors' && batchOperation.status !== 'idle'" class="aa-batch-operation-progress">
                <div>
                  <strong>{{ batchOperationRunning ? "Поиск и проверка всех товаров" : "Последняя массовая операция" }}</strong>
                  <span>
                    {{ batchOperation.processed }} из {{ batchOperation.total }}
                    · успешно {{ batchOperation.succeeded }}
                    · ошибок {{ batchOperation.failed }}
                    · извлечено {{ batchOperation.attributes_found }}
                  </span>
                </div>
                <UProgress :model-value="batchOperation.percent" color="primary" size="sm" />
                <small v-if="batchOperation.current_product">Сейчас: {{ batchOperation.current_product }}</small>
                <small v-else-if="batchOperation.status === 'failed'" class="aa-operation-error">{{ batchOperation.error || batchOperation.errors[0]?.error }}</small>
              </div>
              <p v-else-if="batchOperation?.kind === 'chatgpt' && batchOperation.status === 'failed'" class="aa-operation-error" role="alert">
                {{ batchOperation.error || batchOperation.errors[0]?.error || "Не удалось выполнить анализ ChatGPT" }}
              </p>
            </div>


            <div v-if="displayedProductSources.length" class="aa-source-results">
              <ULink
                v-for="source in displayedProductSources"
                :key="source.id"
                :href="source.url"
                target="_blank"
                rel="noopener"
                :class="['aa-source-result', source.status]"
              >
                <span>
                  <span class="aa-source-result-heading">
                    <strong>{{ source.donor_name }}</strong>
                    <em :class="['aa-source-kind', `is-${sourceKind(source)}`]">{{ sourceKindLabel(source) }}</em>
                  </span>
                  <small :title="source.message || source.role">{{ source.message || source.role }}</small>
                </span>
                <b>{{ sourceStatusText(source.status, source.attributes_found, source.mapped, source.ambiguous, source.unknown, source.already_filled) }}</b>
              </ULink>
            </div>
          </UCard>

          <UCard as="section" variant="outline" class="aa-card aa-attributes">
            <div class="aa-card-head">
              <div>
                <span class="aa-step">Проверка</span>
                <h2>Атрибуты товара</h2>
                <small class="aa-muted">Заполненные значения защищены</small>
              </div>
              <div class="aa-attribute-toolbar">
                <USelect
                  v-model="attributeStatusFilter"
                  :items="attributeStatusItems"
                  value-key="value"
                  class="aa-attribute-status-filter"
                  aria-label="Фильтр атрибутов по статусу"
                />
                <span class="aa-muted">
                  Показано {{ filteredAttributeValues.length }} из {{ attributeValues.length }}
                </span>
              </div>
            </div>

            <UAlert
              v-if="!valuesByGroup.length"
              color="neutral"
              variant="soft"
              icon="i-lucide-list-filter"
              title="По выбранному фильтру атрибутов нет"
              description="Выберите другой статус или покажите все атрибуты."
            />
            <div v-for="[group, values] in valuesByGroup" :key="group" class="aa-attribute-group">
              <h3>{{ group }}</h3>
              <article v-for="value in values" :key="value.id" :class="['aa-attribute', `is-${value.status}`, { 'is-outside-template': !value.is_in_template }]">
                <div class="aa-attribute-row-head">
                  <div class="aa-attribute-name">
                    <strong>{{ value.name }}</strong>
                    <small v-if="!value.is_in_template">Исходная группа: {{ value.group_name || "Без группы" }}</small>
                    <small v-else-if="value.allowed_values_count">Справочник: {{ value.allowed_values_count }} значений</small>
                    <small v-else>{{ value.is_composite ? "Составной атрибут" : value.value_type }}</small>
                  </div>
                  <UBadge :color="valueStatusColor(value)" variant="subtle">{{ valueStatusLabel(value) }}</UBadge>
                </div>

                <div class="aa-attribute-comparison">
                  <div class="aa-comparison-cell is-current">
                    <span>Было</span>
                    <strong>{{ value.current_value }}</strong>
                    <small>{{ currentValueCaption(value) }}</small>
                    <small v-for="hint in originalValueHints(value)" :key="hint" class="aa-original-value-hint">{{ hint }}</small>
                  </div>
                  <div class="aa-comparison-cell is-proposed">
                    <span>Предложение</span>
                    <strong :class="{ 'aa-not-found': !displayedProposal(value) }">{{ displayedProposal(value) }}</strong>
                    <small v-if="displayedProposal(value)">
                      {{ displayedProposalSource(value) }}
                      <template v-if="displayedProposalConfidence(value)"> · {{ displayedProposalConfidence(value) }}%</template>
                    </small>
                    <small v-else>{{ value.reason || "Источники ещё не дали значения" }}</small>
                  </div>
                  <div class="aa-comparison-cell is-final">
                    <span>Итог</span>
                    <USelectMenu
                      v-if="value.is_composite && value.allowed_values_count"
                      :ref="allowedSelectRef(finalAllowedMenuKey(value))"
                      class="aa-final-select aa-final-select--multiple"
                      :model-value="[...selectedFinalParts(value)]"
                      :items="optionsFor(value).filter((item) => !item.value.includes('/'))"
                      value-key="value"
                      label-key="value"
                      :search-input="{ placeholder: 'Найти значение…' }"
                      :loading="searchingAllowedValueIds.has(value.id)"
                      :reset-search-term-on-blur="true"
                      :ignore-filter="true"
                      :virtualize="true"
                      multiple
                      :disabled="busy === `value-${value.id}`"
                      @update:search-term="queueAllowedSearch(value, $event)"
                      @update:open="handleAllowedMenuOpen(value, finalAllowedMenuKey(value), $event)"
                      @update:model-value="selectFinalValue(value, $event)"
                    />
                    <USelectMenu
                      v-else-if="value.allowed_values_count"
                      :ref="allowedSelectRef(finalAllowedMenuKey(value))"
                      class="aa-final-select"
                      :model-value="selectedFinalValue(value)"
                      :items="optionsFor(value)"
                      value-key="value"
                      label-key="value"
                      placeholder="Выберите итоговое значение"
                      :search-input="{ placeholder: 'Найти значение…' }"
                      :loading="searchingAllowedValueIds.has(value.id)"
                      :reset-search-term-on-blur="true"
                      :ignore-filter="true"
                      :virtualize="true"
                      :disabled="busy === `value-${value.id}`"
                      @update:search-term="queueAllowedSearch(value, $event)"
                      @update:open="handleAllowedMenuOpen(value, finalAllowedMenuKey(value), $event)"
                      @update:model-value="selectFinalValue(value, $event)"
                    />
                    <strong v-else>{{ value.final_value || displayedProposal(value) }}</strong>
                    <small v-if="value.status === 'dash'">{{ value.dash_reason }}</small>
                    <small v-else-if="value.status === 'conflict'">Выберите итог или отклоните предложение</small>
                    <small v-else-if="value.allowed_values_count && value.final_value">Можно выбрать другое значение из шаблона</small>
                    <small v-else-if="value.allowed_values_count && displayedProposal(value)">Предложение системы уже подставлено</small>
                    <small v-else-if="value.allowed_values_count">Выберите значение из шаблона</small>
                    <small v-else>В шаблоне нет значений для выбора</small>
                  </div>
                </div>

                <div class="aa-value-actions">
                  <UButton
                    v-if="!value.is_in_template"
                    color="error"
                    variant="soft"
                    icon="i-lucide-trash-2"
                    :loading="busy === `value-remove-${value.id}`"
                    @click="removeOutsideTemplateValue(value)"
                  >Удалить атрибут</UButton>
                  <UButton
                    v-if="hasPendingProposal(value)"
                    color="success"
                    variant="soft"
                    icon="i-lucide-check"
                    :loading="busy === `value-${value.id}`"
                    @click="valueAction(value, 'accept', displayedProposal(value))"
                  >Принять</UButton>
                  <UButton
                    v-if="hasPendingProposal(value)"
                    color="error"
                    variant="ghost"
                    icon="i-lucide-x"
                    :disabled="busy === `value-${value.id}`"
                    @click="valueAction(value, 'reject')"
                  >Отклонить</UButton>
                  <UButton
                    v-if="(!value.current_value || isTechnicalDash(value.current_value)) && !value.final_value"
                    color="neutral"
                    variant="ghost"
                    icon="i-lucide-minus"
                    :disabled="busy === `value-${value.id}`"
                    @click="valueAction(value, 'dash')"
                  >Поставить «-»</UButton>
                </div>

                <SettingsCollapsible
                  v-if="value.source_details.candidates?.length"
                  class="aa-candidate-details"
                  content-class="aa-candidate-list"
                  :default-open="value.status === 'conflict'"
                >
                  <template #label>
                    <span>Все источники</span>
                    <UBadge color="neutral" variant="subtle" size="sm">{{ value.source_details.candidates.length }}</UBadge>
                  </template>
                    <div
                      v-for="(candidate, index) in value.source_details.candidates"
                      :key="`${candidate.source}-${candidate.source_name}-${index}`"
                      :class="['aa-candidate', { 'is-match': candidate.matches_current, 'is-mismatch': value.current_value && !candidate.matches_current }]"
                    >
                      <div class="aa-candidate-source">
                        <ULink v-if="candidate.url" :to="candidate.url" target="_blank">{{ sourceTitle(candidate.source) }}</ULink>
                        <strong v-else>{{ sourceTitle(candidate.source) }}</strong>
                        <small>{{ candidate.role || "Источник предложения" }}</small>
                      </div>
                      <div class="aa-candidate-values">
                        <span><small>На странице · {{ candidate.source_name }}</small><strong>{{ candidate.raw_value || candidate.value }}</strong></span>
                        <span v-if="candidate.raw_value && candidate.raw_value !== candidate.value"><small>После справочника</small><strong>{{ candidate.value }}</strong></span>
                      </div>
                      <div class="aa-candidate-result">
                        <b>{{ candidate.confidence }}%</b>
                        <UBadge v-if="candidate.matches_current" color="success" variant="subtle">Совпадает</UBadge>
                        <UBadge v-else-if="value.current_value" color="error" variant="subtle">Расхождение</UBadge>
                        <UBadge v-else color="neutral" variant="subtle">Предложение</UBadge>
                      </div>
                      <small class="aa-candidate-reason">{{ candidate.reason }}</small>
                      <UButton
                        v-if="!attributeValuesMatch(candidate.value, value.final_value)"
                        color="success"
                        variant="soft"
                        icon="i-lucide-check"
                        :loading="busy === `value-${value.id}`"
                        @click="valueAction(value, 'accept', candidate.value)"
                      >Выбрать</UButton>
                    </div>
                </SettingsCollapsible>

                <div v-for="(unknown, index) in value.source_details.unknown_values || []" :key="`unknown-${index}`" class="aa-detail-line aa-unknown-detail">
                  <span>
                    <ULink v-if="unknown.url" :to="unknown.url" target="_blank">{{ sourceTitle(unknown.source) }}</ULink>
                    <strong v-else>{{ sourceTitle(unknown.source) }}</strong>
                    · {{ unknown.source_name }}: <strong>{{ unknown.value }}</strong>
                  </span>
                  <span v-if="unknown.suggestions?.length">Ближайшее: {{ unknown.suggestions.join(", ") }}</span>
                  <div v-if="unknown.donor_id && value.field_id && !value.current_value" class="aa-unknown-map">
                    <USelectMenu
                      :ref="allowedSelectRef(unknownAllowedMenuKey(value, index))"
                      v-model="unknownSelections[unknownSelectionKey(value, index)]"
                      class="aa-unknown-select"
                      :items="optionsFor(value)"
                      value-key="id"
                      label-key="value"
                      placeholder="Выберите значение шаблона"
                      :search-input="{ placeholder: 'Найти значение…' }"
                      :loading="searchingAllowedValueIds.has(value.id)"
                      :reset-search-term-on-blur="true"
                      :ignore-filter="true"
                      :virtualize="true"
                      @update:search-term="queueAllowedSearch(value, $event)"
                      @update:open="handleAllowedMenuOpen(value, unknownAllowedMenuKey(value, index), $event)"
                    />
                    <UButton
                      color="primary"
                      variant="soft"
                      icon="i-lucide-bookmark-check"
                      :loading="busy === `value-mapping-${value.id}-${index}`"
                      :disabled="!unknownSelections[unknownSelectionKey(value, index)]"
                      @click="rememberUnknownValue(value, unknown, index)"
                    >Применить и запомнить</UButton>
                  </div>
                  <UButton v-if="!value.current_value" color="warning" variant="soft" icon="i-lucide-book-plus" :loading="busy === `dictionary-${value.id}`" @click="addUnknown(value, unknown)">Добавить как новое значение</UButton>
                </div>
              </article>
            </div>
          </UCard>
        </main>
      </div>
    </template>

    <AppDialog ref="appDialog" />

    <UModal
      :open="Boolean(templateFieldEditor)"
      title="Редактирование атрибута"
      description="Измените структуру поля и названия, встречающиеся у доноров."
      :dismissible="busy !== `field-${templateFieldEditor?.id}`"
      :ui="{ content: 'sm:max-w-2xl' }"
      @update:open="(open) => { if (!open) templateFieldEditor = null }"
    >
      <template v-if="templateFieldEditor" #body>
        <div class="aa-dialog-form">
          <UAlert v-if="error" color="error" variant="subtle" :description="error" />
          <UFormField label="Название" required>
            <UInput v-model="templateFieldEditor.name" class="w-full" />
          </UFormField>
          <UFormField label="Группа">
            <UInput v-model="templateFieldEditor.group_name" class="w-full" />
          </UFormField>
          <UFormField label="Тип значения">
            <USelect
              v-model="templateFieldEditor.value_type"
              :items="[
                { label: 'Из справочника', value: 'select' },
                { label: 'Текст', value: 'text' },
                { label: 'Число', value: 'number' },
                { label: 'Габариты', value: 'dimensions' },
                { label: 'Да / нет', value: 'boolean' },
              ]"
              class="w-full"
            />
          </UFormField>
          <UCheckbox v-model="templateFieldEditor.is_composite" label="Составное значение через /" />
          <div class="aa-synonym-editor">
            <div class="aa-synonym-editor-title">
              <span>
                <strong>Синонимы атрибута</strong>
                <small>{{ templateFieldEditor.synonyms.length }} добавлено</small>
              </span>
            </div>
            <p class="aa-muted">
              Названия характеристик у доноров, соответствующие этому атрибуту шаблона.
            </p>
            <div v-if="templateFieldEditor.synonyms.length" class="aa-synonym-list">
              <div
                v-for="(synonym, index) in templateFieldEditor.synonyms"
                :key="`${synonym}-${index}`"
                class="aa-synonym-row"
              >
                <span>{{ synonym }}</span>
                <UButton
                  type="button"
                  color="error"
                  variant="ghost"
                  size="xs"
                  icon="i-lucide-x"
                  :aria-label="`Удалить синоним ${synonym}`"
                  @click="removeTemplateFieldSynonym(index)"
                />
              </div>
            </div>
            <p v-else class="aa-synonym-empty">Синонимов пока нет.</p>
            <form class="aa-synonym-add" @submit.prevent="addTemplateFieldSynonym">
              <UInput
                v-model="templateFieldEditor.synonymDraft"
                autocomplete="off"
                placeholder="Например: диаметр загрузочного проёма"
                class="w-full"
              />
              <UButton
                type="submit"
                color="neutral"
                variant="soft"
                :disabled="!templateFieldEditor.synonymDraft.trim()"
              >
                Добавить
              </UButton>
            </form>
          </div>
          <UFormField label="Правила конвертации (JSON-массив)">
            <UTextarea v-model="templateFieldEditor.conversion_rules" :rows="6" class="w-full font-mono" />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton color="neutral" variant="soft" @click="templateFieldEditor = null">Отмена</UButton>
          <UButton
            color="primary"
            :loading="busy === `field-${templateFieldEditor?.id}`"
            :disabled="!templateFieldEditor?.name.trim()"
            @click="saveTemplateFieldEdit"
          >
            Сохранить
          </UButton>
        </div>
      </template>
    </UModal>

    <UModal
      :open="Boolean(fieldValueEditor)"
      :title="`Добавить значение · ${fieldValueEditor?.fieldName || ''}`"
      description="Новое значение попадёт в справочник этого атрибута."
      :dismissible="busy !== `field-value-${fieldValueEditor?.fieldId}`"
      @update:open="(open) => { if (!open) fieldValueEditor = null }"
    >
      <template v-if="fieldValueEditor" #body>
        <div class="aa-dialog-form">
          <UFormField label="Разрешённое значение" required>
            <UInput v-model="fieldValueEditor.value" autofocus class="w-full" />
          </UFormField>
          <UFormField label="Синоним" hint="необязательно">
            <UInput v-model="fieldValueEditor.synonym" class="w-full" />
          </UFormField>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton color="neutral" variant="soft" @click="fieldValueEditor = null">Отмена</UButton>
          <UButton
            color="primary"
            :loading="busy === `field-value-${fieldValueEditor?.fieldId}`"
            :disabled="!fieldValueEditor?.value.trim()"
            @click="saveFieldValue"
          >
            Добавить
          </UButton>
        </div>
      </template>
    </UModal>

    <UModal
      :open="Boolean(allowedValueEditor)"
      :title="`Значение и синонимы · ${allowedValueEditor?.fieldName || ''}`"
      description="Синонимы помогают сопоставить формулировки доноров с точным значением шаблона."
      :dismissible="busy !== `allowed-${allowedValueEditor?.id}`"
      :ui="{ content: 'sm:max-w-2xl' }"
      @update:open="(open) => { if (!open) closeAllowedValueEditor() }"
    >
      <template v-if="allowedValueEditor" #body>
        <div class="aa-dialog-form">
          <UAlert v-if="error" color="error" variant="subtle" :description="error" />
          <UFormField label="Разрешённое значение">
            <UInput v-model="allowedValueEditor.value" autocomplete="off" class="w-full" />
          </UFormField>

          <div class="aa-synonym-editor">
            <div class="aa-synonym-editor-title">
              <span><strong>Синонимы</strong><small>{{ allowedValueEditor.synonyms.length }} добавлено</small></span>
            </div>
            <div v-if="allowedValueEditor.synonyms.length" class="aa-synonym-list">
              <div v-for="(synonym, index) in allowedValueEditor.synonyms" :key="`${synonym}-${index}`" class="aa-synonym-row">
                <span>{{ synonym }}</span>
                <UButton
                  type="button"
                  color="error"
                  variant="ghost"
                  size="xs"
                  icon="i-lucide-x"
                  :aria-label="`Удалить синоним ${synonym}`"
                  @click="removeAllowedValueSynonym(index)"
                />
              </div>
            </div>
            <p v-else class="aa-synonym-empty">Синонимов пока нет.</p>
            <form class="aa-synonym-add" @submit.prevent="addAllowedValueSynonym">
              <UInput v-model="allowedValueEditor.synonymDraft" autocomplete="off" placeholder="Например: снизу" class="w-full" />
              <UButton type="submit" color="neutral" variant="soft" :disabled="!allowedValueEditor.synonymDraft.trim()">
                Добавить
              </UButton>
            </form>
          </div>
        </div>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="soft"
            :disabled="busy === `allowed-${allowedValueEditor?.id}`"
            @click="closeAllowedValueEditor"
          >
            Отмена
          </UButton>
          <UButton
            color="primary"
            :loading="busy === `allowed-${allowedValueEditor?.id}`"
            @click="saveAllowedValue"
          >
            Сохранить
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>

<style src="../assets/css/attribute-assistant.css"></style>

