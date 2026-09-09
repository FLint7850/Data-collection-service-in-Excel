import { attributeAssistantService as api } from "~/services/attribute-assistant.service";
import type {
    AttributeAllowedValue,
    AttributeMappingRule,
    AttributeTemplate,
    AttributeTemplatePreview,
    AttributeValueMappingRule,
} from "~/types/attribute-assistant";
import type { AttributeAssistantContext } from "~/composables/useAttributeAssistant";
import { errorMessage } from "~/utils/format";

export function useAttributeTemplates(assistant: AttributeAssistantContext) {
    const {
        busy,
        error,
        workspace,
        selectedTemplateId,
        tab,
        run,
        confirmAction,
        promptValue,
        loadWorkspace,
        notify,
        writeRoute,
    } = assistant;

    const templateFile = ref<File | null>(null);
    const templateDetails = ref<AttributeTemplate | null>(null);
    const templatePreview = ref<AttributeTemplatePreview | null>(null);
    const templateUpdateFile = ref<File | null>(null);
    const templateUpdateMode = ref<"merge" | "replace">("merge");
    const templateRevisions = ref<Array<{ id: number; version: number; action: string; created_at: string }>>([]);
    const templateRevisionsLoaded = ref(false);
    const templateRevisionsLoading = ref(false);
    const mappingRules = ref<AttributeMappingRule[]>([]);
    const valueMappingRules = ref<AttributeValueMappingRule[]>([]);
    const loadedTemplateFieldIds = ref<Set<number>>(new Set());
    const loadingTemplateFieldIds = ref<Set<number>>(new Set());
    const templateFieldQueries = ref<Record<number, string>>({});
    const templateFieldMatchedCounts = ref<Record<number, number>>({});
    const showNewTemplateField = ref(false);

    const allowedValueEditor = ref<{
        id: number;
        fieldName: string;
        value: string;
        synonyms: string[];
        synonymDraft: string;
    } | null>(null);

    const templateFieldEditor = ref<{
        id: number;
        name: string;
        synonyms: string[];
        synonymDraft: string;
        group_name: string;
        value_type: string;
        is_composite: boolean;
        conversion_rules: string;
    } | null>(null);

    const fieldValueEditor = ref<{
        fieldId: number;
        fieldName: string;
        value: string;
        synonym: string;
    } | null>(null);

    const templateForm = reactive({
        name: "",
        category: "",
        product_type: "",
        description: "",
    });

    const newTemplateField = reactive({
        group_name: "Основные характеристики",
        name: "",
        value_type: "select",
        is_required: true,
        is_composite: false,
        separator: "/",
    });

    const templateFieldSearchTimers = new Map<number, ReturnType<typeof setTimeout>>();
    const templateFieldSearchTokens = new Map<number, number>();

    async function previewNewTemplate() {
        if (!templateFile.value) {
            error.value = "Выберите CSV-файл шаблона.";
            return;
        }
        templatePreview.value = await run("template-preview", () => api.previewTemplate(templateFile.value!));
    }

    async function importTemplate() {
        if (!templateFile.value) {
            error.value = "Выберите CSV-файл шаблона.";
            return;
        }
        if (!templatePreview.value) await previewNewTemplate();
        if (!templatePreview.value?.can_import) {
            error.value = "Предварительная проверка не разрешает импорт.";
            return;
        }
        const result = await run("template-import", () => api.importTemplate(templateFile.value!, templateForm));
        if (!result) return;
        notify("Шаблон импортирован");
        await loadWorkspace();
        selectedTemplateId.value = result.id;
        templateFile.value = null;
        templatePreview.value = null;
        await openTemplate(result.id);
    }

    async function openTemplate(id: number, syncRoute = true) {
        const requestKey = `template-open-${id}`;
        if (busy.value === requestKey) return;
        selectedTemplateId.value = id;
        const result = await run(requestKey, () => Promise.all([
            api.template(id),
            api.mappingRules(id).catch(() => ({ items: [] })),
            api.valueMappingRules(id).catch(() => ({ items: [] })),
        ]));
        if (!result) return;

        const [details, rules, valueRules] = result;
        templateDetails.value = details;
        loadedTemplateFieldIds.value = new Set();
        templateFieldQueries.value = {};
        templateFieldMatchedCounts.value = {};
        templateFieldSearchTimers.forEach((timer) => clearTimeout(timer));
        templateFieldSearchTimers.clear();
        templateFieldSearchTokens.clear();
        templateRevisions.value = [];
        templateRevisionsLoaded.value = false;
        mappingRules.value = rules.items;
        valueMappingRules.value = valueRules.items;

        if (syncRoute) await writeRoute("push");
    }

    async function onShopSynced() {
        const openedId = templateDetails.value?.id;
        await loadWorkspace();
        if (openedId) await openTemplate(openedId);
    }

    async function loadTemplateRevisions() {
        const templateId = templateDetails.value?.id;
        if (!templateId || templateRevisionsLoaded.value || templateRevisionsLoading.value) return;
        templateRevisionsLoading.value = true;
        try {
            const result = await api.templateRevisions(templateId);
            if (templateDetails.value?.id !== templateId) return;
            templateRevisions.value = result.items;
            templateRevisionsLoaded.value = true;
        } catch (caught) {
            error.value = errorMessage(caught);
        } finally {
            templateRevisionsLoading.value = false;
        }
    }

    function handleTemplateHistoryOpen(open: boolean) {
        if (open) void loadTemplateRevisions();
    }

    function setTemplateFieldLoading(fieldId: number, loading: boolean) {
        const next = new Set(loadingTemplateFieldIds.value);
        if (loading) next.add(fieldId);
        else next.delete(fieldId);
        loadingTemplateFieldIds.value = next;
    }

    async function loadTemplateFieldValues(fieldId: number) {
        if (
            loadedTemplateFieldIds.value.has(fieldId)
            || loadingTemplateFieldIds.value.has(fieldId)
        ) return;

        setTemplateFieldLoading(fieldId, true);
        try {
            const result = await api.allowedValues(fieldId, "", true);
            if (templateDetails.value?.fields) {
                templateDetails.value = {
                    ...templateDetails.value,
                    fields: templateDetails.value.fields.map((field) => field.id === fieldId
                        ? { ...field, allowed_values: result.values, allowed_values_count: result.total }
                        : field),
                };
            }
            loadedTemplateFieldIds.value = new Set([...loadedTemplateFieldIds.value, fieldId]);
        } catch (caught) {
            error.value = errorMessage(caught);
        } finally {
            setTemplateFieldLoading(fieldId, false);
        }
    }

    function handleTemplateFieldOpen(open: boolean, fieldId: number) {
        if (open) void loadTemplateFieldValues(fieldId);
    }

    function queueTemplateFieldValueSearch(fieldId: number, event: Event) {
        const query = (event.target as HTMLInputElement).value;
        templateFieldQueries.value = { ...templateFieldQueries.value, [fieldId]: query };
        const previousTimer = templateFieldSearchTimers.get(fieldId);
        if (previousTimer) clearTimeout(previousTimer);

        const token = (templateFieldSearchTokens.get(fieldId) || 0) + 1;
        templateFieldSearchTokens.set(fieldId, token);
        templateFieldSearchTimers.set(fieldId, setTimeout(async () => {
            setTemplateFieldLoading(fieldId, true);
            try {
                const result = await api.allowedValues(fieldId, query, true);
                if (templateFieldSearchTokens.get(fieldId) !== token || !templateDetails.value?.fields) return;
                templateDetails.value = {
                    ...templateDetails.value,
                    fields: templateDetails.value.fields.map((field) => field.id === fieldId
                        ? { ...field, allowed_values: result.values, allowed_values_count: result.total }
                        : field),
                };
                templateFieldMatchedCounts.value = {
                    ...templateFieldMatchedCounts.value,
                    [fieldId]: result.matched,
                };
            } catch (caught) {
                if (templateFieldSearchTokens.get(fieldId) === token) error.value = errorMessage(caught);
            } finally {
                if (templateFieldSearchTokens.get(fieldId) === token) setTemplateFieldLoading(fieldId, false);
            }
        }, 250));
    }

    async function updateTemplateCsv() {
        if (!templateDetails.value || !templateUpdateFile.value) return;
        const preview = await run(
            "template-update-preview",
            () => api.previewTemplate(templateUpdateFile.value!, templateDetails.value!.id),
        );
        if (!preview) return;

        templatePreview.value = preview;
        if (!preview.can_import || !await confirmAction({
            title: "Обновить шаблон?",
            description: `Будет применено полей: ${preview.fields.length}. Предупреждений: ${preview.warnings.length}.`,
            confirmLabel: "Применить",
        })) return;

        const result = await run(
            "template-update",
            () => api.updateTemplateCsv(templateDetails.value!.id, templateUpdateFile.value!, templateUpdateMode.value),
        );
        if (!result) return;

        templateDetails.value = result.template;
        templateUpdateFile.value = null;
        await loadWorkspace();
        notify("Шаблон обновлён");
    }

    async function copyCurrentTemplate() {
        if (!templateDetails.value) return;
        const name = await promptValue({
            title: "Создать копию шаблона",
            label: "Название копии",
            defaultValue: `${templateDetails.value.name} — копия`,
            confirmLabel: "Создать",
        });
        if (!name?.trim()) return;

        const result = await run("template-copy", () => api.copyTemplate(templateDetails.value!.id, name));
        if (result) {
            await loadWorkspace();
            await openTemplate(result.id);
            notify("Копия шаблона создана");
        }
    }

    async function toggleTemplateActive() {
        if (!templateDetails.value) return;
        const result = await run(
            "template-active",
            () => api.updateTemplate(templateDetails.value!.id, { is_active: !templateDetails.value!.is_active }),
        );
        if (result) {
            templateDetails.value = result;
            await loadWorkspace();
        }
    }

    async function removeTemplate(template: AttributeTemplate) {
        const requestKey = `template-remove-${template.id}`;
        if (busy.value === requestKey) return;
        if (!await confirmAction({
            title: `Удалить шаблон «${template.name}»?`,
            description: "Будут удалены атрибуты, значения, синонимы и история шаблона. Используемый шаблон сервер удалить не позволит.",
            confirmLabel: "Удалить шаблон",
            color: "error",
        })) return;

        const result = await run(requestKey, () => api.removeTemplate(template.id));
        if (!result) return;

        if (templateDetails.value?.id === template.id) {
            templateDetails.value = null;
            templateRevisions.value = [];
            mappingRules.value = [];
            valueMappingRules.value = [];
        }

        const remaining = workspace.value.templates.filter((item) => item.id !== template.id);
        if (selectedTemplateId.value === template.id) {
            selectedTemplateId.value = remaining[0]?.id || null;
        }

        await loadWorkspace();
        if (tab.value === "templates") await writeRoute("replace");
        notify("Шаблон удалён");
    }

    async function removeMapping(id: number) {
        if (!await confirmAction({
            title: "Удалить сопоставление?",
            description: "Автоматическое сопоставление атрибута донора больше не будет применяться.",
            confirmLabel: "Удалить",
            color: "error",
        })) return;

        if (await run(`mapping-remove-${id}`, () => api.removeMappingRule(id))) {
            mappingRules.value = mappingRules.value.filter((item) => item.id !== id);
        }
    }

    async function removeValueMapping(id: number) {
        if (!await confirmAction({
            title: "Удалить соответствие значения?",
            description: "Сохранённое правило для значения донора больше не будет применяться.",
            confirmLabel: "Удалить",
            color: "error",
        })) return;

        if (await run(`value-mapping-remove-${id}`, () => api.removeValueMappingRule(id))) {
            valueMappingRules.value = valueMappingRules.value.filter((item) => item.id !== id);
        }
    }

    async function createTemplateField() {
        if (!templateDetails.value || !newTemplateField.name.trim()) {
            error.value = "Укажите название нового атрибута.";
            return;
        }

        const result = await run("field-create", () =>
            api.createField(templateDetails.value!.id, { ...newTemplateField }),
        );
        if (!result) return;

        templateDetails.value = result;
        newTemplateField.name = "";
        showNewTemplateField.value = false;
        await loadWorkspace();
        notify("Атрибут добавлен");
    }

    async function removeTemplateField(field: NonNullable<AttributeTemplate["fields"]>[number]) {
        const requestKey = `field-remove-${field.id}`;
        if (!templateDetails.value || busy.value === requestKey) return;
        if (!await confirmAction({
            title: `Удалить атрибут «${field.name}»?`,
            description: "Заполненные значения товаров сохранятся как дополнительные атрибуты.",
            confirmLabel: "Удалить атрибут",
            color: "error",
        })) return;

        const previous = templateDetails.value;
        const remainingFields = (previous.fields || []).filter((item) => item.id !== field.id);
        templateDetails.value = {
            ...previous,
            fields: remainingFields,
            field_count: remainingFields.length,
        };
        workspace.value = {
            ...workspace.value,
            templates: workspace.value.templates.map((item) => item.id === previous.id
                ? { ...item, field_count: remainingFields.length }
                : item),
        };

        const result = await run(requestKey, () => api.removeField(field.id));
        if (!result) {
            templateDetails.value = previous;
            workspace.value = {
                ...workspace.value,
                templates: workspace.value.templates.map((item) => item.id === previous.id
                    ? { ...item, field_count: previous.field_count }
                    : item),
            };
            return;
        }

        const revisions = await api.templateRevisions(previous.id).catch(() => null);
        if (revisions) templateRevisions.value = revisions.items;
        notify("Атрибут удалён");
    }

    async function restoreTemplateVersion(id: number) {
        if (!templateDetails.value || !await confirmAction({
            title: "Восстановить версию шаблона?",
            description: "Текущая структура и значения шаблона будут заменены выбранной версией.",
            confirmLabel: "Восстановить",
        })) return;

        const result = await run(
            "template-restore",
            () => api.restoreTemplate(templateDetails.value!.id, id),
        );
        if (result) {
            templateDetails.value = result;
            await openTemplate(result.id);
        }
    }

    function editField(field: NonNullable<AttributeTemplate["fields"]>[number]) {
        error.value = "";
        templateFieldEditor.value = {
            id: field.id,
            name: field.name,
            synonyms: [...(field.synonyms || [])],
            synonymDraft: "",
            group_name: field.group_name,
            value_type: field.value_type,
            is_composite: field.is_composite,
            conversion_rules: JSON.stringify(field.conversion_rules || [], null, 2),
        };
    }

    function addTemplateFieldSynonym() {
        const editor = templateFieldEditor.value;
        if (!editor) return;
        const synonym = editor.synonymDraft.trim();
        if (!synonym) return;
        const key = synonym.toLocaleLowerCase("ru-RU");

        if (key === editor.name.trim().toLocaleLowerCase("ru-RU")) {
            error.value = "Синоним не должен совпадать с названием атрибута.";
            return;
        }
        if (editor.synonyms.some((item) => item.toLocaleLowerCase("ru-RU") === key)) {
            error.value = "Такой синоним уже добавлен.";
            return;
        }

        editor.synonyms.push(synonym);
        editor.synonymDraft = "";
        error.value = "";
    }

    function removeTemplateFieldSynonym(index: number) {
        templateFieldEditor.value?.synonyms.splice(index, 1);
    }

    async function saveTemplateFieldEdit() {
        const editor = templateFieldEditor.value;
        if (!editor || !editor.name.trim()) return;
        if (editor.synonymDraft.trim()) addTemplateFieldSynonym();
        if (templateFieldEditor.value?.synonymDraft.trim()) return;

        let conversionRules: unknown;
        try {
            conversionRules = JSON.parse(editor.conversion_rules || "[]");
            if (!Array.isArray(conversionRules)) throw new Error("not an array");
        } catch {
            error.value = "Правила конвертации должны быть корректным JSON-массивом.";
            return;
        }

        const result = await run(`field-${editor.id}`, () => api.updateField(editor.id, {
            name: editor.name,
            synonyms: editor.synonyms,
            group_name: editor.group_name,
            value_type: editor.value_type,
            is_composite: editor.is_composite,
            conversion_rules: conversionRules,
        }));
        if (!result) return;

        templateDetails.value = result;
        templateFieldEditor.value = null;
        notify("Атрибут и синонимы обновлены");
    }

    function addFieldValue(field: NonNullable<AttributeTemplate["fields"]>[number]) {
        fieldValueEditor.value = {
            fieldId: field.id,
            fieldName: field.name,
            value: "",
            synonym: "",
        };
    }

    async function saveFieldValue() {
        const editor = fieldValueEditor.value;
        if (!editor?.value.trim()) return;

        const result = await run(
            `field-value-${editor.fieldId}`,
            () => api.addAllowedValue(editor.fieldId, editor.value, editor.synonym),
        );
        if (!result || !templateDetails.value) return;

        fieldValueEditor.value = null;
        await openTemplate(templateDetails.value.id);
        notify("Значение добавлено");
    }

    function editAllowedValue(fieldName: string, allowed: AttributeAllowedValue) {
        error.value = "";
        allowedValueEditor.value = {
            id: allowed.id,
            fieldName,
            value: allowed.value,
            synonyms: [...(allowed.synonyms || [])],
            synonymDraft: "",
        };
    }

    function closeAllowedValueEditor() {
        const editor = allowedValueEditor.value;
        if (editor && busy.value === `allowed-${editor.id}`) return;
        allowedValueEditor.value = null;
    }

    function addAllowedValueSynonym() {
        const editor = allowedValueEditor.value;
        if (!editor) return;
        const synonym = editor.synonymDraft.trim();
        if (!synonym) return;
        const key = synonym.toLocaleLowerCase("ru-RU");

        if (key === editor.value.trim().toLocaleLowerCase("ru-RU")) {
            error.value = "Синоним не должен совпадать с разрешённым значением.";
            return;
        }
        if (editor.synonyms.some((item) => item.toLocaleLowerCase("ru-RU") === key)) {
            error.value = "Такой синоним уже добавлен.";
            return;
        }

        editor.synonyms.push(synonym);
        editor.synonymDraft = "";
        error.value = "";
    }

    function removeAllowedValueSynonym(index: number) {
        allowedValueEditor.value?.synonyms.splice(index, 1);
    }

    async function saveAllowedValue() {
        const editor = allowedValueEditor.value;
        if (!editor) return;
        const value = editor.value.trim();
        if (!value) {
            error.value = "Разрешённое значение не может быть пустым.";
            return;
        }

        if (editor.synonymDraft.trim()) addAllowedValueSynonym();
        if (allowedValueEditor.value?.synonymDraft.trim()) return;

        const result = await run(`allowed-${editor.id}`, () => api.updateAllowedValue(editor.id, {
            value,
            synonyms: editor.synonyms,
        }));
        if (!result) return;

        patchAllowedValue(editor.id, result.value);
        if (templateDetails.value) {
            templateDetails.value = {
                ...templateDetails.value,
                version: result.template_version,
            };
        }
        allowedValueEditor.value = null;
        notify("Значение и синонимы сохранены");
    }

    function patchAllowedValue(
        id: number,
        values: Partial<{
            value: string;
            is_active: boolean;
            is_combination: boolean;
            synonyms: string[];
        }>,
    ) {
        if (!templateDetails.value?.fields) return;
        templateDetails.value = {
            ...templateDetails.value,
            fields: templateDetails.value.fields.map((field) => ({
                ...field,
                allowed_values: field.allowed_values.map((allowed) =>
                    allowed.id === id ? { ...allowed, ...values } : allowed,
                ),
            })),
        };
    }

    function allowedValueMenuItems(fieldName: string, allowed: AttributeAllowedValue) {
        return [
            {
                label: "Значение и синонимы",
                icon: "i-lucide-pencil",
                onSelect: () => editAllowedValue(fieldName, allowed),
            },
            {
                label: allowed.is_active ? "Отключить" : "Включить",
                icon: allowed.is_active ? "i-lucide-circle-off" : "i-lucide-circle-check",
                disabled: busy.value === `allowed-${allowed.id}`,
                onSelect: () => void toggleAllowedValue(allowed.id, allowed.is_active),
            },
        ];
    }

    async function toggleAllowedValue(id: number, active: boolean) {
        const nextActive = !active;
        patchAllowedValue(id, { is_active: nextActive });

        const result = await run(
            `allowed-${id}`,
            () => api.updateAllowedValue(id, { is_active: !active }),
        );
        if (!result) {
            patchAllowedValue(id, { is_active: active });
            return;
        }

        patchAllowedValue(id, result.value || { is_active: nextActive });
        if (templateDetails.value) {
            templateDetails.value = {
                ...templateDetails.value,
                version: result.template_version,
            };
        }
        notify(nextActive ? "Значение включено" : "Значение отключено");
    }

    function dispose() {
        templateFieldSearchTimers.forEach((timer) => clearTimeout(timer));
        templateFieldSearchTimers.clear();
        templateFieldSearchTokens.clear();
    }

    return {
        templateFile,
        templateDetails,
        templatePreview,
        templateUpdateFile,
        templateUpdateMode,
        templateRevisions,
        templateRevisionsLoaded,
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
        loadTemplateRevisions,
        handleTemplateHistoryOpen,
        loadTemplateFieldValues,
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
        patchAllowedValue,
        allowedValueMenuItems,
        toggleAllowedValue,
        dispose,
    };
}

export type AttributeTemplatesContext = ReturnType<typeof useAttributeTemplates>;
