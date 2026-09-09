import { attributeAssistantService as api } from "~/services/attribute-assistant.service";
import type { AttributeValue } from "~/types/attribute-assistant";
import {
    ALLOWED_OPTIONS_PAGE_SIZE,
    displayedProposal,
} from "~/utils/attribute-assistant";

type AllowedSelectInstance = {
    viewportRef?: HTMLElement | { value?: HTMLElement | null } | null;
};

export function useAttributeAllowedValues() {
    const allowedOptionCache = ref<Record<number, Array<{ id: number; value: string }>>>({});
    const allowedSearchQueries = ref<Record<number, string>>({});
    const searchingAllowedValueIds = ref<Set<number>>(new Set());
    const allowedOptionPages = ref<Record<number, {
        query: string;
        total: number;
        matched: number;
        hasMore: boolean;
    }>>({});

    const allowedSearchTimers = new Map<number, ReturnType<typeof setTimeout>>();
    const allowedRequestTokens = new Map<number, number>();
    const allowedSelectRefs = new Map<string, AllowedSelectInstance>();
    const allowedSelectRefCallbacks = new Map<string, (instance: unknown) => void>();
    const allowedScrollBindings = new Map<string, {
        valueId: number;
        check: () => void;
        cleanup: () => void;
    }>();

    function optionsFor(value: AttributeValue) {
        const loaded = allowedOptionCache.value[value.id] || value.allowed_values;
        const result = [...loaded];
        const pinned = [value.final_value, displayedProposal(value)]
            .flatMap((item) => value.is_composite ? item.split("/") : [item])
            .map((item) => item.trim())
            .filter((item) => item && item !== "-");

        for (const item of [...new Set(pinned)].reverse()) {
            if (!result.some((option) => option.value === item)) {
                result.unshift({ id: -result.length - 1, value: item });
            }
        }
        return result;
    }

    function setAllowedSearchLoading(valueId: number, loading: boolean) {
        const next = new Set(searchingAllowedValueIds.value);
        if (loading) next.add(valueId);
        else next.delete(valueId);
        searchingAllowedValueIds.value = next;
    }

    async function searchAllowed(value: AttributeValue, query: string) {
        if (!value.field_id) return;
        const normalizedQuery = query.trim();
        const token = (allowedRequestTokens.get(value.id) || 0) + 1;
        allowedRequestTokens.set(value.id, token);
        setAllowedSearchLoading(value.id, true);

        const result = await api.allowedValues(
            value.field_id,
            normalizedQuery,
            false,
            0,
            ALLOWED_OPTIONS_PAGE_SIZE,
        ).catch(() => null);

        if (
            result
            && allowedRequestTokens.get(value.id) === token
            && allowedSearchQueries.value[value.id] === normalizedQuery
        ) {
            allowedOptionCache.value = {
                ...allowedOptionCache.value,
                [value.id]: result.values,
            };
            allowedOptionPages.value = {
                ...allowedOptionPages.value,
                [value.id]: {
                    query: normalizedQuery,
                    total: result.total,
                    matched: result.matched,
                    hasMore: result.has_more,
                },
            };
        }

        if (allowedRequestTokens.get(value.id) === token) {
            setAllowedSearchLoading(value.id, false);
            await nextTick();
            checkAllowedMenus(value.id);
        }
    }

    async function loadMoreAllowed(value: AttributeValue) {
        if (!value.field_id || searchingAllowedValueIds.value.has(value.id)) return;
        const page = allowedOptionPages.value[value.id];
        if (!page?.hasMore || page.query !== (allowedSearchQueries.value[value.id] || "")) return;

        const token = (allowedRequestTokens.get(value.id) || 0) + 1;
        allowedRequestTokens.set(value.id, token);
        setAllowedSearchLoading(value.id, true);

        const loaded = allowedOptionCache.value[value.id] || [];
        const result = await api.allowedValues(
            value.field_id,
            page.query,
            false,
            loaded.length,
            ALLOWED_OPTIONS_PAGE_SIZE,
        ).catch(() => null);

        if (
            result
            && allowedRequestTokens.get(value.id) === token
            && allowedSearchQueries.value[value.id] === page.query
        ) {
            const merged = [...loaded];
            const known = new Set(merged.map((item) => item.id));
            for (const item of result.values) {
                if (!known.has(item.id)) merged.push(item);
            }
            allowedOptionCache.value = {
                ...allowedOptionCache.value,
                [value.id]: merged,
            };
            allowedOptionPages.value = {
                ...allowedOptionPages.value,
                [value.id]: {
                    query: page.query,
                    total: result.total,
                    matched: result.matched,
                    hasMore: result.has_more,
                },
            };
        }

        if (allowedRequestTokens.get(value.id) === token) {
            setAllowedSearchLoading(value.id, false);
            await nextTick();
            checkAllowedMenus(value.id);
        }
    }

    function queueAllowedSearch(value: AttributeValue, query: string) {
        const normalizedQuery = query.trim();
        allowedSearchQueries.value = {
            ...allowedSearchQueries.value,
            [value.id]: normalizedQuery,
        };

        const previous = allowedSearchTimers.get(value.id);
        if (previous) clearTimeout(previous);

        allowedSearchTimers.set(value.id, setTimeout(() => {
            allowedSearchTimers.delete(value.id);
            void searchAllowed(value, normalizedQuery);
        }, 250));
    }

    async function ensureAllowedOptions(value: AttributeValue, open: boolean) {
        if (!open || !value.field_id || searchingAllowedValueIds.value.has(value.id)) return;
        const page = allowedOptionPages.value[value.id];
        if (page?.query === "" && allowedOptionCache.value[value.id]) return;

        allowedSearchQueries.value = {
            ...allowedSearchQueries.value,
            [value.id]: "",
        };
        await searchAllowed(value, "");
    }

    function clearAllowedScrollBinding(key: string) {
        allowedScrollBindings.get(key)?.cleanup();
        allowedScrollBindings.delete(key);
    }

    function setAllowedSelectRef(key: string, instance: unknown) {
        if (!instance) {
            clearAllowedScrollBinding(key);
            allowedSelectRefs.delete(key);
            return;
        }
        allowedSelectRefs.set(key, instance as AllowedSelectInstance);
    }

    function allowedSelectRef(key: string) {
        let callback = allowedSelectRefCallbacks.get(key);
        if (!callback) {
            callback = (instance: unknown) => setAllowedSelectRef(key, instance);
            allowedSelectRefCallbacks.set(key, callback);
        }
        return callback;
    }

    function allowedViewport(instance: AllowedSelectInstance | undefined): HTMLElement | null {
        const exposed = instance?.viewportRef;
        if (exposed instanceof HTMLElement) return exposed;
        return exposed?.value instanceof HTMLElement ? exposed.value : null;
    }

    function checkAllowedMenus(valueId: number) {
        for (const binding of allowedScrollBindings.values()) {
            if (binding.valueId === valueId) binding.check();
        }
    }

    async function handleAllowedMenuOpen(
        value: AttributeValue,
        key: string,
        open: boolean,
    ) {
        clearAllowedScrollBinding(key);
        if (!open) return;

        await ensureAllowedOptions(value, true);
        await nextTick();

        const viewport = allowedViewport(allowedSelectRefs.get(key));
        if (!viewport) return;

        const check = () => {
            if (viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 48) {
                void loadMoreAllowed(value);
            }
        };

        viewport.addEventListener("scroll", check, { passive: true });
        allowedScrollBindings.set(key, {
            valueId: value.id,
            check,
            cleanup: () => viewport.removeEventListener("scroll", check),
        });
        check();
    }

    function resetAllowedOptionState() {
        for (const binding of allowedScrollBindings.values()) binding.cleanup();
        allowedScrollBindings.clear();
        allowedSelectRefs.clear();
        allowedSelectRefCallbacks.clear();
        allowedOptionCache.value = {};
        allowedOptionPages.value = {};
        allowedSearchQueries.value = {};
        searchingAllowedValueIds.value = new Set();
        allowedRequestTokens.clear();
        for (const timer of allowedSearchTimers.values()) clearTimeout(timer);
        allowedSearchTimers.clear();
    }

    onBeforeUnmount(resetAllowedOptionState);

    return {
        allowedOptionCache,
        allowedSearchQueries,
        searchingAllowedValueIds,
        allowedOptionPages,
        optionsFor,
        searchAllowed,
        loadMoreAllowed,
        queueAllowedSearch,
        ensureAllowedOptions,
        allowedSelectRef,
        handleAllowedMenuOpen,
        resetAllowedOptionState,
    };
}

export type AttributeAllowedValuesContext = ReturnType<typeof useAttributeAllowedValues>;
