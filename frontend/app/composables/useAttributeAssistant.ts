import { attributeAssistantService as api } from "~/services/attribute-assistant.service";
import type {
    AttributeProcessingMode,
    AttributeWorkspace,
    ChatGptLogin,
    ChatGptStatus,
} from "~/types/attribute-assistant";
import { errorMessage } from "~/utils/format";
import { ATTRIBUTE_ASSISTANT_UI } from "~/config/attribute-assistant";
import {
    createLatestRequestCoordinator,
    isAbortError,
} from "~/utils/latest-request";

export type AttributeAssistantTab = "start" | "templates" | "review";
export type AttributeRouteWriteMode = "push" | "replace";

type AppDialogInstance = {
    confirm: (options: Record<string, unknown>) => Promise<boolean>;
    prompt: (options: Record<string, unknown>) => Promise<string | null>;
};

type RouteWriter = (mode?: AttributeRouteWriteMode) => Promise<void>;

export function useAttributeAssistant() {
    const toast = useToast();

    const loading = ref(true);
    const activeOperations = ref<Record<string, number>>({});
    const busy = computed(() => Object.keys(activeOperations.value)[0] || "");
    const hasBusy = computed(() => Object.keys(activeOperations.value).length > 0);
    const error = ref("");
    const tab = ref<AttributeAssistantTab>("start");
    const inputMode = ref<"csv" | "urls">("csv");
    const workspace = ref<AttributeWorkspace>({
        templates: [],
        donors: [],
        batches: [],
        settings: null,
        dashboard: {
            active_templates: 0,
            batches: 0,
            products: 0,
            ready: 0,
            conflicts: 0,
            missing: 0,
        },
    });

    const selectedTemplateId = ref<number | null>(null);
    const productFile = ref<File | null>(null);
    const urlsText = ref("");
    const processingMode = ref<AttributeProcessingMode>("suggest");
    const chatGpt = ref<ChatGptStatus | null>(null);
    const deviceLogin = ref<ChatGptLogin | null>(null);
    const appDialog = ref<AppDialogInstance | null>(null);

    let authPoll: ReturnType<typeof setInterval> | null = null;
    let routeWriter: RouteWriter | null = null;
    const requests = createLatestRequestCoordinator();

    const templates = computed(() => workspace.value.templates);
    const donors = computed(() => workspace.value.donors);

    const templateSelectItems = computed(() => [
        { label: "Определить автоматически", value: null as number | null },
        ...templates.value.map((item) => ({
            label: `${item.category} · ${item.name}`,
            value: item.id,
        })),
    ]);

    const productTemplateItems = computed(() => templates.value.map((item) => ({
        label: `${item.category} · ${item.name}`,
        value: item.id,
    })));

    function notify(title: string) {
        toast.add({ title, color: "success" });
    }

    async function run<T>(key: string, task: () => Promise<T>): Promise<T | null> {
        activeOperations.value = {
            ...activeOperations.value,
            [key]: (activeOperations.value[key] || 0) + 1,
        };
        error.value = "";
        try {
            return await task();
        } catch (caught) {
            if (!isAbortError(caught)) error.value = errorMessage(caught);
            return null;
        } finally {
            const next = { ...activeOperations.value };
            const remaining = (next[key] || 1) - 1;
            if (remaining > 0) next[key] = remaining;
            else delete next[key];
            activeOperations.value = next;
        }
    }

    function isBusy(key: string) {
        return Boolean(activeOperations.value[key]);
    }

    async function confirmAction(options: Record<string, unknown>) {
        return Boolean(await appDialog.value?.confirm(options));
    }

    async function promptValue(options: Record<string, unknown>) {
        return (await appDialog.value?.prompt(options)) ?? null;
    }

    async function loadWorkspace() {
        const signal = requests.start("workspace");
        const data = await run("load", () => api.workspace(signal));
        requests.finish("workspace", signal);
        if (!data) return;
        workspace.value = data;
        selectedTemplateId.value ||= data.templates[0]?.id || null;
    }

    async function loadChatGpt() {
        const signal = requests.start("chatgpt-status");
        try {
            chatGpt.value = await api.chatGptStatus(signal);
        } catch (caught) {
            if (!isAbortError(caught)) error.value = errorMessage(caught);
            return;
        } finally {
            requests.finish("chatgpt-status", signal);
        }
        if (chatGpt.value.authenticated && authPoll) {
            clearInterval(authPoll);
            authPoll = null;
            deviceLogin.value = null;
        }
    }

    async function loginChatGpt() {
        const login = await run("chatgpt-login", () => api.chatGptLogin());
        if (!login) return;

        deviceLogin.value = login;
        window.open(login.verification_url, "_blank", "noopener,noreferrer");
        await navigator.clipboard?.writeText(login.user_code).catch(() => undefined);

        if (authPoll) clearInterval(authPoll);
        authPoll = setInterval(() => void loadChatGpt(), ATTRIBUTE_ASSISTANT_UI.authPollMs);
    }

    async function logoutChatGpt() {
        if (await run("chatgpt-logout", () => api.chatGptLogout())) {
            await loadChatGpt();
        }
    }

    function setRouteWriter(writer: RouteWriter | null) {
        routeWriter = writer;
    }

    async function writeRoute(mode: AttributeRouteWriteMode = "replace") {
        if (routeWriter) await routeWriter(mode);
    }

    function dispose() {
        if (authPoll) clearInterval(authPoll);
        authPoll = null;
        routeWriter = null;
        requests.dispose();
    }

    return {
        loading,
        busy,
        hasBusy,
        isBusy,
        error,
        tab,
        inputMode,
        workspace,
        templates,
        donors,
        selectedTemplateId,
        productFile,
        urlsText,
        processingMode,
        chatGpt,
        deviceLogin,
        appDialog,
        templateSelectItems,
        productTemplateItems,
        notify,
        run,
        confirmAction,
        promptValue,
        loadWorkspace,
        loadChatGpt,
        loginChatGpt,
        logoutChatGpt,
        setRouteWriter,
        writeRoute,
        dispose,
    };
}

export type AttributeAssistantContext = ReturnType<typeof useAttributeAssistant>;
