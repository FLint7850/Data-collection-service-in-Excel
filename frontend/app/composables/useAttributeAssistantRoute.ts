import type {
    AttributeAssistantContext,
    AttributeAssistantTab,
    AttributeRouteWriteMode,
} from "~/composables/useAttributeAssistant";
import type { AttributeTemplatesContext } from "~/composables/useAttributeTemplates";
import type { AttributeReviewContext } from "~/composables/useAttributeReview";
import {
    ALL_FILTER_VALUE,
    positiveRouteId,
    routeQueryValue,
} from "~/utils/attribute-assistant";

export function useAttributeAssistantRoute(
    assistant: AttributeAssistantContext,
    templates: AttributeTemplatesContext,
    review: AttributeReviewContext,
) {
    const route = useRoute();
    const router = useRouter();

    let routeApplyToken = 0;
    let routeStateReady = false;
    let applyingRouteState = false;
    let writtenRoute = "";
    let filterRouteTimer: ReturnType<typeof setTimeout> | null = null;

    function routeSegments(): string[] {
        const raw = route.params.state;
        const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
        return values
            .flatMap((value) => String(value).split("/"))
            .filter(Boolean);
    }

    const mainTabItems = computed(() => [
        { label: "Новая обработка", icon: "i-lucide-sparkles", value: "start" },
        { label: "Шаблоны", icon: "i-lucide-layout-template", value: "templates" },
        {
            label: "Проверка",
            icon: "i-lucide-list-checks",
            value: "review",
            disabled: !review.selectedBatch.value,
            badge: review.selectedBatch.value?.summary.needs_review || undefined,
        },
    ]);

    function assistantRouteLocation() {
        let path = "/attribute-assistant/new";
        const query: Record<string, string> = {};

        if (assistant.tab.value === "templates") {
            path = templates.templateDetails.value
                ? `/attribute-assistant/templates/${templates.templateDetails.value.id}`
                : "/attribute-assistant/templates";
        } else if (assistant.tab.value === "review" && review.selectedBatch.value) {
            path = `/attribute-assistant/review/${review.selectedBatch.value.id}`;
            if (review.selectedProduct.value) path += `/${review.selectedProduct.value.id}`;
            if (review.productQuery.value) query.product_query = review.productQuery.value;
            if (review.productStatusFilter.value !== ALL_FILTER_VALUE) {
                query.product_status = review.productStatusFilter.value;
            }
            if (
                review.selectedProduct.value
                && review.attributeStatusFilter.value !== ALL_FILTER_VALUE
            ) {
                query.attribute_status = review.attributeStatusFilter.value;
            }
        }

        return { path, query };
    }

    async function writeAssistantRoute(mode: AttributeRouteWriteMode = "replace") {
        if (!import.meta.client) return;
        const location = assistantRouteLocation();
        const target = router.resolve(location).fullPath;
        if (target === route.fullPath) return;

        writtenRoute = target;
        if (mode === "push") await router.push(location);
        else await router.replace(location);
    }

    function applyRouteFilters() {
        review.setRouteFilters({
            productQuery: routeQueryValue(route.query.product_query),
            productStatus: routeQueryValue(route.query.product_status),
            attributeStatus: routeQueryValue(route.query.attribute_status),
        });
    }

    async function applyAssistantRoute() {
        const token = ++routeApplyToken;
        applyingRouteState = true;
        applyRouteFilters();

        const [section, firstId, secondId] = routeSegments();

        try {
            if (section === "templates") {
                assistant.tab.value = "templates";
                const templateId = positiveRouteId(firstId);
                if (templateId && templates.templateDetails.value?.id !== templateId) {
                    await templates.openTemplate(templateId, false);
                }
            } else if (section === "review") {
                const batchId = positiveRouteId(firstId);
                const productId = positiveRouteId(secondId);

                if (batchId) {
                    const opened = await review.openBatch(batchId, productId, {
                        syncRoute: false,
                        resetFilters: false,
                    });
                    if (!opened) {
                        review.selectedBatch.value = null;
                        review.selectedProduct.value = null;
                        assistant.tab.value = "start";
                    }
                } else if (review.selectedBatch.value) {
                    assistant.tab.value = "review";
                } else {
                    assistant.tab.value = "start";
                }
            } else {
                assistant.tab.value = "start";
            }
        } finally {
            if (token === routeApplyToken) {
                applyingRouteState = false;
                routeStateReady = true;
            }
        }

        if (token === routeApplyToken) {
            await writeAssistantRoute("replace");
        }
    }

    async function changeMainTab(value: string | number) {
        const next = String(value) as AttributeAssistantTab;
        if (!(new Set<AttributeAssistantTab>(["start", "templates", "review"])).has(next)) return;
        if (next === "review" && !review.selectedBatch.value) return;

        assistant.tab.value = next;
        await writeAssistantRoute("push");
    }

    async function useTemplateForNewBatch(id: number) {
        assistant.selectedTemplateId.value = id;
        assistant.tab.value = "start";
        await writeAssistantRoute("push");
    }

    const stopFilterWatch = watch(
        [review.productQuery, review.productStatusFilter, review.attributeStatusFilter],
        () => {
            if (!routeStateReady || applyingRouteState || assistant.tab.value !== "review") return;
            if (filterRouteTimer) clearTimeout(filterRouteTimer);

            filterRouteTimer = setTimeout(() => {
                filterRouteTimer = null;
                if (!routeStateReady || applyingRouteState || assistant.tab.value !== "review") return;
                void writeAssistantRoute("replace");
            }, 180);
        },
    );

    const stopRouteWatch = watch(
        () => route.fullPath,
        (fullPath) => {
            if (fullPath === writtenRoute) {
                writtenRoute = "";
                return;
            }
            if (routeStateReady) void applyAssistantRoute();
        },
    );

    assistant.setRouteWriter(writeAssistantRoute);

    function dispose() {
        if (filterRouteTimer) clearTimeout(filterRouteTimer);
        filterRouteTimer = null;
        stopFilterWatch();
        stopRouteWatch();
        assistant.setRouteWriter(null);
    }

    return {
        mainTabItems,
        assistantRouteLocation,
        writeAssistantRoute,
        applyRouteFilters,
        applyAssistantRoute,
        changeMainTab,
        useTemplateForNewBatch,
        dispose,
    };
}

export type AttributeAssistantRouteContext = ReturnType<typeof useAttributeAssistantRoute>;