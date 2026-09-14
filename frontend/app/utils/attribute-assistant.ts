import type {
    AttributeProcessingMode,
    AttributeProduct,
    AttributeSource,
    AttributeValue,
} from "~/types/attribute-assistant";

export const ALL_FILTER_VALUE = "all";
export const PRODUCT_STATUS_VALUES = new Set(["ready", "conflict", "missing", "outside_template", "needs_review"]);
export const ATTRIBUTE_STATUS_VALUES = new Set(["outside_template", "conflict", "suggested", "no_suggestion"]);
export const ALLOWED_OPTIONS_PAGE_SIZE = 40;

export const processingModeItems: Array<{ label: string; value: AttributeProcessingMode }> = [
    { label: "Только проверить, без предложений в итог", value: "check" },
    { label: "Показать предложения, решение вручную", value: "suggest" },
    { label: "Автопринять только точные 100%", value: "auto_exact" },
    { label: "Автопринять уверенное от главного донора", value: "auto_primary" },
    { label: "Автопринять подтверждённое от 95%", value: "auto_confident" },
    { label: "Автопринять всё найденное в справочнике", value: "auto_all" },
];

export const templateUpdateModeItems = [
    { label: "Объединить", value: "merge" },
    { label: "Заменить значения из файла", value: "replace" },
];

export const templateFieldTypeItems = [
    { label: "Из справочника", value: "select" },
    { label: "Текст", value: "text" },
    { label: "Число", value: "number" },
    { label: "Габариты", value: "dimensions" },
    { label: "Да / нет", value: "boolean" },
];

export const inputModeItems = [
    { label: "CSV-файл", icon: "i-lucide-file-spreadsheet", value: "csv" },
    { label: "Ссылки сайта", icon: "i-lucide-link", value: "urls" },
];

export function routeQueryValue(value: unknown): string {
    return Array.isArray(value) ? String(value[0] || "") : String(value || "");
}

export function positiveRouteId(value: string | undefined): number | null {
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function matchesProductStatus(product: AttributeProduct, status: string): boolean {
    if (status === ALL_FILTER_VALUE) return true;
    if (status === "conflict") return product.status === status || product.counts.conflicts > 0;
    if (status === "missing") return product.status === status || product.counts.missing > 0;
    if (status === "outside_template") return product.counts.outside_template > 0;
    return product.status === status;
}

export function bestCandidate(value: AttributeValue) {
    return [...(value.source_details.candidates || [])].sort((left, right) => {
        const priorityDifference = (left.priority ?? 999) - (right.priority ?? 999);
        return priorityDifference || (right.confidence ?? 0) - (left.confidence ?? 0);
    })[0];
}

export function displayedProposal(value: AttributeValue) {
    const nearest = ["suggested", "unknown"].includes(value.status)
        ? value.source_details.unknown_values?.flatMap((item) => item.suggestions || [])[0]
        : "";
    return value.proposed_value || bestCandidate(value)?.value || nearest || "";
}

export function originalValueHints(value: AttributeValue): string[] {
    const hints = value.source_details.current_value_hint ? [value.source_details.current_value_hint] : [];
    for (const item of value.source_details.unknown_values || []) {
        hints.push(`${item.source_name}: ${item.value} — ${item.reason}`);
    }
    return [...new Set(hints)];
}

export function attributeValuesMatch(left: string, right: string): boolean {
    return left.trim().toLowerCase() === right.trim().toLowerCase();
}

export function hasPendingProposal(value: AttributeValue): boolean {
    if (value.status === "rejected" || value.status === "dash") return false;
    const proposal = displayedProposal(value);
    return Boolean(proposal && !attributeValuesMatch(proposal, value.final_value));
}

export function matchesAttributeStatus(value: AttributeValue, status: string): boolean {
    if (status === ALL_FILTER_VALUE) return true;
    if (status === "outside_template") return !value.is_in_template;
    if (!value.is_in_template) return false;
    const reviewStatus = value.status === "unknown"
        ? (hasPendingProposal(value) ? "suggested" : "conflict") : value.status;
    if (status === "conflict") return reviewStatus === "conflict";
    if (status === "suggested") return reviewStatus === "suggested" || (reviewStatus !== "conflict" && hasPendingProposal(value));
    if (status === "no_suggestion") return !["conflict", "suggested"].includes(reviewStatus) && !hasPendingProposal(value);
    return true;
}

export function selectedFinalParts(value: AttributeValue) {
    const selected = value.status === "rejected"
        ? value.final_value
        : value.final_value || displayedProposal(value);
    return new Set(selected.split("/").map((item) => item.trim()).filter(Boolean));
}

export function selectedFinalValue(value: AttributeValue) {
    if (value.final_value && value.final_value !== "-") return value.final_value;
    if (value.status === "rejected") return "";
    return displayedProposal(value);
}

export function sourceStatusText(
    status: string,
    attributesFound = 0,
    mapped = 0,
    ambiguous = 0,
    unknown = 0,
    alreadyFilled = 0,
) {
    if (status === "parsed") {
        return `Извлечено: ${attributesFound} · сопоставлено: ${mapped} · проверено заполненных: ${alreadyFilled} · не сопоставлено: ${ambiguous} · вне справочника: ${unknown}`;
    }
    if (status === "resolved") return "Ссылка найдена";
    if (status === "no_attributes") return "Страница открыта, характеристик нет";
    if (status === "not_found") return "Не найдена";
    if (status === "error") return "Ошибка";
    return status || "Нет данных";
}

export function sourceTitle(source: string) {
    const labels: Record<string, string> = {
        current_csv: "Исходный CSV сайта",
        own_site: "Официальный сайт",
        manual: "Ручной выбор",
        similar: "Похожий товар",
        ai: "ChatGPT",
    };
    return labels[source] || source || "Источник";
}

export function sourceKind(source: AttributeSource) {
    if (source.source_type) return source.source_type;
    if (source.role === "chatgpt") return "chatgpt";
    if (source.donor_id) return "donor";
    return "site";
}

export function sourceKindLabel(source: AttributeSource) {
    return {
        chatgpt: "ChatGPT",
        donor: "Донор",
        site: "Страница сайта",
    }[sourceKind(source)];
}

export function displayedProposalSource(value: AttributeValue) {
    const candidate = bestCandidate(value);
    return sourceTitle(value.proposed_value ? value.source : candidate?.source || "");
}

export function displayedProposalConfidence(value: AttributeValue) {
    return value.confidence || bestCandidate(value)?.confidence || 0;
}

export function isTechnicalDash(value: string) {
    return /^[-–—−]$/u.test(value.trim());
}

export function valueStatusLabel(value: AttributeValue) {
    if (!value.is_in_template) return "Вне шаблона";
    if (value.status === "conflict") return "Конфликт";
    if (value.status === "unknown") return hasPendingProposal(value) ? "Есть предложение" : "Конфликт";
    if (value.status === "dash") return "Технический пропуск";
    if (value.status === "rejected") return "Отклонено";
    if (value.status === "approved") return "Принято";
    if (value.status === "suggested") return "Есть предложение";
    if (value.current_value) return value.source === "current_site" ? "Сохранено со страницы" : "Сохранено из CSV";
    return "Не заполнено";
}

export function valueStatusColor(value: AttributeValue): "error" | "warning" | "success" | "neutral" {
    if (!value.is_in_template) return "warning";
    if (value.status === "conflict" || value.status === "rejected") return "error";
    if (value.status === "unknown") return hasPendingProposal(value) ? "warning" : "error";
    if (value.status === "suggested") return "warning";
    if (value.current_value || value.status === "approved") return "success";
    return "neutral";
}

export function formatHistoryDate(value: string) {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
        ? value
        : new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(date);
}

export function finalAllowedMenuKey(value: AttributeValue) {
    return `final-${value.id}`;
}

export function unknownAllowedMenuKey(value: AttributeValue, index: number) {
    return `unknown-${value.id}-${index}`;
}

export function unknownSelectionKey(value: AttributeValue, index: number) {
    return `${value.id}:${index}`;
}
