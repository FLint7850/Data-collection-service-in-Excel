import { attributeAssistantService as api } from "~/services/attribute-assistant.service";
import type {
    AttributeProcessingMode,
    AttributeWorkspace,
    ChatGptLogin,
    ChatGptStatus,
} from "~/types/attribute-assistant";
import { errorMessage } from "~/utils/format";

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
    const busy = ref("");
    const error = ref("");
    const tab = ref<AttributeAssistantTab>("start");
    const inputMode = ref<"csv" | "urls">("csv");
    const workspace = ref<AttributeWorkspace>({
        templates: [],
        donors: [],
        batches: [],
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
        busy.value = key;
        error.value = "";
        try {
            return await task();
        } catch (caught) {
            error.value = errorMessage(caught);
            return null;
        } finally {
            busy.value = "";
        }
    }

    async function confirmAction(options: Record<string, unknown>) {
        return Boolean(await appDialog.value?.confirm(options));
    }

    async function promptValue(options: Record<string, unknown>) {
        return (await appDialog.value?.prompt(options)) ?? null;
    }

    async function loadWorkspace() {
        const data = await run("load", () => api.workspace());
        if (!data) return;
        workspace.value = data;
        selectedTemplateId.value ||= data.templates[0]?.id || null;
    }

    async function loadChatGpt() {
        chatGpt.value = await api.chatGptStatus();
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
        authPoll = setInterval(() => void loadChatGpt(), 3000);
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
    }

    return {
        loading,
        busy,
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
