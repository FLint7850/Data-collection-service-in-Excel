import { attributeAssistantService as api } from "~/services/attribute-assistant.service";
import type {
    AttributeBatch,
    AttributeBatchOperation,
    AttributeDonor,
    AttributeHistoryItem,
    AttributeProduct,
    AttributeValue,
} from "~/types/attribute-assistant";
import type { AttributeAssistantContext } from "~/composables/useAttributeAssistant";
import type { AttributeAllowedValuesContext } from "~/composables/useAttributeAllowedValues";
import {
    ALL_FILTER_VALUE,
    ATTRIBUTE_STATUS_VALUES,
    PRODUCT_STATUS_VALUES,
    matchesAttributeStatus,
    matchesProductStatus,
    sourceKind,
    unknownSelectionKey,
} from "~/utils/attribute-assistant";
import { errorMessage } from "~/utils/format";

export function useAttributeReview(
    assistant: AttributeAssistantContext,
    allowedValues: AttributeAllowedValuesContext,
) {
    const toast = useToast();
    const {
        busy,
        error,
        tab,
        inputMode,
        workspace,
        donors,
        selectedTemplateId,
        productFile,
        urlsText,
        processingMode,
        chatGpt,
        run,
        confirmAction,
        promptValue,
        loadWorkspace,
        notify,
        writeRoute,
    } = assistant;

    const selectedBatch = ref<AttributeBatch | null>(null);
    const selectedProduct = ref<AttributeProduct | null>(null);
    const loadingProductId = ref<number | null>(null);
    const selectedDonors = ref<number[]>([]);
    const unknownSelections = ref<Record<string, number>>({});
    const donorRecommendations = ref<AttributeDonor[]>([]);
    const donorUrlOverrides = ref<Record<string, string>>({});
    const historyItems = ref<AttributeHistoryItem[]>([]);
    const batchOperation = ref<AttributeBatchOperation | null>(null);

    const productQuery = ref("");
    const productStatusFilter = ref(ALL_FILTER_VALUE);
    const attributeStatusFilter = ref(ALL_FILTER_VALUE);

    let productRequestToken = 0;
    let batchOperationPoll: ReturnType<typeof setTimeout> | null = null;

    const displayedDonors = computed(() =>
        donorRecommendations.value.length ? donorRecommendations.value : donors.value,
    );

    const selectedDonorRows = computed(() =>
        selectedDonors.value
            .map((id) => displayedDonors.value.find((item) => item.id === id))
            .filter((item): item is AttributeDonor => Boolean(item)),
    );

    const filteredProducts = computed(() => (selectedBatch.value?.products || []).filter((product) => {
        const query = productQuery.value.trim().toLocaleLowerCase("ru-RU");
        const queryMatches = !query
            || `${product.model} ${product.name} ${product.brand}`.toLocaleLowerCase("ru-RU").includes(query);
        return queryMatches && matchesProductStatus(product, productStatusFilter.value);
    }));

    const productStatusItems = computed(() => {
        const products = selectedBatch.value?.products || [];
        const count = (status: string) => products.filter((product) => matchesProductStatus(product, status)).length;
        return [
            { label: `Все товары (${products.length})`, value: ALL_FILTER_VALUE },
            { label: `Готовые (${count("ready")})`, value: "ready" },
            { label: `С конфликтами (${count("conflict")})`, value: "conflict" },
            { label: `С пропусками (${count("missing")})`, value: "missing" },
            { label: `Вне шаблона (${count("outside_template")})`, value: "outside_template" },
            { label: `Нужна проверка (${count("needs_review")})`, value: "needs_review" },
        ];
    });

    const attributeValues = computed(() => selectedProduct.value?.values || []);

    const filteredAttributeValues = computed(() =>
        attributeValues.value.filter((value) => matchesAttributeStatus(value, attributeStatusFilter.value)),
    );

    const attributeStatusItems = computed(() => {
        const values = attributeValues.value;
        const count = (status: string) => values.filter((value) => matchesAttributeStatus(value, status)).length;
        return [
            { label: `Все атрибуты (${values.length})`, value: ALL_FILTER_VALUE },
            { label: `Вне шаблона (${count("outside_template")})`, value: "outside_template" },
            { label: `Конфликт (${count("conflict")})`, value: "conflict" },
            { label: `Предложения (${count("suggested")})`, value: "suggested" },
            { label: `Нет предложения (${count("no_suggestion")})`, value: "no_suggestion" },
        ];
    });

    const valuesByGroup = computed(() => {
        const groups = new Map<string, AttributeValue[]>();
        const outsideTemplate: AttributeValue[] = [];

        for (const value of filteredAttributeValues.value) {
            if (!value.is_in_template) {
                outsideTemplate.push(value);
                continue;
            }
            const key = value.group_name || "Без группы";
            groups.set(key, [...(groups.get(key) || []), value]);
        }

        const result: Array<[string, AttributeValue[]]> = [...groups.entries()];
        if (outsideTemplate.length) result.unshift(["Вне шаблона", outsideTemplate]);
        return result;
    });

    const batchOperationRunning = computed(() =>
        ["queued", "running"].includes(batchOperation.value?.status || ""),
    );

    const batchChatGptLoading = computed(() =>
        busy.value === "chatgpt-all"
        || (batchOperationRunning.value && batchOperation.value?.kind === "chatgpt"),
    );

    const displayedProductSources = computed(() =>
        (selectedProduct.value?.sources || []).filter((source) => {
            const kind = sourceKind(source);
            return kind === "donor" || kind === "chatgpt";
        }),
    );

    function productListIndicator(product: AttributeProduct): string {
        if (productStatusFilter.value === "outside_template") {
            return `${product.counts.outside_template}`;
        }
        return String(product.counts.conflicts || product.counts.missing || "✓");
    }

    function currentValueCaption(value: AttributeValue) {
        if (value.current_value) {
            return value.source === "current_site" || selectedBatch.value?.input_mode === "urls"
                ? "Исходная страница сайта"
                : "Исходный CSV сайта";
        }
        if (value.source_details.unknown_values?.length) return "Исходное значение из источника приведено ниже";
        return selectedBatch.value?.input_mode === "urls"
            ? "На странице не найдено"
            : "В файле не заполнено";
    }

    function setRouteFilters(filters: {
        productQuery?: string;
        productStatus?: string;
        attributeStatus?: string;
    }) {
        if (filters.productQuery !== undefined) productQuery.value = filters.productQuery;
        if (filters.productStatus !== undefined) {
            productStatusFilter.value = PRODUCT_STATUS_VALUES.has(filters.productStatus)
                ? filters.productStatus
                : ALL_FILTER_VALUE;
        }
        if (filters.attributeStatus !== undefined) {
            attributeStatusFilter.value = ATTRIBUTE_STATUS_VALUES.has(filters.attributeStatus)
                ? filters.attributeStatus
                : ALL_FILTER_VALUE;
        }
    }

    async function createBatch() {
        if (inputMode.value === "csv") {
            if (!productFile.value || !selectedTemplateId.value) {
                error.value = "Выберите CSV товаров и шаблон категории.";
                return;
            }
            const batch = await run("batch-import", () =>
                api.importBatch(productFile.value!, selectedTemplateId.value!, processingMode.value),
            );
            if (batch) await openBatch(batch.id);
            return;
        }

        const urls = urlsText.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
        if (!urls.length) {
            error.value = "Вставьте хотя бы одну ссылку.";
            return;
        }

        const batch = await run("url-import", () =>
            api.importUrls(urls, selectedTemplateId.value, processingMode.value),
        );
        if (batch) await openBatch(batch.id);
    }

    function clearBatchOperationPoll() {
        if (batchOperationPoll) clearTimeout(batchOperationPoll);
        batchOperationPoll = null;
    }

    function currentProductOverrides(): Record<string, Record<string, string>> {
        if (!selectedProduct.value) return {};
        return { [String(selectedProduct.value.id)]: { ...donorUrlOverrides.value } };
    }

    function scheduleBatchOperationPoll(batchId: number, delay = 1400) {
        clearBatchOperationPoll();
        batchOperationPoll = setTimeout(() => void loadBatchOperation(batchId), delay);
    }

    async function loadBatchOperation(batchId: number) {
        try {
            const previous = batchOperation.value;
            const operation = await api.batchOperation(batchId);
            if (selectedBatch.value?.id !== batchId) return;
            batchOperation.value = operation;

            if (["queued", "running"].includes(operation.status)) {
                scheduleBatchOperationPoll(batchId);
                return;
            }

            clearBatchOperationPoll();
            const justFinished = previous?.id === operation.id
                && ["queued", "running"].includes(previous.status)
                && ["completed", "failed"].includes(operation.status);
            if (!justFinished) return;

            await refreshBatch();
            const productId = selectedProduct.value?.id;
            if (productId && selectedBatch.value?.id === batchId) {
                await openProduct(productId, { syncRoute: false, resetAttributeFilter: false });
            }

            const summary = "Обработано: " + operation.processed
                + " · успешно: " + operation.succeeded
                + " · ошибок: " + operation.failed;

            if (operation.status === "failed") {
                toast.add({
                    title: "Массовая операция остановлена",
                    description: operation.error || summary,
                    color: "error",
                });
            } else if (operation.failed) {
                toast.add({
                    title: "Массовая операция завершена с ошибками",
                    description: summary,
                    color: "warning",
                });
            } else {
                notify("Массовая операция завершена · " + summary);
            }
        } catch (caught) {
            if (selectedBatch.value?.id !== batchId) return;
            clearBatchOperationPoll();
            error.value = errorMessage(caught);
            if (!batchOperation.value || batchOperationRunning.value) {
                scheduleBatchOperationPoll(batchId, 5000);
            }
        }
    }

    async function processAllProducts() {
        if (!selectedBatch.value || !selectedDonors.value.length || batchOperationRunning.value) return;
        const total = selectedBatch.value.summary.products;
        if (!await confirmAction({
            title: "Найти и проверить все товары (" + total + ")?",
            description: "Выбранные доноры будут применены ко всей текущей обработке. Для неё используется один общий браузерный сеанс.",
            confirmLabel: "Начать проверку",
        })) return;

        const result = await run("process-all", () =>
            api.processBatch(selectedBatch.value!.id, selectedDonors.value, currentProductOverrides()),
        );
        if (!result) return;

        batchOperation.value = result;
        scheduleBatchOperationPoll(result.batch_id);
        notify("Проверка запущена для " + result.total + " товаров");
    }

    async function askChatGptForAllProducts() {
        if (!selectedBatch.value || batchOperationRunning.value) return;
        if (!chatGpt.value?.authenticated) {
            error.value = "Сначала подключите ChatGPT в блоке подключения выше.";
            return;
        }

        const total = selectedBatch.value.summary.products;
        if (!await confirmAction({
            title: "Спросить ChatGPT по всем товарам (" + total + ")?",
            description: "Каждый товар будет отправлен ChatGPT отдельным запросом. Запросы выполняются параллельно с ограничением нагрузки; ошибка одного товара не останавливает остальные.",
            confirmLabel: "Начать анализ",
        })) return;

        const result = await run("chatgpt-all", () =>
            api.analyzeBatchWithChatGpt(
                selectedBatch.value!.id,
                selectedDonors.value,
                currentProductOverrides(),
            ),
        );
        if (!result) return;

        batchOperation.value = result;
        scheduleBatchOperationPoll(result.batch_id);
        notify("ChatGPT-анализ запущен для " + result.total + " товаров");
    }

    async function openBatch(
        id: number,
        requestedProductId: number | null = null,
        options: { syncRoute?: boolean; resetFilters?: boolean } = {},
    ) {
        const syncRoute = options.syncRoute ?? true;
        const resetFilters = options.resetFilters ?? true;
        const batchChanged = selectedBatch.value?.id !== id;

        if (resetFilters && batchChanged) {
            productQuery.value = "";
            productStatusFilter.value = ALL_FILTER_VALUE;
            attributeStatusFilter.value = ALL_FILTER_VALUE;
        }

        const batch = await run("batch", () => api.batch(id));
        if (!batch) return false;

        clearBatchOperationPoll();
        batchOperation.value = null;
        selectedBatch.value = batch;
        void loadBatchOperation(id);
        tab.value = "review";

        const requested = requestedProductId
            ? batch.products?.find((product) => product.id === requestedProductId)
            : null;
        const first = requested || batch.products?.[0];

        if (first) {
            await openProduct(first.id, {
                syncRoute: false,
                resetAttributeFilter: resetFilters && selectedProduct.value?.id !== first.id,
            });
        } else {
            selectedProduct.value = null;
        }

        if (syncRoute) await writeRoute("push");
        return true;
    }

    async function removeBatch(batch: AttributeBatch) {
        const requestKey = `batch-remove-${batch.id}`;
        if (busy.value === requestKey) return;
        if (!await confirmAction({
            title: `Удалить обработку «${batch.name}»?`,
            description: "Будут удалены загруженный CSV, отчёты, страницы доноров и все результаты этой обработки. Шаблон останется.",
            confirmLabel: "Удалить обработку",
            color: "error",
        })) return;

        const result = await run(requestKey, () => api.removeBatch(batch.id));
        if (!result) return;

        if (selectedBatch.value?.id === batch.id) {
            clearBatchOperationPoll();
            batchOperation.value = null;
            selectedBatch.value = null;
            selectedProduct.value = null;
            historyItems.value = [];
            tab.value = "start";
            await writeRoute("replace");
        }

        await loadWorkspace();
        notify(`Обработка удалена · товаров: ${result.deleted.products}, файлов: ${result.deleted.files}`);
    }

    async function refreshProductHistory(productId = selectedProduct.value?.id) {
        if (!productId) {
            historyItems.value = [];
            return;
        }
        try {
            const history = await api.productHistory(productId);
            if (selectedProduct.value?.id === productId) historyItems.value = history.items;
        } catch {
            error.value = "Не удалось обновить историю изменений товара.";
        }
    }

    async function openProduct(
        id: number,
        options: { syncRoute?: boolean; resetAttributeFilter?: boolean } = {},
    ) {
        const syncRoute = options.syncRoute ?? true;
        const resetAttributeFilter = options.resetAttributeFilter ?? true;
        if (resetAttributeFilter && selectedProduct.value?.id !== id) {
            attributeStatusFilter.value = ALL_FILTER_VALUE;
        }

        const token = ++productRequestToken;
        loadingProductId.value = id;
        error.value = "";

        let product: AttributeProduct;
        try {
            product = await api.product(id);
        } catch (caught) {
            if (token === productRequestToken) error.value = errorMessage(caught);
            return false;
        } finally {
            if (token === productRequestToken) loadingProductId.value = null;
        }

        if (token !== productRequestToken) return false;

        selectedProduct.value = product;
        historyItems.value = [];
        selectedDonors.value = [...(product.selected_donor_ids || [])];
        donorUrlOverrides.value = { ...(product.donor_url_overrides || {}) };
        allowedValues.resetAllowedOptionState();

        void Promise.all([
            api.donorRecommendations(id).catch(() => ({ items: [] })),
            api.productHistory(id).catch(() => ({ items: [] })),
        ]).then(([recommendations, history]) => {
            if (token !== productRequestToken) return;
            donorRecommendations.value = recommendations.items;
            historyItems.value = history.items;
            if (!selectedDonors.value.length) {
                selectedDonors.value = recommendations.items
                    .filter((item) => item.recommended)
                    .slice(0, 4)
                    .map((item) => item.id);
            }
        });

        if (syncRoute) await writeRoute("push");
        return true;
    }

    function toggleDonor(id: number) {
        selectedDonors.value = selectedDonors.value.includes(id)
            ? selectedDonors.value.filter((item) => item !== id)
            : [...selectedDonors.value, id];
    }

    function moveDonor(index: number, direction: number) {
        const next = index + direction;
        if (next < 0 || next >= selectedDonors.value.length) return;

        const copy = [...selectedDonors.value];
        const current = copy[index];
        const target = copy[next];
        if (current === undefined || target === undefined) return;

        copy[index] = target;
        copy[next] = current;
        selectedDonors.value = copy;
    }

    async function processDonors() {
        if (!selectedProduct.value || !selectedDonors.value.length) {
            error.value = "Выберите доноров в порядке приоритета.";
            return;
        }

        const result = await run("process", () =>
            api.processProduct(selectedProduct.value!.id, selectedDonors.value, donorUrlOverrides.value),
        );
        if (!result) return;

        selectedProduct.value = result.product;
        await refreshBatch();

        const reports = result.report.reports || [];
        const opened = reports.filter((item) => ["parsed", "no_attributes"].includes(item.status)).length;
        const found = reports.reduce((sum, item) => sum + (item.attributes_found || 0), 0);
        const mapped = reports.reduce((sum, item) => sum + (item.mapped || 0), 0);
        const ambiguous = reports.reduce((sum, item) => sum + (item.ambiguous || 0), 0);
        const unknown = reports.reduce((sum, item) => sum + (item.unknown || 0), 0);
        const alreadyFilled = reports.reduce((sum, item) => sum + (item.already_filled || 0), 0);
        const failed = reports.length - opened;

        notify(
            `Страниц открыто: ${opened} · характеристик извлечено: ${found} · предложений: ${mapped}`
            + (alreadyFilled ? ` · уже заполнено: ${alreadyFilled}` : "")
            + (ambiguous ? ` · требуют сопоставления: ${ambiguous}` : "")
            + (unknown ? ` · вне справочника: ${unknown}` : "")
            + (failed ? ` · проблем: ${failed}` : ""),
        );
    }

    async function useSimilar() {
        if (!selectedProduct.value) return;
        const result = await run("similar", () => api.useSimilar(selectedProduct.value!.id));
        if (result) {
            selectedProduct.value = result.product;
            await refreshBatch();
            notify(`Добавлено предложений: ${result.changed}`);
        }
    }

    async function askChatGpt() {
        if (!selectedProduct.value) return;
        if (!chatGpt.value?.authenticated) {
            error.value = "Сначала подключите ChatGPT в блоке подключения выше.";
            return;
        }

        const result = await run("chatgpt-product", () =>
            api.analyzeProductWithChatGpt(
                selectedProduct.value!.id,
                selectedDonors.value,
                donorUrlOverrides.value,
            ),
        );
        if (!result) return;

        selectedProduct.value = result.product;
        await refreshBatch();
        const warnings = result.analysis.warnings.length;
        notify(
            warnings
                ? `ChatGPT: предложений ${result.changed}, предупреждений ${warnings}`
                : `ChatGPT: добавлено предложений ${result.changed}`,
        );
    }

    async function assignCurrentTemplate(selection: unknown) {
        if (!selectedProduct.value) return;
        const templateId = Number(selection);
        if (!templateId) return;

        const result = await run(
            "assign-template",
            () => api.assignTemplate(selectedProduct.value!.id, templateId),
        );
        if (result) {
            selectedProduct.value = result;
            await refreshBatch();
        }
    }

    async function exportReadyOnly() {
        if (!selectedBatch.value) return;
        const result = await run("export-ready", () => api.export(selectedBatch.value!.id, true));
        if (result) {
            window.location.href = `/api/attribute-assistant/batches/${selectedBatch.value.id}/download`;
        }
    }

    async function restoreHistory(id: number) {
        if (!selectedProduct.value || !await confirmAction({
            title: "Восстановить состояние товара?",
            description: "Текущие решения по атрибутам будут заменены выбранным состоянием.",
            confirmLabel: "Восстановить",
        })) return;

        const product = await run(
            "history-restore",
            () => api.restoreProduct(selectedProduct.value!.id, id),
        );
        if (product) {
            selectedProduct.value = product;
            await openProduct(product.id);
            await refreshBatch();
        }
    }

    async function valueAction(
        value: AttributeValue,
        action: "accept" | "reject" | "dash",
        manual = "",
    ) {
        const dashReason = action === "dash"
            ? await promptValue({
            title: "Технический пропуск",
            label: "Причина",
            defaultValue: "Не найдено после проверки источников",
            confirmLabel: "Поставить «-»",
        }) || ""
            : "";

        if (action === "dash" && !dashReason) return;

        const updated = await run(`value-${value.id}`, () =>
            api.updateValue(value.id, { action, value: manual, dash_reason: dashReason }),
        );
        if (!updated || !selectedProduct.value?.values) return;

        const index = selectedProduct.value.values.findIndex((item) => item.id === updated.id);
        if (index >= 0) selectedProduct.value.values[index] = updated;
        await refreshBatch();
    }

    async function removeOutsideTemplateValue(value: AttributeValue) {
        if (value.is_in_template) return;
        if (!await confirmAction({
            title: `Удалить атрибут «${value.name}»?`,
            description: "Он исчезнет из текущей обработки и последующих экспортов. Шаблон не изменится.",
            confirmLabel: "Удалить атрибут",
            color: "error",
        })) return;

        const result = await run(`value-remove-${value.id}`, () => api.removeExtraValue(value.id));
        if (!result) return;

        selectedProduct.value = result.product;
        await refreshBatch();
        notify("Атрибут вне шаблона удалён");
    }

    async function selectFinalValue(value: AttributeValue, selection: unknown) {
        const parts = (Array.isArray(selection) ? selection : [selection])
            .filter((item): item is string => typeof item === "string" && Boolean(item));
        const selected = value.is_composite
            ? parts.sort((left, right) => left.localeCompare(right, "ru")).join("/")
            : parts[0] || "";

        if (!selected) return;
        await valueAction(value, "accept", selected);
        if (!error.value) notify(`Итог для «${value.name}» сохранён`);
    }

    async function addUnknown(
        value: AttributeValue,
        unknown: NonNullable<AttributeValue["source_details"]["unknown_values"]>[number],
    ) {
        if (!value.field_id) return;
        const confirmed = await confirmAction({
            title: `Добавить «${unknown.value}» в справочник?`,
            description: "Значение станет разрешённым для этого атрибута и будет применено к товару.",
            confirmLabel: "Добавить и применить",
        });
        if (!confirmed) return;

        const result = await run(`dictionary-${value.id}`, async () => {
            await api.addAllowedValue(value.field_id!, unknown.value);
            return api.updateValue(value.id, { action: "accept", value: unknown.value });
        });

        if (result && selectedProduct.value?.values) {
            const index = selectedProduct.value.values.findIndex((item) => item.id === result.id);
            if (index >= 0) selectedProduct.value.values[index] = result;
            await refreshBatch();
            notify("Значение добавлено в справочник");
        }
    }

    async function rememberUnknownValue(
        value: AttributeValue,
        unknown: NonNullable<AttributeValue["source_details"]["unknown_values"]>[number],
        index: number,
    ) {
        const key = unknownSelectionKey(value, index);
        const allowedValueId = unknownSelections.value[key];
        if (!unknown.donor_id || !allowedValueId) {
            error.value = "Выберите разрешённое значение для этого донора.";
            return;
        }

        const result = await run(`value-mapping-${value.id}-${index}`, () =>
            api.rememberValueMapping(value.id, {
                donor_id: unknown.donor_id!,
                raw_value: unknown.value,
                allowed_value_id: allowedValueId,
            }),
        );
        if (!result || !selectedProduct.value?.values) return;

        const valueIndex = selectedProduct.value.values.findIndex((item) => item.id === result.value.id);
        if (valueIndex >= 0) selectedProduct.value.values[valueIndex] = result.value;
        delete unknownSelections.value[key];
        await refreshBatch();
        notify("Значение применено и запомнено для донора");
    }

    async function refreshBatch() {
        if (!selectedBatch.value) return;
        const batch = await api.batch(selectedBatch.value.id);
        selectedBatch.value = batch;
        const index = workspace.value.batches.findIndex((item) => item.id === batch.id);
        if (index >= 0) workspace.value.batches[index] = batch;
        await refreshProductHistory();
    }

    async function bulk(action: "accept_high" | "fill_dashes") {
        if (!selectedBatch.value) return;
        const confirmed = await confirmAction({
            title: action === "accept_high" ? "Принять уверенные предложения?" : "Заполнить технические пропуски?",
            description: action === "accept_high"
                ? "Будут подтверждены все предложения с уверенностью от 90%."
                : "Во все оставшиеся неконфликтные поля будет поставлен технический пропуск.",
            confirmLabel: action === "accept_high" ? "Принять" : "Заполнить",
        });
        if (!confirmed) return;

        const result = await run("bulk", () =>
            api.bulk(selectedBatch.value!.id, {
                action,
                minimum_confidence: 90,
                dash_reason: "Не найдено после проверки источников",
            }),
        );
        if (result) {
            selectedBatch.value = result.batch;
            if (selectedProduct.value) await openProduct(selectedProduct.value.id);
            notify(`Изменено значений: ${result.changed}`);
        }
    }

    async function exportBatch() {
        if (!selectedBatch.value) return;
        const result = await run("export", () => api.export(selectedBatch.value!.id));
        if (!result) return;
        window.location.href = `/api/attribute-assistant/batches/${selectedBatch.value.id}/download`;
    }

    function dispose() {
        clearBatchOperationPoll();
        productRequestToken += 1;
    }

    return {
        selectedBatch,
        selectedProduct,
        loadingProductId,
        selectedDonors,
        unknownSelections,
        donorRecommendations,
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
        setRouteFilters,
        createBatch,
        clearBatchOperationPoll,
        currentProductOverrides,
        loadBatchOperation,
        processAllProducts,
        askChatGptForAllProducts,
        openBatch,
        removeBatch,
        refreshProductHistory,
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
        refreshBatch,
        bulk,
        exportBatch,
        dispose,
    };
}

export type AttributeReviewContext = ReturnType<typeof useAttributeReview>;