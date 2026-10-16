import type {
    AttributeProcessingMode,
    AttributeAssistantSettings,
    AttributeProduct,
    AttributeSource,
    AttributeValue,
} from "~/types/attribute-assistant";

export const ALL_FILTER_VALUE = "all";
export const PRODUCT_STATUS_VALUES = new Set(["ready", "conflict", "missing", "outside_template", "needs_review"]);
export const ATTRIBUTE_STATUS_VALUES = new Set(["outside_template", "conflict", "suggested", "from_source", "unfilled"]);
export function processingModeItems(
    settings: AttributeAssistantSettings | null,
): Array<{ label: string; value: AttributeProcessingMode }> {
    const exact = settings?.exact_value_confidence ?? 100;
    const primary = settings?.auto_primary_confidence ?? 85;
    const confident = settings?.auto_confident_confidence ?? 95;
    const labels: Record<AttributeProcessingMode, string> = {
        check: "Только проверить, без предложений в итог",
        suggest: "Показать предложения, решение вручную",
        auto: `Автопринять подтверждённое от ${confident}%`,
        auto_exact: `Автопринять только точные ${exact}%`,
        auto_primary: `Автопринять от главного донора от ${primary}%`,
        auto_confident: `Автопринять подтверждённое от ${confident}%`,
        auto_all: "Автопринять всё найденное в справочнике",
    };
    const modes = settings?.processing_modes || [
        "check",
        "suggest",
        "auto_exact",
        "auto_primary",
        "auto_confident",
        "auto_all",
    ];
    return modes.map((value) => ({ value, label: labels[value] }));
}

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

export function matchesProductStatus(
    product: Pick<AttributeProduct, "status" | "counts">,
    status: string,
): boolean {
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

export function addableUnknownProposal(value: AttributeValue): string {
    if (value.status === "rejected" || value.status === "approved") return "";
    if (value.current_value.trim() && !isTechnicalDash(value.current_value)) return "";
    const proposals = new Map<string, string>();
    for (const item of value.source_details.unknown_values || []) {
        const proposal = item.value.trim();
        if (proposal) proposals.set(proposal.toLowerCase(), proposal);
    }
    return proposals.size === 1 ? [...proposals.values()][0]! : "";
}

function rawProposal(value: AttributeValue) {
    const nearest = ["suggested", "unknown"].includes(value.status)
        ? value.source_details.unknown_values?.flatMap((item) => item.suggestions || [])[0]
        : "";
    return value.proposed_value || bestCandidate(value)?.value || nearest || addableUnknownProposal(value) || "";
}

function unchangedProposal(value: AttributeValue): boolean {
    if (["conflict", "rejected", "dash"].includes(value.status)) return false;
    const proposal = rawProposal(value);
    return Boolean(value.current_value && value.final_value && proposal
        && attributeValuesMatch(value.current_value, value.final_value)
        && attributeValuesMatch(proposal, value.final_value)
        && (value.source_details.candidates || []).every((candidate) => attributeValuesMatch(candidate.value, value.final_value)));
}

export function displayedProposal(value: AttributeValue) {
    const proposal = rawProposal(value);
    // A source can confirm the selected result while other sources disagree.
    // Keep that disagreement visible without presenting the result as a change.
    return value.final_value && attributeValuesMatch(proposal, value.final_value) ? "" : proposal;
}

export function attributeReviewStatus(value: AttributeValue) {
    if (unchangedProposal(value) && ["suggested", "unknown"].includes(value.status)) return "kept";
    if (value.current_value.trim() && !isTechnicalDash(value.current_value)
        && ["suggested", "unknown"].includes(value.status)) return "conflict";
    if (addableUnknownProposal(value)) return "suggested";
    if (value.status === "unknown") return hasPendingProposal(value) ? "suggested" : "conflict";
    return value.status;
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

type UnknownSourceValue = NonNullable<AttributeValue["source_details"]["unknown_values"]>[number];

export function sourceEvidenceCount(value: AttributeValue): number {
    return (value.source_details.candidates?.length || 0)
        + (value.source_details.unknown_values?.length || 0);
}

export function unknownSourceMatchesSelected(
    value: AttributeValue,
    unknown: UnknownSourceValue,
): boolean {
    const selected = value.final_value.trim() || value.current_value.trim();
    if (!selected) return false;
    return unknownSourceMatchesExactly(value, unknown)
        || Boolean(unknown.suggestions?.[0]
            && attributeValuesMatch(unknown.suggestions[0], selected));
}

export function unknownSourceMatchesExactly(
    value: AttributeValue,
    unknown: UnknownSourceValue,
): boolean {
    const selected = value.final_value.trim() || value.current_value.trim();
    return Boolean(selected) && attributeValuesMatch(unknownReviewValue(unknown), selected);
}

export function unknownReviewValue(unknown: UnknownSourceValue): string {
    return unknown.normalized_value?.trim() || unknown.value.trim();
}

export function canAddUnknownFromNearest(
    value: AttributeValue,
    unknown: UnknownSourceValue,
): boolean {
    const reviewValue = unknownReviewValue(unknown);
    const hasNearest = (unknown.suggestions || []).some((item) => item.trim());
    if (!reviewValue || !hasNearest || !value.field_id) return false;

    const exactCandidate = (value.source_details.candidates || [])
        .some((candidate) => attributeValuesMatch(candidate.value, reviewValue));
    const exactAllowedValue = (value.allowed_values || [])
        .some((allowed) => attributeValuesMatch(allowed.value, reviewValue));
    const exactSuggestion = (unknown.suggestions || [])
        .some((suggestion) => attributeValuesMatch(suggestion, reviewValue));
    return !exactCandidate && !exactAllowedValue && !exactSuggestion;
}

export function hasPendingProposal(value: AttributeValue): boolean {
    if (value.status === "rejected" || value.status === "dash") return false;
    const proposal = displayedProposal(value);
    const newValue = addableUnknownProposal(value);
    if (newValue && attributeValuesMatch(proposal, newValue)) return false;
    return Boolean(proposal && !attributeValuesMatch(proposal, value.final_value));
}

export function canConfirmConflictFinal(value: AttributeValue): boolean {
    return value.is_in_template && attributeReviewStatus(value) === "conflict"
        && Boolean(value.final_value) && !isTechnicalDash(value.final_value)
        && !hasPendingProposal(value);
}

export function matchesAttributeStatus(value: AttributeValue, status: string): boolean {
    if (status === ALL_FILTER_VALUE) return true;
    if (status === "outside_template") return !value.is_in_template;
    if (!value.is_in_template) return false;
    const effectiveStatus = attributeReviewStatus(value);
    if (status === "conflict") return effectiveStatus === "conflict";
    if (status === "suggested") return (!value.current_value.trim() || isTechnicalDash(value.current_value))
        && (effectiveStatus === "suggested" || (effectiveStatus !== "conflict" && hasPendingProposal(value)));
    if (status === "from_source" || status === "unfilled") {
        if (["conflict", "suggested"].includes(effectiveStatus) || hasPendingProposal(value)) return false;
        const selectedValue = value.final_value.trim() || value.current_value.trim();
        const filled = Boolean(selectedValue) && !isTechnicalDash(selectedValue);
        return status === "from_source" ? filled : !filled;
    }
    return true;
}

export function selectedFinalParts(value: AttributeValue) {
    const selected = value.status === "rejected"
        ? value.final_value
        : value.final_value || displayedProposal(value);
    return new Set(selected.split("/").map((item) => item.trim()).filter(Boolean));
}

export function selectedFinalValue(value: AttributeValue) {
    if (value.final_value) return value.final_value;
    if (value.status === "rejected") return "";
    return hasPendingProposal(value) ? displayedProposal(value) : "";
}

type FinalSelectOption = {
    id: number;
    value: string;
    disabled?: boolean;
};

export function finalSelectOptions(
    value: AttributeValue,
    options: Array<{ id: number; value: string }>,
): FinalSelectOption[] {
    if (!isTechnicalDash(value.final_value)) return options;

    const dash = value.final_value.trim();
    const result: FinalSelectOption[] = options.map((option) => (
        isTechnicalDash(option.value) ? { ...option, disabled: true } : option
    ));
    if (!result.some((option) => option.value === dash)) {
        result.unshift({ id: Number.MIN_SAFE_INTEGER + value.id, value: dash, disabled: true });
    }
    return result;
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
    if (unchangedProposal(value)) return "Без изменений";
    const reviewStatus = attributeReviewStatus(value);
    if (reviewStatus === "conflict") return "Конфликт";
    if (reviewStatus === "suggested") return "Есть предложение";
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
    if (unchangedProposal(value)) return "success";
    const reviewStatus = attributeReviewStatus(value);
    if (reviewStatus === "conflict" || value.status === "rejected") return "error";
    if (reviewStatus === "suggested") return "warning";
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
