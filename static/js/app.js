const projectTabs = document.querySelector("#projectTabs");
const addProjectButton = document.querySelector("#addProjectButton");
const projectsTabButton = document.querySelector("#projectsTabButton");
const newItemsTabButton = document.querySelector("#newItemsTabButton");
const importTabButton = document.querySelector("#importTabButton");
const settingsTabButton = document.querySelector("#settingsTabButton");
const logsTabButton = document.querySelector("#logsTabButton");
const projectView = document.querySelector("#projectView");
const newItemsView = document.querySelector("#newItemsView");
const fileImportView = document.querySelector("#fileImportView");
const settingsView = document.querySelector("#settingsView");
const logsView = document.querySelector("#logsView");

const statusText = document.querySelector("#statusText");
const statusDot = document.querySelector("#statusDot");
const progressFill = document.querySelector("#progressFill");
const percentText = document.querySelector("#percentText");
const currentUrl = document.querySelector("#currentUrl");
const processedCount = document.querySelector("#processedCount");
const foundCount = document.querySelector("#foundCount");
const skippedCount = document.querySelector("#skippedCount");
const elapsedTime = document.querySelector("#elapsedTime");
const etaTime = document.querySelector("#etaTime");
const errorText = document.querySelector("#errorText");
const fileName = document.querySelector("#fileName");
const downloadButton = document.querySelector("#downloadButton");
const startButton = document.querySelector("#startButton");
const softPauseButton = document.querySelector("#softPauseButton");
const restartButton = document.querySelector("#restartButton");
const stopButton = document.querySelector("#stopButton");
const pauseButton = document.querySelector("#pauseButton");
const projectName = document.querySelector("#projectName");
const startUrls = document.querySelector("#startUrls");
const threadCount = document.querySelector("#threadCount");
const connectionMethod = document.querySelector("#connectionMethod");
const autoConnectionFallback = document.querySelector("#autoConnectionFallback");
const persistProfile = document.querySelector("#persistProfile");
const exclusionForm = document.querySelector("#exclusionForm");
const exclusionInput = document.querySelector("#exclusionInput");
const exclusionList = document.querySelector("#exclusionList");
const productUrlFilterForm = document.querySelector("#productUrlFilterForm");
const productUrlFilterInput = document.querySelector("#productUrlFilterInput");
const productUrlFilterList = document.querySelector("#productUrlFilterList");
const productUrlExclusionForm = document.querySelector("#productUrlExclusionForm");
const productUrlExclusionInput = document.querySelector("#productUrlExclusionInput");
const productUrlExclusionList = document.querySelector("#productUrlExclusionList");
const productCardSelector = document.querySelector("#productCardSelector");
const productUrlSelector = document.querySelector("#productUrlSelector");
const modelSelector = document.querySelector("#modelSelector");
const priceSelector = document.querySelector("#priceSelector");
const modelStartMarker = document.querySelector("#modelStartMarker");
const modelEndMarker = document.querySelector("#modelEndMarker");
const modelReplaceRules = document.querySelector("#modelReplaceRules");
const fileImportInput = document.querySelector("#fileImportInput");
const fileImportExclusions = document.querySelector("#fileImportExclusions");
const fileImportExclusionsDetails = document.querySelector(".file-import-exclusions");
const fileImportRulesDetails = document.querySelector(".file-import-rules");
const fileImportModelField = document.querySelector("#fileImportModelField");
const fileImportModelReplaceRules = document.querySelector("#fileImportModelReplaceRules");
const saveFileImportButton = document.querySelector("#saveFileImportButton");
const fileImportSaveNotice = document.querySelector("#fileImportSaveNotice");
const fileImportSelected = document.querySelector("#fileImportSelected");
const fileImportName = document.querySelector("#fileImportName");
const fileImportSize = document.querySelector("#fileImportSize");
const clearFileImportButton = document.querySelector("#clearFileImportButton");
const fileImportProgress = document.querySelector("#fileImportProgress");
const fileImportProgressFill = document.querySelector("#fileImportProgressFill");
const fileImportProgressText = document.querySelector("#fileImportProgressText");
const fileImportNotice = document.querySelector("#fileImportNotice");
const fileImportActions = document.querySelector("#fileImportActions");
const compareFileImportButton = document.querySelector("#compareFileImportButton");
const downloadFileImportCsvButton = document.querySelector("#downloadFileImportCsvButton");

function enableDetailsAnimation(details) {
  if (!details) return;

  const summary = details.querySelector("summary");
  const content = details.querySelector(".settings-details__content");
  if (!summary || !content) return;

  let animation = null;
  const duration = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 220;

  summary.addEventListener("click", (event) => {
    event.preventDefault();

    if (animation) {
      animation.commitStyles?.();
      animation.cancel();
    }

    const startHeight = content.getBoundingClientRect().height;
    if (details.open) {
      content.style.height = `${startHeight}px`;
      animation = content.animate(
        [{ height: `${startHeight}px`, opacity: 1 }, { height: "0px", opacity: 0 }],
        { duration, easing: "ease-in-out" },
      );
      animation.onfinish = () => {
        details.open = false;
        content.style.height = "";
        content.style.opacity = "";
        animation = null;
      };
      return;
    }

    details.open = true;
    const endHeight = content.getBoundingClientRect().height;
    content.style.height = "0px";
    animation = content.animate(
      [{ height: "0px", opacity: 0 }, { height: `${endHeight}px`, opacity: 1 }],
      { duration, easing: "ease-in-out" },
    );
    animation.onfinish = () => {
      content.style.height = "";
      content.style.opacity = "";
      animation = null;
    };
  });
}

enableDetailsAnimation(fileImportExclusionsDetails);
enableDetailsAnimation(fileImportRulesDetails);

function animateNewsGroup(list, collapse) {
  if (!list) return;

  list._toggleAnimation?.commitStyles?.();
  list._toggleAnimation?.cancel();
  const duration = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 220;

  if (collapse) {
    const height = list.getBoundingClientRect().height;
    list.style.height = `${height}px`;
    list._toggleAnimation = list.animate(
      [
        { height: `${height}px`, opacity: 1, transform: "translateY(0)" },
        { height: "0px", opacity: 0, transform: "translateY(-4px)" },
      ],
      { duration, easing: "ease-in-out" },
    );
    list._toggleAnimation.onfinish = () => {
      list.classList.add("news-brand-grid--collapsed");
      list.style.height = "";
      list.style.opacity = "";
      list.style.transform = "";
      list._toggleAnimation = null;
    };
    return;
  }

  list.classList.remove("news-brand-grid--collapsed");
  const height = list.getBoundingClientRect().height;
  list.style.height = "0px";
  list._toggleAnimation = list.animate(
    [
      { height: "0px", opacity: 0, transform: "translateY(-4px)" },
      { height: `${height}px`, opacity: 1, transform: "translateY(0)" },
    ],
    { duration, easing: "ease-in-out" },
  );
  list._toggleAnimation.onfinish = () => {
    list.style.height = "";
    list.style.opacity = "";
    list.style.transform = "";
    list._toggleAnimation = null;
  };
}

const logsList = document.querySelector("#logsList");
const clearLogsButton = document.querySelector("#clearLogsButton");
const refreshLogsButton = document.querySelector("#refreshLogsButton");
const autoCleanup = document.querySelector("#autoCleanup");
const newsGroups = document.querySelector("#newsGroups");
const ownSitesList = document.querySelector("#ownSitesList");
const addOwnSiteButton = document.querySelector("#addOwnSiteButton");
const smtpHost = document.querySelector("#smtpHost");
const smtpPort = document.querySelector("#smtpPort");
const smtpSecurity = document.querySelector("#smtpSecurity");
const smtpUsername = document.querySelector("#smtpUsername");
const smtpPassword = document.querySelector("#smtpPassword");
const toggleSmtpPasswordButton = document.querySelector("#toggleSmtpPasswordButton");
const smtpRecipients = document.querySelector("#smtpRecipients");
const saveNewsSettingsButton = document.querySelector("#saveNewsSettingsButton");
const testNewsEmailButton = document.querySelector("#testNewsEmailButton");
const newsSettingsNotice = document.querySelector("#newsSettingsNotice");
const newsFeedsStorage = document.querySelector("#newsFeedsStorage");
const newsMonitorModal = document.querySelector("#newsMonitorModal");
const newsModalTitle = document.querySelector("#newsModalTitle");
const newsModalSubtitle = document.querySelector("#newsModalSubtitle");
const newsModalTitleActions = document.querySelector("#newsModalTitleActions");
const newsModalContent = document.querySelector("#newsModalContent");
const closeNewsModalButton = document.querySelector("#closeNewsModalButton");
const deleteProjectModal = document.querySelector("#deleteProjectModal");
const deleteProjectText = document.querySelector("#deleteProjectText");
const confirmDeleteProjectButton = document.querySelector("#confirmDeleteProjectButton");
const cancelDeleteProjectButton = document.querySelector("#cancelDeleteProjectButton");
const cancelDeleteProjectIconButton = document.querySelector("#cancelDeleteProjectIconButton");
const deleteNewsMonitorModal = document.querySelector("#deleteNewsMonitorModal");
const deleteNewsMonitorText = document.querySelector("#deleteNewsMonitorText");
const confirmDeleteNewsMonitorButton = document.querySelector("#confirmDeleteNewsMonitorButton");
const cancelDeleteNewsMonitorButton = document.querySelector("#cancelDeleteNewsMonitorButton");
const cancelDeleteNewsMonitorIconButton = document.querySelector("#cancelDeleteNewsMonitorIconButton");
const addFeedModal = document.querySelector("#addFeedModal");
const newFeedName = document.querySelector("#newFeedName");
const newFeedUrl = document.querySelector("#newFeedUrl");
const newFeedGenerateUrl = document.querySelector("#newFeedGenerateUrl");
const confirmAddFeedButton = document.querySelector("#confirmAddFeedButton");
const cancelAddFeedButton = document.querySelector("#cancelAddFeedButton");
const cancelAddFeedIconButton = document.querySelector("#cancelAddFeedIconButton");

let projects = [];
let newsData = null;
let fileImportData = null;
let fileImportLoaded = false;
let fileImportUploading = false;
const activeViewStorageKey = "excelServiceActiveView";
const allowedActiveViews = new Set(["projects", "news", "import", "settings", "logs"]);
const appConfig = window.__APP_CONFIG__ || {};
let activeProjectId = appConfig.activeProjectId || idFromEditPath("projects") || null;
let pendingNewsMonitorId = appConfig.activeNewsId || idFromEditPath("news") || "";

function viewFromPath(pathname = window.location.pathname) {
  if (pathname.startsWith("/news")) return "news";
  if (pathname.startsWith("/file-import")) return "import";
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/logs")) return "logs";
  return "projects";
}

function idFromEditPath(prefix, pathname = window.location.pathname) {
  const marker = `/${prefix}/edit/`;
  if (!pathname.startsWith(marker)) return "";
  return decodeURIComponent(pathname.slice(marker.length).split("/")[0] || "");
}

function readStoredActiveView() {
  const configured = appConfig.activeView;
  if (allowedActiveViews.has(configured)) return configured;
  const routed = viewFromPath();
  if (allowedActiveViews.has(routed)) return routed;
  try {
    const storedView = window.localStorage.getItem(activeViewStorageKey);
    if (storedView === "project") return "projects";
    return allowedActiveViews.has(storedView) ? storedView : "projects";
  } catch {
    return "projects";
  }
}

function routeForView(view, options = {}) {
  if (view === "projects") {
    const projectId = options.projectId || activeProjectId || "";
    return projectId ? `/projects/edit/${encodeURIComponent(projectId)}` : "/projects";
  }
  if (view === "news") {
    const monitorId = options.newsId || "";
    return monitorId ? `/news/edit/${encodeURIComponent(monitorId)}` : "/news";
  }
  if (view === "import") return "/file-import";
  if (view === "settings") return "/settings";
  if (view === "logs") return "/logs";
  return "/projects";
}

function pushAppRoute(view, options = {}, replace = false) {
  const nextPath = routeForView(view, options);
  if (window.location.pathname === nextPath) return;
  const method = replace ? "replaceState" : "pushState";
  window.history[method]({ view, ...options }, "", nextPath);
}

function setActiveView(view, options = {}) {
  activeView = allowedActiveViews.has(view) ? view : "projects";
  try {
    window.localStorage.setItem(activeViewStorageKey, activeView);
  } catch {
  }
  if (options.updateRoute !== false) {
    pushAppRoute(activeView, options, Boolean(options.replace));
  }
}

let activeView = readStoredActiveView();
let isHydratingForm = false;
let isHydratingNews = false;
let saveTimer = null;
let newsSaveTimer = null;
new Map();
const selectedNewsSites = new Map();
let activeNewsBrandKey = null;
let activeNewsSelectorsOpen = false;
let activeNewsReplaceRulesOpen = false;
let activeNewsBrandNameEditing = false;
let pendingDeleteProjectId = null;
let pendingDeleteNewsMonitorId = null;
let pendingDeleteNewsMonitorMode = "brand";
let pendingDeleteNewsBrandKey = null;
let pendingDeleteDonorBrandKey = null;
let tabsRenderKey = "";
const collapsedNewsGroups = new Set();
let newsMonitorsStructureKey = "";
let logsSignature = null;
let newsListRenderQueued = false;
let newsModalProgressQueued = false;
let connectionMethods = [];
let progressEvents = null;
let progressIncludesNews = null;
let newsLoadPromise = null;
const stableProjectStates = new Map();
const stableNewsMonitorStates = new Map();
const stableNewsBrandStates = new Map();

const statusLabels = {
  idle: "ожидание",
  running: "выполняется",
  paused: "пауза",
  completed: "завершено",
  error: "ошибка",
  stopping: "останавливается",
  pausing: "приостанавливается",
  partial: "приостановлено",
};

function activeProject() {
  return projects.find((project) => project.id === activeProjectId) || projects[0] || null;
}

function formatDuration(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "—";
  }
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return [hours, minutes, secs].map((part) => String(part).padStart(2, "0")).join(":");
}

function parseDateTimeMs(value) {
  if (!value) return 0;
  const normalized = String(value).replace(/\.\d+/, "");
  const timestamp = Date.parse(normalized);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function stampNewsStates(data) {
  const receivedAt = Date.now();
  (data?.monitors || []).forEach((monitor) => {
    if (monitor?.state) monitor.state._receivedAt = receivedAt;
    if (monitor?.brand_state) monitor.brand_state._receivedAt = receivedAt;
  });
  return data;
}

function isScanningStatus(status) {
  return ["running", "queued", "pausing", "stopping"].includes(status);
}

function sameProgressRun(current, previous) {
  const currentStarted = String(current?.started_at || "");
  const previousStarted = String(previous?.started_at || "");
  return !currentStarted || !previousStarted || currentStarted === previousStarted;
}

function hasPositiveProgressValue(state, fields) {
  return fields.some((field) => Number(state?.[field] || 0) > 0);
}

function isEmptyProgressSnapshot(state, fields) {
  return isScanningStatus(state?.status) && !hasPositiveProgressValue(state, fields) && !String(state?.currenturl || "").trim();
}

function mergeStableProgressState(state, previous, fields) {
  if (!previous || !sameProgressRun(state, previous) || !isScanningStatus(state?.status)) {
    return state;
  }
  const merged = { ...state };
  fields.forEach((field) => {
    if (Number(merged[field] || 0) === 0 && Number(previous[field] || 0) > 0) {
      merged[field] = previous[field];
    }
  });
  if (!isEmptyProgressSnapshot(state, fields)) {
    return merged;
  }
  [
    "percent",
    "currenturl",
    "active_urls",
    "missing_by_feed",
    "last_event",
    "last_warning",
    "elapsed_seconds",
    "stall_seconds",
  ].forEach((field) => {
    const value = merged[field];
    const isEmptyArray = Array.isArray(value) && value.length === 0;
    if ((value === "" || value === null || value === undefined || isEmptyArray || Number(value || 0) === 0) && previous[field]) {
      merged[field] = previous[field];
    }
  });
  return merged;
}

function rememberStableProgressState(cache, key, state, fields) {
  if (!key || !state) return state || {};
  if (!isScanningStatus(state.status)) {
    cache.delete(key);
    return state;
  }
  const previous = cache.get(key);
  const merged = mergeStableProgressState(state, previous, fields);
  if (!isEmptyProgressSnapshot(merged, fields) || hasPositiveProgressValue(merged, fields)) {
    cache.set(key, { ...merged });
  }
  return merged;
}

function mergeProjectPayloadItem(project) {
  const previous = projects.find((item) => item.id === project.id) || null;
  const hasDetails = Object.prototype.hasOwnProperty.call(project, "start_urls");
  return {
    ...(previous || {}),
    ...project,
    __detail_loaded: hasDetails || Boolean(previous?.__detail_loaded),
  };
}

function applyProjectPayload(items) {
  const projectFields = ["totalprocessed", "found_products", "skipped"];
  projects = (items || []).map((item) => {
    const project = mergeProjectPayloadItem(item);
    return {
      ...project,
      state: rememberStableProgressState(
        stableProjectStates,
        project.id,
        project.state || {},
        projectFields
      ),
    };
  });
  return projects;
}

function mergeNewsMonitorPayloadItem(monitor) {
  const previous = (newsData?.monitors || []).find((item) => item.id === monitor.id) || null;
  const hasDetails = Object.prototype.hasOwnProperty.call(monitor, "extraction_rules")
    || Object.prototype.hasOwnProperty.call(monitor, "selector_settings")
    || Object.prototype.hasOwnProperty.call(monitor, "exclusions");
  return {
    ...(previous || {}),
    ...monitor,
    __detail_loaded: hasDetails || Boolean(previous?.__detail_loaded),
  };
}

function applyNewsPayload(data) {
  setConnectionMethods(data?.connection_methods);
  const stamped = stampNewsStates(data || {});
  const newsFields = [
    "processed",
    "found_products",
    "candidate_products",
    "compared_products",
    "in_memory_products",
    "queue_size",
    "active_tasks",
    "failed_pages",
    "availability_skipped",
  ];
  const mergedMonitors = (stamped?.monitors || []).map((item) => {
    const monitor = mergeNewsMonitorPayloadItem(item);
    monitor.state = rememberStableProgressState(
      stableNewsMonitorStates,
      monitor.id,
      monitor.state || {},
      newsFields
    );
    monitor.brand_state = rememberStableProgressState(
      stableNewsBrandStates,
      monitor.brand_id || `${monitor.group || ""}::${monitor.brand || ""}`,
      monitor.brand_state || {},
      newsFields
    );
    return monitor;
  });
  newsData = {
    ...(newsData || {}),
    ...(stamped || {}),
    monitors: mergedMonitors,
  };
  return newsData;
}

function localElapsedSeconds(state) {
  const base = Number(state?.elapsed_seconds || 0);
  if (!isNewsScanningStatus(state?.status)) return base;
  const startedAt = parseDateTimeMs(state?.started_at);
  if (startedAt) {
    return Math.max(base, Math.floor((Date.now() - startedAt) / 1000));
  }
  const receivedAt = Number(state?._receivedAt || 0);
  if (!receivedAt) return base;
  return base + Math.floor((Date.now() - receivedAt) / 1000);
}
function setTextIfChanged(node, value) {
  if (!node) return;
  const next = String(value ?? "");
  if (node.textContent !== next) node.textContent = next;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Ошибка запроса");
  }
  return data;
}

function setControls(status) {
  const isRunning = status === "running";
  const isPaused = status === "paused";
  const isPartial = status === "partial";
  const canResume = isPaused || isPartial;

  startButton.disabled = isRunning || canResume;
  softPauseButton.disabled = !isRunning && !isPaused;
  pauseButton.disabled = !isRunning && !isPaused && !isPartial;
  restartButton.disabled = false;
  stopButton.disabled = !isRunning && !isPaused && !isPartial;

  softPauseButton.textContent = isPaused ? "Продолжить" : "Пауза";
  pauseButton.textContent = isPartial ? "Продолжить" : "Приостановить с результатом";

  projectName.disabled = isRunning;
  startUrls.disabled = isRunning;
  threadCount.disabled = isRunning;
  connectionMethod.disabled = isRunning;
  autoConnectionFallback.disabled = isRunning;
  persistProfile.disabled = isRunning;
  productCardSelector.disabled = isRunning;
  productUrlSelector.disabled = isRunning;
  modelSelector.disabled = isRunning;
  priceSelector.disabled = isRunning;
  modelStartMarker.disabled = isRunning;
  modelEndMarker.disabled = isRunning;
  modelReplaceRules.disabled = isRunning;
}

function renderTabs() {
  const nextRenderKey = JSON.stringify({
    activeProjectId,
    activeView,
    projects: projects.map((project) => ({
      id: project.id,
      name: project.name,
    })),
  });
  if (nextRenderKey === tabsRenderKey) {
    return;
  }
  tabsRenderKey = nextRenderKey;

  projectTabs.innerHTML = "";
  projects.forEach((project) => {
    const tab = document.createElement("div");
    tab.className = `project-tab ${project.id === activeProjectId && activeView === "projects" ? "active" : ""}`;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "project-tab-button";
    button.textContent = project.name;
    button.addEventListener("click", () => {
      activeProjectId = project.id;
      setActiveView("projects", { projectId: project.id });
      renderAll();
      loadProjectDetail(project.id).then(renderAll).catch((error) => {
        errorText.textContent = error.message;
      });
    });

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "project-tab-close";
    closeButton.textContent = "×";
    closeButton.dataset.projectId = project.id;
    closeButton.setAttribute("aria-label", `Удалить проект ${project.name}`);
    closeButton.disabled = projects.length <= 1;
    closeButton.addEventListener("click", (event) => {
      event.stopPropagation();
      openDeleteProjectModal(event.currentTarget.dataset.projectId);
    });

    tab.append(button, closeButton);
    projectTabs.append(tab);
  });
  projectsTabButton.classList.toggle("active", activeView === "projects");
  newItemsTabButton.classList.toggle("active", activeView === "news");
  importTabButton.classList.toggle("active", activeView === "import");
  settingsTabButton.classList.toggle("active", activeView === "settings");
  logsTabButton.classList.toggle("active", activeView === "logs");
}

function openDeleteProjectModal(projectId) {
  const project = projects.find((item) => item.id === projectId);
  if (!project) return;
  pendingDeleteProjectId = projectId;
  deleteProjectText.textContent = `Проект "${project.name}" будет удален. Это действие нельзя отменить.`;
  deleteProjectModal.classList.remove("hidden");
  deleteProjectModal.setAttribute("aria-hidden", "false");
  confirmDeleteProjectButton.focus();
}

function closeDeleteProjectModal() {
  pendingDeleteProjectId = null;
  deleteProjectModal.classList.add("hidden");
  deleteProjectModal.setAttribute("aria-hidden", "true");
}

async function deletePendingProject() {
  const projectId = pendingDeleteProjectId;
  if (!projectId) return;

  const index = projects.findIndex((project) => project.id === projectId);
  await requestJson(`/api/projects/${projectId}`, { method: "DELETE" });
  projects = projects.filter((project) => project.id !== projectId);
  if (activeProjectId === projectId) {
    activeProjectId = projects[Math.max(0, index - 1)]?.id || projects[0]?.id || null;
    setActiveView("projects");
  }
  closeDeleteProjectModal();
  renderAll();
}

function openDeleteNewsMonitorModal(monitorId, mode = "brand", brandKey = null) {
  const monitor = (newsData?.monitors || []).find((item) => item.id === monitorId);
  if (!monitor) return;
  pendingDeleteNewsMonitorId = monitorId;
  pendingDeleteNewsMonitorMode = mode;
  pendingDeleteNewsBrandKey = brandKey || activeNewsBrandKey;
  const site = monitor.site_url || (monitor.start_urls || [])[0] || "";
  const isDonor = mode === "donor";
  deleteNewsMonitorModal.querySelector("#deleteNewsMonitorTitle").textContent = isDonor ? "Удалить донор" : "Удалить бренд";
  deleteNewsMonitorText.textContent = isDonor
    ? `Сайт-донор ${site || monitor.brand || ""} будет удален только из списка доноров текущего бренда "${monitor.brand || "бренд"}".`
    : `Бренд "${monitor.brand || "донор"}" и все его доноры будут удалены. Это действие нельзя отменить.`;
  deleteNewsMonitorModal.classList.remove("hidden");
  deleteNewsMonitorModal.setAttribute("aria-hidden", "false");
  confirmDeleteNewsMonitorButton.focus();
}

function closeDeleteNewsMonitorModal() {
  pendingDeleteNewsMonitorId = null;
  pendingDeleteNewsMonitorMode = "brand";
  pendingDeleteNewsBrandKey = null;
  pendingDeleteDonorBrandKey = null;
  deleteNewsMonitorModal.classList.add("hidden");
  deleteNewsMonitorModal.setAttribute("aria-hidden", "true");
}

function openDeleteSelectedDonorModal() {
  const select = newsModalContent.querySelector("[data-action='modal-select-news-site']");
  const monitorId = select?.value || "";
  const monitor = (newsData?.monitors || []).find((item) => item.id === monitorId);
  if (!monitor) {
    errorText.textContent = "Выберите сайт-донора для удаления.";
    return;
  }
  if (monitorsForBrandKey(activeNewsBrandKey).length < 2) {
    errorText.textContent = "Нельзя удалить единственного донора бренда.";
    renderNewsModal();
    return;
  }
  pendingDeleteNewsMonitorId = monitorId;
  pendingDeleteNewsMonitorMode = "donor";
  pendingDeleteNewsBrandKey = null;
  pendingDeleteDonorBrandKey = activeNewsBrandKey;
  const site = monitor.site_url || (monitor.start_urls || [])[0] || "";
  deleteNewsMonitorModal.querySelector("#deleteNewsMonitorTitle").textContent = "Удалить донор";
  deleteNewsMonitorText.textContent = `Сайт-донор ${site || monitor.brand || ""} будет удален из списка текущего бренда.`;
  deleteNewsMonitorModal.classList.remove("hidden");
  deleteNewsMonitorModal.setAttribute("aria-hidden", "false");
  confirmDeleteNewsMonitorButton.focus();
}

async function deletePendingNewsMonitor() {
  const monitorId = pendingDeleteNewsMonitorId;
  if (!monitorId) return;
  const mode = pendingDeleteNewsMonitorMode;
  const previousBrandKey = pendingDeleteDonorBrandKey || pendingDeleteNewsBrandKey || activeNewsBrandKey;
  const previousMonitors = monitorsForBrandKey(previousBrandKey);
  const removedIndex = previousMonitors.findIndex((item) => item.id === monitorId);
  const idsToDelete = mode === "brand" && pendingDeleteNewsBrandKey
    ? monitorsForBrandKey(pendingDeleteNewsBrandKey).map((item) => item.id)
    : [monitorId];
  let latestMonitors = null;
  for (const id of idsToDelete) {
    const url = mode === "brand" ? `/api/news/monitors/${id}?mode=brand` : `/api/news/monitors/${id}`;
    const data = await requestJson(url, { method: "DELETE" });
    if (Array.isArray(data.monitors)) latestMonitors = data.monitors;
  }
  if (mode === "donor") {
    newsData = applyNewsPayload(await requestJson("/api/news"));
  } else {
    newsData.monitors = latestMonitors || (newsData.monitors || []).filter((item) => !idsToDelete.includes(item.id));
  }
  if (mode === "donor" && previousBrandKey) {
    const nextMonitors = monitorsForBrandKey(previousBrandKey);
    const nextMonitor = nextMonitors[Math.max(0, removedIndex - 1)] || nextMonitors[0] || null;
    if (nextMonitor) {
      selectedNewsSites.set(previousBrandKey, nextMonitor.id);
      activeNewsBrandKey = previousBrandKey;
    } else {
      selectedNewsSites.delete(previousBrandKey);
      closeNewsModal();
    }
  }
  if (idsToDelete.includes(newsModalContent.dataset.monitorId) && mode !== "donor") {
    closeNewsModal();
  }
  closeDeleteNewsMonitorModal();
  renderFeedStorage();
  renderNewsMonitors();
  if (mode === "donor" && activeNewsBrandKey && !newsMonitorModal.classList.contains("hidden")) {
    renderNewsModal();
  }
}

function renderProjectForm(project) {
  if (!project) {
    return;
  }
  if (!project.__detail_loaded) {
    return;
  }
  isHydratingForm = true;
  projectName.value = project.name || "";
  startUrls.value = (project.start_urls || []).join("\n");
  threadCount.value = project.thread_count || project.state?.thread_count || 4;
  hydrateConnectionSelect(connectionMethod, project.connection_method);
  autoConnectionFallback.checked = project.auto_connection_fallback !== false;
  persistProfile.checked = Boolean(project.persist_profile);
  const rules = project.extraction_rules || {};
  productCardSelector.value = rules.product_card_selector || "";
  productUrlSelector.value = rules.product_url_selector || "";
  modelSelector.value = rules.model_selector || "";
  priceSelector.value = rules.price_selector || "";
  modelStartMarker.value = rules.model_start_marker || "";
  modelEndMarker.value = rules.model_end_marker || "";
  modelReplaceRules.value = rules.model_replace_rules || "";
  isHydratingForm = false;
  renderExclusions(project.exclusions || []);
  renderProductUrlFilters(project.product_url_filters || []);
  renderProductUrlExclusions(project.product_url_exclusions || []);
}

function renderState(project) {
  const state = project?.state || {};
  const percent = Number(state.percent || 0);
  const status = state.status || "idle";
  if (statusText) statusText.textContent = statusLabels[status] || status;
  if (statusDot) statusDot.className = `status-dot status-${status}`;
  if (progressFill) progressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  if (percentText) percentText.textContent = `${percent}%`;
  const nextCurrentUrl = state.currenturl || (["running", "queued"].includes(status) ? "" : "Текущий URL появится после запуска.");
  if (currentUrl && currentUrl.dataset.value !== nextCurrentUrl) {
    currentUrl.textContent = nextCurrentUrl;
    currentUrl.dataset.value = nextCurrentUrl;
  }
  if (processedCount) processedCount.textContent = state.totalprocessed || 0;
  if (foundCount) foundCount.textContent = state.found_products || 0;
  if (skippedCount) skippedCount.textContent = state.skipped || 0;
  if (elapsedTime) elapsedTime.textContent = formatDuration(state.elapsed_seconds || 0);
  if (etaTime) etaTime.textContent = state.eta_seconds === null || state.eta_seconds === undefined ? "—" : formatDuration(state.eta_seconds);
  if (errorText) errorText.textContent = state.error || "";
  if (fileName) fileName.textContent = state.filename || "";

  const ready = Boolean(state.download_ready || state.filename);
  if (downloadButton) {
    downloadButton.classList.toggle("disabled", !ready);
    downloadButton.setAttribute("aria-disabled", ready ? "false" : "true");
    downloadButton.href = ready && project ? `/api/projects/${project.id}/download` : "#";
  }
  setControls(status);
}

function renderExclusions(items) {
  exclusionList.innerHTML = "";
  items.forEach((pattern, index) => {
    const item = document.createElement("li");
    item.className = "exclusion-item";

    const text = document.createElement("span");
    text.className = "exclusion-pattern";
    text.textContent = pattern;

    const button = document.createElement("button");
    button.className = "remove-button";
    button.type = "button";
    button.setAttribute("aria-label", "Удалить исключение");
    button.textContent = "×";
    button.addEventListener("click", async () => {
      const project = activeProject();
      if (!project) return;
      const data = await requestJson(`/api/projects/${project.id}/exclusions/${index}`, { method: "DELETE" });
      project.exclusions = data.exclusions || [];
      renderExclusions(project.exclusions);
    });

    item.append(text, button);
    exclusionList.append(item);
  });
}

function renderProductUrlFilters(items) {
  productUrlFilterList.innerHTML = "";
  items.forEach((pattern, index) => {
    const item = document.createElement("li");
    item.className = "exclusion-item";

    const text = document.createElement("span");
    text.className = "exclusion-pattern";
    text.textContent = pattern;

    const button = document.createElement("button");
    button.className = "remove-button";
    button.type = "button";
    button.setAttribute("aria-label", "Удалить фильтр товарной ссылки");
    button.textContent = "×";
    button.addEventListener("click", async () => {
      const project = activeProject();
      if (!project) return;
      const data = await requestJson(`/api/projects/${project.id}/product-url-filters/${index}`, { method: "DELETE" });
      project.product_url_filters = data.product_url_filters || [];
      renderProductUrlFilters(project.product_url_filters);
    });

    item.append(text, button);
    productUrlFilterList.append(item);
  });
}

function renderProductUrlExclusions(items) {
  if (!productUrlExclusionList) return;
  productUrlExclusionList.innerHTML = "";
  items.forEach((pattern, index) => {
    const item = document.createElement("li");
    item.className = "exclusion-item";

    const text = document.createElement("span");
    text.className = "exclusion-pattern";
    text.textContent = pattern;

    const button = document.createElement("button");
    button.className = "remove-button";
    button.type = "button";
    button.setAttribute("aria-label", "Удалить исключение товарной ссылки");
    button.textContent = "×";
    button.addEventListener("click", async () => {
      const project = activeProject();
      if (!project) return;
      const data = await requestJson(`/api/projects/${project.id}/product-url-exclusions/${index}`, { method: "DELETE" });
      project.product_url_exclusions = data.product_url_exclusions || [];
      renderProductUrlExclusions(project.product_url_exclusions);
    });

    item.append(text, button);
    productUrlExclusionList.append(item);
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function defaultConnectionMethod() {
  return connectionMethods[0]?.code || "requests";
}

function setConnectionMethods(methods) {
  if (!Array.isArray(methods)) return;
  connectionMethods = methods
    .map((method, index) => ({
      id: Number(method.id ?? index),
      code: String(method.code || "").trim(),
      name: String(method.name || method.code || "").trim(),
    }))
    .filter((method) => method.code);
}

function connectionOptionsHtml(current) {
  const currentValue = current || defaultConnectionMethod();
  const options = connectionMethods.length
    ? connectionMethods
    : [{ id: 0, code: "requests", name: "Requests" }];
  return options
    .map((method) => {
      const value = escapeHtml(method.code);
      const label = escapeHtml(method.name || method.code);
      return `<option value="${value}" ${method.code === currentValue ? "selected" : ""}>${label}</option>`;
    })
    .join("");
}

function hydrateConnectionSelect(select, current) {
  if (!select) return;
  const currentValue = current || select.value || defaultConnectionMethod();
  const previousValue = select.value;
  const nextHtml = connectionOptionsHtml(currentValue);
  if (select.dataset.optionsHtml !== nextHtml) {
    select.innerHTML = nextHtml;
    select.dataset.optionsHtml = nextHtml;
  }
  select.value = connectionMethods.some((method) => method.code === currentValue)
    ? currentValue
    : defaultConnectionMethod();
  if (!select.value && previousValue) select.value = previousValue;
}

function renderNewsSettings() {
  if (!newsData) return;
  isHydratingNews = true;
  const smtp = newsData.smtp || {};
  renderOwnSites();
  smtpHost.value = smtp.host || "smtp.yandex.ru";
  smtpPort.value = smtp.port || 465;
  smtpSecurity.value = smtp.security || "ssl";
  smtpUsername.value = smtp.username || "";
  smtpPassword.value = smtp.password || "";
  smtpPassword.placeholder = smtp.password_set ? "Пароль приложения сохранен" : "Введите пароль приложения";
  smtpRecipients.value = (smtp.recipients || []).join("\n");
  isHydratingNews = false;
}

function ownSitesFromNewsData() {
  if (Array.isArray(newsData?.own_sites) && newsData.own_sites.length) {
    return newsData.own_sites.map((site, index) => ({
      name: site.name || `Фид ${index + 1}`,
      feed_url: site.feed_url || "",
      feed_generate_url: site.feed_generate_url || "",
    }));
  }
  const feedUrls = newsData?.feed_urls || (newsData?.feed_url ? [newsData.feed_url] : []);
  const generateUrls = newsData?.feed_generate_urls || (newsData?.feed_generate_url ? [newsData.feed_generate_url] : []);
  return feedUrls.map((feedUrl, index) => ({
    name: `Фид ${index + 1}`,
    feed_url: feedUrl || "",
    feed_generate_url: generateUrls[index] || generateUrls[0] || "",
  }));
}

function localFeedsHtmlForSite(site) {
  const feeds = (newsData?.feed_storage || []).filter((feed) => feed.url === site.feed_url);
  if (!feeds.length) {
    return `
      <div class="local-feeds local-feeds-in-card">
        <span class="local-feeds-title">Локальный фид ${escapeHtml(site.name || "Фид")}</span>
        <span class="local-feed-empty">Фид еще не загружался.</span>
      </div>
    `;
  }
  return `
    <div class="local-feeds local-feeds-in-card">
      <span class="local-feeds-title">Локальный фид ${escapeHtml(site.name || feeds[0]?.source_label || "Фид")}</span>
      ${feeds
        .map((feed) => {
          const filename = feed.filename || "";
          const size = formatFileSize(feed.size);
          const codes = Number(feed.codes_count || 0);
          const meta = [size, `${codes} моделей`].filter(Boolean).join(" · ");
          const source = feed.source || "feed";
          return `
            <a class="local-feed-link" href="/api/news/feeds/${encodeURIComponent(source)}/${encodeURIComponent(filename)}">
              <span>${escapeHtml(filename || "feed.xml")}</span>
              <small>${escapeHtml(meta || feed.kind || "")}</small>
            </a>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderOwnSites() {
  if (!ownSitesList || !newsData) return;
  const sites = ownSitesFromNewsData();
  if (!sites.length) {
    ownSitesList.innerHTML = `<div class="own-site-empty">Фиды не добавлены.</div>`;
    return;
  }
  ownSitesList.innerHTML = sites
    .map(
      (site, index) => `
        <div class="own-site-card" data-own-site-index="${index}">
          <div class="own-site-card-head">
            <strong>${escapeHtml(site.name || `Фид ${index + 1}`)}</strong>
            <button class="remove-button" data-action="remove-own-site" type="button" aria-label="Удалить фид">×</button>
          </div>
          <div class="news-settings-grid">
            <label class="field">
              <span>Название фида</span>
              <input data-own-site-field="name" type="text" autocomplete="off" value="${escapeHtml(site.name || `Фид ${index + 1}`)}">
            </label>
            <label class="field">
              <span>Фид товаров моего сайта</span>
              <input data-own-site-field="feed_url" type="url" autocomplete="off" value="${escapeHtml(site.feed_url)}">
            </label>
            <label class="field">
              <span>Ссылка генерации фида</span>
              <input data-own-site-field="feed_generate_url" type="url" autocomplete="off" value="${escapeHtml(site.feed_generate_url)}">
            </label>
          </div>
          <div class="news-settings-actions own-site-actions">
            <button class="button primary" data-action="save-own-site" type="button">Сохранить изменения</button>
            <span class="save-notice" data-role="own-site-notice"></span>
          </div>
          ${localFeedsHtmlForSite(site)}
        </div>
      `
    )
    .join("");
}

function updateLocalFeedBlocks() {
  if (!ownSitesList || !newsData) return;
  Array.from(ownSitesList.querySelectorAll("[data-own-site-index]")).forEach((card) => {
    const site = {
      name: card.querySelector('[data-own-site-field="name"]')?.value.trim() || "",
      feed_url: card.querySelector('[data-own-site-field="feed_url"]')?.value.trim() || "",
      feed_generate_url: card.querySelector('[data-own-site-field="feed_generate_url"]')?.value.trim() || "",
    };
    const nextHtml = localFeedsHtmlForSite(site);
    const current = card.querySelector(".local-feeds-in-card");
    if (current) {
      current.outerHTML = nextHtml;
    } else {
      card.insertAdjacentHTML("beforeend", nextHtml);
    }
  });
}

function collectOwnSites() {
  if (!ownSitesList) return [];
  return Array.from(ownSitesList.querySelectorAll("[data-own-site-index]"))
    .map((card) => ({
      name: card.querySelector('[data-own-site-field="name"]')?.value.trim() || "",
      feed_url: card.querySelector('[data-own-site-field="feed_url"]')?.value.trim() || "",
      feed_generate_url: card.querySelector('[data-own-site-field="feed_generate_url"]')?.value.trim() || "",
    }))
    .filter((site) => site.feed_url || site.feed_generate_url);
}

function scheduleTypeOptionsHtml(current) {
  const options = [
    ["daily", "Каждый день"],
    ["weekly", "Раз в неделю"],
    ["once", "Разовый запуск"],
  ];
  return options
    .map(([value, label]) => `<option value="${value}" ${value === current ? "selected" : ""}>${label}</option>`)
    .join("");
}

function weekdayOptionsHtml(current) {
  const names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  return names
    .map((label, index) => `<option value="${index}" ${Number(current) === index ? "selected" : ""}>${label}</option>`)
    .join("");
}

function formatDateTimeLocal(value) {
  if (!value) return "";
  return String(value).slice(0, 16);
}

function createdTimestamp(value) {
  const time = Date.parse(String(value || ""));
  return Number.isFinite(time) ? time : 0;
}

function newsStatusClass(status) {
  if (status === "running" || status === "queued") return "status-running";
  if (status === "completed") return "status-completed";
  if (status === "stopping" || status === "pausing" || status === "partial") return "status-paused";
  if (status === "error") return "status-error";
  return "status-idle";
}

function isNewsScanningStatus(status) {
  return isScanningStatus(status);
}

function newsStatusText(status) {
  if (status === "running" || status === "queued") return "в работе";
  if (status === "completed") return "завершено";
  if (status === "stopping") return "останавливается";
  if (status === "pausing") return "приостанавливается";
  if (status === "partial") return "приостановлено";
  if (status === "error") return "ошибка";
  return "ожидание";
}


function newsStatusActionsHtml(status) {
  if (status === "running" || status === "queued") {
    return `
      <button class="status-action-button status-action-button--pause" data-action="pause-news" type="button" title="Приостановить" aria-label="Приостановить">⏸</button>
      <button class="status-action-button status-action-button--stop" data-action="stop-news" type="button" title="Стоп" aria-label="Стоп">■</button>
    `;
  }

  if (status === "partial") {
    return `
      <button class="status-action-button status-action-button--resume" data-action="resume-news" type="button" title="Продолжить" aria-label="Продолжить">▶</button>
    `;
  }

  return "";
}

function newsStatusHtml(status) {
  return `
    <span class="news-status ${newsStatusClass(status)}" data-role="news-status" data-status="${escapeHtml(status || "idle")}">
      <span data-role="status-text">${escapeHtml(newsStatusText(status))}</span>
      ${newsStatusActionsHtml(status)}
    </span>
  `;
}

function aggregateMissingByFeed(states) {
  const byLabel = new Map();
  states.forEach((state) => {
    (state.missing_by_feed || []).forEach((item) => {
      const label = item.source_label || item.url || "Сайт";
      const current = byLabel.get(label) || 0;
      byLabel.set(label, current + Number(item.count || 0));
    });
  });
  return Array.from(byLabel.entries()).map(([label, count]) => ({ label, count }));
}

function missingSummaryHtml(summary, total) {
  if (!total) {
    return `<span class="missing-summary-empty">Новинок не найдено</span>`;
  }
  return `
    <span>Всего новинок: <strong>${Number(total || 0)}</strong></span>
    ${summary
      .map((item) => `<span>Нет на ${escapeHtml(item.label)}: <strong>${Number(item.count || 0)}</strong></span>`)
      .join("")}
  `;
}

function aggregateNewsStatus(states) {
  if (states.some((state) => state.status === "error")) return "error";
  if (states.some((state) => ["running", "queued"].includes(state.status))) return "running";
  if (states.some((state) => state.status === "stopping")) return "stopping";
  if (states.some((state) => state.status === "pausing")) return "pausing";
  if (states.some((state) => state.status === "partial")) return "partial";
  if (states.some((state) => state.status === "completed")) return "completed";
  return "idle";
}

function stateWithBrandState(monitor) {
  const state = { ...(monitor.state || {}) };
  const brandState = monitor.brand_state || null;
  if (brandState && (!state.status || state.status === "idle")) {
    return { ...state, ...brandState };
  }
  return state;
}

function clampPercent(value) {
  const percent = Number(value || 0);
  if (!Number.isFinite(percent)) return 0;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function getCompareProgress(state) {
  const compared = Number(state?.compared_products || 0);
  const total = Number(state?.candidate_products || state?.found_products || 0);

  if (!Number.isFinite(total) || total <= 0) return 0;

  return clampPercent((compared / total) * 100);
}

function formatFileSize(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

function setFileImportProgress(percent, notice = "") {
  const value = clampPercent(percent);
  fileImportProgressFill.style.width = `${value}%`;
  fileImportProgressText.textContent = `${value}%`;
  fileImportNotice.textContent = notice;
}

function renderFileImport() {
  const file = fileImportData?.file || null;
  if (fileImportExclusions && document.activeElement !== fileImportExclusions) {
    fileImportExclusions.value = fileImportData?.exclusions || "";
  }
  if (fileImportModelField && document.activeElement !== fileImportModelField) {
    fileImportModelField.value = fileImportData?.model_field || "";
  }
  if (fileImportModelReplaceRules && document.activeElement !== fileImportModelReplaceRules) {
    fileImportModelReplaceRules.value = fileImportData?.replace_rules || "";
  }
  fileImportName.textContent = file?.filename || "—";
  fileImportSize.textContent = file?.size ? formatFileSize(file.size) : "";
  fileImportSelected.classList.toggle("hidden", !file);
  fileImportActions.classList.toggle("hidden", !file);
  if (saveFileImportButton) saveFileImportButton.disabled = fileImportUploading;
  clearFileImportButton.disabled = fileImportUploading || !file;
  compareFileImportButton.disabled = fileImportUploading || !file;
  if (fileImportData?.result_ready) {
    downloadFileImportCsvButton.classList.remove("disabled");
    downloadFileImportCsvButton.setAttribute("aria-disabled", "false");
    downloadFileImportCsvButton.href = "/api/file-import/download";
  } else {
    downloadFileImportCsvButton.classList.add("disabled");
    downloadFileImportCsvButton.setAttribute("aria-disabled", "true");
    downloadFileImportCsvButton.href = "#";
  }
  fileImportInput.disabled = fileImportUploading;
  if (!fileImportUploading && !file) {
    fileImportProgress.classList.add("hidden");
    setFileImportProgress(0, "");
  }
}

async function loadFileImport() {
  fileImportData = await requestJson("/api/file-import");
  fileImportLoaded = true;
  renderFileImport();
}

async function saveFileImport() {
  if (!saveFileImportButton || !fileImportSaveNotice) return;
  saveFileImportButton.disabled = true;
  fileImportSaveNotice.textContent = "Сохраняю...";
  fileImportData = await requestJson("/api/file-import", {
    method: "PATCH",
    body: JSON.stringify({
      exclusions: fileImportExclusions?.value || "",
      model_field: fileImportModelField?.value || "",
      replace_rules: fileImportModelReplaceRules?.value || "",
      file: fileImportData?.file || null,
    }),
  });
  fileImportLoaded = true;
  renderFileImport();
  fileImportSaveNotice.textContent = "Сохранено";
  window.setTimeout(() => {
    if (fileImportSaveNotice.textContent === "Сохранено") {
      fileImportSaveNotice.textContent = "";
    }
  }, 1800);
}

function uploadFileImport(file) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/file-import");
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        setFileImportProgress((event.loaded / event.total) * 100, "Выгружаю файл...");
      }
    });
    xhr.addEventListener("load", () => {
      const data = JSON.parse(xhr.responseText || "{}");
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
      } else {
        reject(new Error(data.error || "Не удалось выгрузить файл"));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Не удалось выгрузить файл")));
    xhr.send(formData);
  });
}

async function deleteFileImport() {
  fileImportData = await requestJson("/api/file-import", { method: "DELETE" });
  fileImportInput.value = "";
  renderFileImport();
}

async function compareFileImport() {
  compareFileImportButton.disabled = true;
  fileImportProgress.classList.remove("hidden");
  setFileImportProgress(20, "Сравниваю с фидами...");
  fileImportData = await requestJson("/api/file-import/compare", { method: "POST" });
  const summary = fileImportData?.summary || {};
  setFileImportProgress(100, `Готово. Missing: ${Number(summary.missing_rows || 0)}`);
  renderFileImport();
}

function renderFeedStorage() {
  if (!newsFeedsStorage || !newsData) return;
  if (ownSitesList) {
    updateLocalFeedBlocks();
    newsFeedsStorage.innerHTML = "";
    return;
  }
  const feeds = newsData.feed_storage || [];
  if (!feeds.length) {
    newsFeedsStorage.innerHTML = `
      <div class="local-feeds">
        <span class="local-feeds-title">Локальные фиды</span>
        <span class="local-feed-empty">Фиды еще не загружались.</span>
      </div>
    `;
    return;
  }
  const groups = feeds.reduce((acc, feed) => {
    const source = feed.source || "feed";
    if (!acc[source]) {
      acc[source] = {
        label: feed.source_label || source,
        feeds: [],
      };
    }
    acc[source].feeds.push(feed);
    return acc;
  }, {});
  newsFeedsStorage.innerHTML = `
    <div class="local-feeds">
      ${Object.entries(groups)
        .map(([source, group]) => `
          <div class="local-feed-source">
            <span class="local-feeds-title">Локальный фид ${escapeHtml(group.label)}</span>
            ${group.feeds
              .map((feed) => {
                const filename = feed.filename || "";
                const size = formatFileSize(feed.size);
                const codes = Number(feed.codes_count || 0);
                const meta = [size, `${codes} моделей`].filter(Boolean).join(" · ");
                return `
                  <a class="local-feed-link" href="/api/news/feeds/${encodeURIComponent(source)}/${encodeURIComponent(filename)}">
                    <span>${escapeHtml(filename || "feed.xml")}</span>
                    <small>${escapeHtml(meta || feed.kind || "")}</small>
                  </a>
                `;
              })
              .join("")}
          </div>
        `)
        .join("")}
    </div>
  `;
}

function sortedBrandEntries(brands) {
  return Object.entries(brands).sort((left, right) => {
    const leftCreated = Math.max(...left[1].map((monitor) => createdTimestamp(monitor.brand_created_at)));
    const rightCreated = Math.max(...right[1].map((monitor) => createdTimestamp(monitor.brand_created_at)));
    if (rightCreated !== leftCreated) return rightCreated - leftCreated;
    return String(right[0]).localeCompare(String(left[0]), "ru");
  });
}

function newsMonitorsStructureSignature() {
  const grouped = groupNewsMonitors();
  return JSON.stringify(
    ["Маржа", "Немаржа"].map((group) => [
      group,
      sortedBrandEntries(grouped[group] || {}).map(([brand, brandMonitors]) => [
        brand,
        brandMonitors.map((monitor) => ({
          id: monitor.id,
          brand_created_at: monitor.brand_created_at || "",
          created_at: monitor.created_at || "",
          site_url: monitor.site_url || "",
          start_urls: monitor.start_urls || [],
        })),
      ]),
    ])
  );
}

function newsBrandTileHtml(group, brand, brandMonitors) {
  const brandKey = `${group}::${brand}`;
  const selectedId = selectedNewsSites.get(brandKey);
  const monitor = brandMonitors.find((item) => item.id === selectedId) || brandMonitors[0];
  selectedNewsSites.set(brandKey, monitor.id);
  const states = brandMonitors.map((item) => stateWithBrandState(item));
  const status = aggregateNewsStatus(states);
  const activeState = states.find((state) => state.status === "running" || state.status === "queued") || states[0] || {};
  const percent = getCompareProgress(activeState);
  const newCount = Number(activeState.new_count || 0);
  const inMemoryProducts = Number(activeState.in_memory_products || activeState.found_products || 0);
  const queueSize = Number(activeState.queue_size || 0);
  const activeTasks = Number(activeState.active_tasks || 0);
  const stallSeconds = Number(activeState.stall_seconds || 0);
  const missingSummary = aggregateMissingByFeed([activeState]);
  const lastScan = states.map((state) => state.last_scan_at || "").filter(Boolean).sort().pop() || "—";
  return `
    <span class="news-tile-remove-wrap">
      <button class="news-tile-remove" data-action="delete-news-monitor-card" data-monitor-id="${monitor.id}" data-brand-key="${escapeHtml(brandKey)}" type="button" aria-label="Удалить">×</button>
    </span>
    <span class="brand-name">${escapeHtml(brand)}</span>
    <span class="brand-meta">${brandMonitors.length} сайт${brandMonitors.length > 1 ? "а" : ""}</span>
    <span class="brand-sites">${brandMonitors.map((item) => escapeHtml(item.site_url || (item.start_urls || [])[0] || "")).join("<br>")}</span>
    <span class="brand-row">
      ${newsStatusHtml(status)}
    </span>
    <span class="brand-missing-summary">
      ${missingSummaryHtml(missingSummary, newCount)}
    </span>
    <span class="mini-progress-track"><span class="mini-progress-fill" style="width: ${percent}%"></span></span>
    <span class="brand-counters">
      Стр: ${Number(activeState.processed || 0)} · Тов: ${Number(activeState.found_products || 0)} · Сравнено: ${Number(activeState.compared_products || 0)}
    </span>
    <span class="brand-counters brand-counters-secondary">
      В памяти: ${inMemoryProducts} · Очередь: ${queueSize} · Активно: ${activeTasks}
    </span>
    ${stallSeconds ? `<span class="brand-stage">Без прогресса: ${formatDuration(stallSeconds)}</span>` : ""}
    <span class="brand-stage">${escapeHtml(activeState.stage || "")}</span>
    ${activeState.last_warning ? `<span class="brand-warning">${escapeHtml(activeState.last_warning)}</span>` : ""}
    ${activeState.last_event && !activeState.last_warning ? `<span class="brand-stage">${escapeHtml(activeState.last_event)}</span>` : ""}
    ${activeState.error ? `<span class="brand-error">${escapeHtml(activeState.error)}</span>` : ""}
    <span class="brand-last">Последнее: ${escapeHtml(lastScan)}</span>
  `;
}

function updateNewsBrandTiles() {
  const grouped = groupNewsMonitors();
  ["Маржа", "Немаржа"].forEach((group) => {
    sortedBrandEntries(grouped[group] || {}).forEach(([brand, brandMonitors]) => {
      const brandKey = `${group}::${brand}`;
      const tile = Array.from(newsGroups.querySelectorAll("[data-action='open-news-brand']")).find((node) => node.dataset.brandKey === brandKey);
      if (!tile) return;
      const status = aggregateNewsStatus(brandMonitors.map((item) => stateWithBrandState(item)));
      if (!isNewsScanningStatus(status) && tile.dataset.newsStatus === status) {
        return;
      }
      const nextHtml = newsBrandTileHtml(group, brand, brandMonitors);
      if (tile.innerHTML.trim() !== nextHtml.trim()) {
        tile.innerHTML = nextHtml;
      }
      tile.dataset.newsStatus = status;
    });
  });
}

function renderNewsList() {
  if (!newsData || !newsGroups) return;
  const nextStructureKey = newsMonitorsStructureSignature();
  if (nextStructureKey !== newsMonitorsStructureKey || !newsGroups.children.length) {
    renderNewsMonitors();
  } else {
    updateNewsBrandTiles();
  }
}

function scheduleNewsListRender() {
  if (newsListRenderQueued) return;
  newsListRenderQueued = true;
  requestAnimationFrame(() => {
    newsListRenderQueued = false;
    renderNewsList();
  });
}

function scheduleNewsModalProgressUpdate() {
  if (newsModalProgressQueued) return;
  newsModalProgressQueued = true;
  requestAnimationFrame(() => {
    newsModalProgressQueued = false;
    updateNewsModalProgress();
  });
}

function tickNewsModalTimers() {
  if (!activeNewsBrandKey || !newsMonitorModal || newsMonitorModal.classList.contains("hidden")) return;
  const monitor = activeNewsMonitor();
  const state = monitor?.state || {};
  if (!isNewsScanningStatus(state.status)) return;
  setTextIfChanged(newsModalContent.querySelector("[data-summary='elapsed']"), formatDuration(localElapsedSeconds(state)));
}

function renderNewsMonitors() {
  if (!newsData || !newsGroups) return;
  const grouped = groupNewsMonitors();
  newsMonitorsStructureKey = newsMonitorsStructureSignature();
  newsGroups.innerHTML = "";
  ["Маржа", "Немаржа"].forEach((group) => {
    const brands = grouped[group] || {};
    const section = document.createElement("section");
    section.className = "panel news-group-panel";
    const isCollapsed = collapsedNewsGroups.has(group);
    section.innerHTML = `
      <div class="section-title-row">
        <button class="news-group-toggle" data-action="toggle-news-group" data-group="${escapeHtml(group)}" type="button" aria-expanded="${isCollapsed ? "false" : "true"}">
          <span class="news-group-toggle-icon">${isCollapsed ? "▸" : "▾"}</span>
          <span>${escapeHtml(group)}</span>
        </button>
        <button class="button secondary" data-action="add-news-monitor-group" data-group="${escapeHtml(group)}" type="button">+ Бренд</button>
      </div>
    `;
    const list = document.createElement("div");
    list.className = "news-brand-grid main-block-wrapper";
    if (isCollapsed) {
      list.classList.add("news-brand-grid--collapsed");
    }
    sortedBrandEntries(brands).forEach(([brand, brandMonitors]) => {
      const brandKey = `${group}::${brand}`;
      const tile = document.createElement("button");
      tile.className = "news-brand-tile";
      tile.type = "button";
      tile.dataset.action = "open-news-brand";
      tile.dataset.brandKey = brandKey;
      tile.innerHTML = newsBrandTileHtml(group, brand, brandMonitors);
      tile.dataset.newsStatus = aggregateNewsStatus(brandMonitors.map((item) => stateWithBrandState(item)));
      list.append(tile);
    });
    section.append(list);
    newsGroups.append(section);
  });
}

function groupNewsMonitors() {
  return (newsData?.monitors || []).reduce((acc, monitor) => {
    const group = monitor.group || "Доноры";
    const brand = monitor.brand || "Донор";
    if (!acc[group]) acc[group] = {};
    if (!acc[group][brand]) acc[group][brand] = [];
    acc[group][brand].push(monitor);
    return acc;
  }, {});
}

function monitorsForBrandKey(brandKey) {
  const [group, brand] = String(brandKey || "").split("::");
  return groupNewsMonitors()[group]?.[brand] || [];
}

function activeNewsMonitor() {
  const monitors = monitorsForBrandKey(activeNewsBrandKey);
  if (!monitors.length) return null;
  const primaryId = String(monitors[0]?.primary_donor_id || "");
  const selectedId = selectedNewsSites.get(activeNewsBrandKey);
  const monitor =
    monitors.find((item) => item.id === selectedId) ||
    monitors.find((item) => item.id === primaryId) ||
    monitors[0];
  selectedNewsSites.set(activeNewsBrandKey, monitor.id);
  return monitor;
}

async function openNewsModal(brandKey, options = {}) {
  activeNewsBrandKey = brandKey;
  const monitors = monitorsForBrandKey(brandKey);
  const primaryId = String(monitors[0]?.primary_donor_id || "");
  if (primaryId && !selectedNewsSites.has(brandKey)) {
    selectedNewsSites.set(brandKey, primaryId);
  }
  activeNewsSelectorsOpen = false;
  activeNewsReplaceRulesOpen = false;
  activeNewsBrandNameEditing = false;
  newsMonitorModal.classList.remove("hidden");
  newsMonitorModal.setAttribute("aria-hidden", "false");
  const selected = activeNewsMonitor();
  if (selected?.id) {
    pushAppRoute("news", { newsId: selected.id }, Boolean(options.replace));
    if (!selected.__detail_loaded) {
      newsModalContent.dataset.monitorId = selected.id;
      newsModalContent.innerHTML = `<div class="modal-summary-row">Загружаю настройки донора...</div>`;
      try {
        await loadNewsMonitorDetail(selected.id);
      } catch (error) {
        errorText.textContent = error.message;
      }
    }
  }
  renderNewsModal();
}

function closeNewsModal() {
  newsMonitorModal.classList.add("hidden");
  newsMonitorModal.setAttribute("aria-hidden", "true");
  activeNewsBrandKey = null;
  activeNewsSelectorsOpen = true;
  activeNewsReplaceRulesOpen = false;
  activeNewsBrandNameEditing = false;
  if (activeView === "news") pushAppRoute("news");
}

function updateNewsModalProgress() {
  const monitor = activeNewsMonitor();
  if (!monitor || newsModalContent.dataset.monitorId !== monitor.id) return;
  const state = monitor.state || {};
  const statusNode = newsModalTitleActions.querySelector("[data-role='news-status']");
  if (statusNode && statusNode.dataset.status !== (state.status || "idle")) {
    statusNode.outerHTML = newsStatusHtml(state.status);
  }
  const percent = getCompareProgress(state);
  const summaryValues = {
    lastScan: state.last_scan_at || "—",
    newCount: Number(state.new_count || 0),
    csv: state.last_csv || "—",
    stage: state.stage || "—",
    processed: Number(state.processed || 0),
    found: Number(state.found_products || 0),
    memory: Number(state.in_memory_products || state.found_products || 0),
    compared: Number(state.compared_products || 0),
    candidates: Number(state.candidate_products || state.found_products || 0),
    queue: Number(state.queue_size || 0),
    active: Number(state.active_tasks || 0),
    failed: Number(state.failed_pages || 0),
    availabilitySkipped: Number(state.availability_skipped || 0),
    stall: formatDuration(Number(state.stall_seconds || 0)),
    elapsed: formatDuration(localElapsedSeconds(state)),
    lastEvent: state.last_event || "—",
    lastWarning: state.last_warning || "",
  };
  Object.entries(summaryValues).forEach(([key, value]) => {
    const node = newsModalContent.querySelector(`[data-summary='${key}']`);
    setTextIfChanged(node, value);
  });
  const missingNode = newsModalContent.querySelector("[data-role='modal-missing-summary']");
  if (missingNode) {
    const isScanning = isNewsScanningStatus(state.status);
    const wasScanning = missingNode.dataset.wasScanning === "true";
    if (isScanning || wasScanning) {
      missingNode.innerHTML = missingSummaryHtml(
        aggregateMissingByFeed([state]),
        Number(state.new_count || 0)
      );
    }
    missingNode.dataset.wasScanning = isScanning ? "true" : "false";
  }

  const fill = newsModalContent.querySelector("[data-role='modal-progress-fill']");
  if (fill) fill.style.width = `${percent}%`;
  const percentNode = newsModalContent.querySelector("[data-role='modal-percent']");
  setTextIfChanged(percentNode, `${percent}%`);
  const currentUrlNode = newsModalContent.querySelector("[data-role='modal-current-url']");
  setTextIfChanged(currentUrlNode, state.currenturl || "");
  const activeUrlsNode = newsModalContent.querySelector("[data-role='modal-active-urls']");
  if (activeUrlsNode) {
    const activeUrls = Array.isArray(state.active_urls) ? state.active_urls.filter(Boolean).slice(0, 8) : [];
    activeUrlsNode.innerHTML = activeUrls.length ? activeUrls.map((url) => escapeHtml(url)).join("<br>") : "";
    activeUrlsNode.classList.toggle("hidden", !activeUrls.length);
  }

  const scanButton = newsModalContent.querySelector("[data-action='scan-news']");
  if (scanButton) scanButton.disabled = ["running", "queued", "pausing", "stopping"].includes(state.status);
  const pauseButton = newsModalTitleActions.querySelector("[data-action='pause-news']");
  if (pauseButton) pauseButton.disabled = !["running", "queued"].includes(state.status);
  const stopButton = newsModalTitleActions.querySelector("[data-action='stop-news']");
  if (stopButton) stopButton.disabled = !["running", "queued", "pausing", "stopping"].includes(state.status);
  const resumeButton = newsModalTitleActions.querySelector("[data-action='resume-news']");
  if (resumeButton) resumeButton.disabled = state.status !== "partial";
  const downloadLink = newsModalContent.querySelector("[data-role='modal-csv-download']");
  if (downloadLink) {
    const ready = Boolean(state.csv_ready || state.last_csv);
    downloadLink.classList.toggle("disabled", !ready);
    downloadLink.setAttribute("aria-disabled", ready ? "false" : "true");
    downloadLink.href = ready ? `/api/news/monitors/${monitor.id}/download` : "#";
  }
  const errorNode = newsModalContent.querySelector("[data-role='modal-error']");
  setTextIfChanged(errorNode, state.error || "");
}

function renderNewsModal() {
  const monitor = activeNewsMonitor();
  const monitors = monitorsForBrandKey(activeNewsBrandKey);
  if (!monitor) return;

  const state = monitor.state || {};
  const disabled = ["running", "queued", "stopping"].includes(state.status);
  const percent = getCompareProgress(state);
  const brand = monitor.brand || "Донор";
  const site = monitor.site_url || (monitor.start_urls || [])[0] || "";
  const isDraftBrand = !brand || /^Новый бренд(?:\s+\d+)?$/i.test(brand);
  const editingTitle = activeNewsBrandNameEditing || isDraftBrand;
  newsModalTitle.innerHTML = editingTitle
    ? `
      <span class="modal-title-editor">
        <input data-role="brand-title-input" type="text" value="${isDraftBrand ? "" : escapeHtml(brand)}" placeholder="Введите название бренда">
        <button class="title-icon-button title-icon-button--save" data-action="save-brand-title" type="button" title="Принять название" aria-label="Принять название">✓</button>
      </span>
    `
    : `
      <span class="modal-title-text">${escapeHtml(brand)}</span>
      <button class="title-icon-button" data-action="edit-brand-title" type="button" title="Редактировать название" aria-label="Редактировать название">✎</button>
    `;
  newsModalSubtitle.textContent = site;
  newsModalTitleActions.innerHTML = `
  ${newsStatusHtml(state.status)}
    <label class="toggle-field modal-title-toggle">
    <input
      class="toggle-field__input"
      data-field="enabled"
      type="checkbox"
      ${monitor.enabled !== false ? "checked" : ""}
    >

    <span class="toggle-field__switch"></span>

    <span class="toggle-field__text">
      ${monitor.enabled !== false ? "Активен" : "Неактивен"}
    </span>
  </label>
`

  const enabledInput = newsModalTitleActions.querySelector('[data-field="enabled"]')
  const enabledText = newsModalTitleActions.querySelector('.toggle-field__text')

  enabledInput.addEventListener('change', () => {
    enabledText.textContent = enabledInput.checked ? 'Активен' : 'Неактивен'
  })

  newsModalContent.dataset.monitorId = monitor.id;
  newsModalContent.innerHTML = `
    <div class="modal-site-row">
      <label class="field">
        <span>Сайт-донор</span>
        <select data-action="modal-select-news-site">
          ${monitors
            .map((item) => {
              const itemSite = item.site_url || (item.start_urls || [])[0] || "";
              return `<option value="${item.id}" ${item.id === String(monitor.primary_donor_id || monitor.id) ? "selected" : ""}>${escapeHtml(itemSite)}</option>`;
            })
            .join("")}
        </select>
        <div class="add-modal-donor-row">
          <input data-role="new-site-donor-url" type="url" placeholder="https://site.ru/">
          <button class="button secondary compact-button add-modal-donor-button" data-action="add-news-site-donor" type="button">Добавить</button>
          <button class="button danger compact-button delete-modal-donor-button" data-action="delete-news-monitor" type="button" ${monitors.length < 2 ? "disabled" : ""}>Удалить донор</button>
        </div>
      </label>
    </div>

    <div class="modal-summary-row">
      <span>Последнее сканирование: <span data-summary="lastScan">${escapeHtml(state.last_scan_at || "—")}</span></span>
      <span>Новинок: <strong data-summary="newCount">${Number(state.new_count || 0)}</strong></span>
      <span>CSV: <span data-summary="csv">${escapeHtml(state.last_csv || "—")}</span></span>
      <span>Этап: <span data-summary="stage">${escapeHtml(state.stage || "—")}</span></span>
      <span>Ссылок/страниц: <strong data-summary="processed">${Number(state.processed || 0)}</strong></span>
      <span>Товаров найдено: <strong data-summary="found">${Number(state.found_products || 0)}</strong></span>
      <span>Сравнено: <strong data-summary="compared">${Number(state.compared_products || 0)}</strong> / <span data-summary="candidates">${Number(state.candidate_products || state.found_products || 0)}</span></span>
      <span>Время: <span data-summary="elapsed">${formatDuration(localElapsedSeconds(state))}</span></span>
    </div>
    <div class="modal-summary-row modal-summary-row--diagnostics">
      <span>В памяти: <strong data-summary="memory">${Number(state.in_memory_products || state.found_products || 0)}</strong></span>
      <span>Очередь: <strong data-summary="queue">${Number(state.queue_size || 0)}</strong></span>
      <span>Активно: <strong data-summary="active">${Number(state.active_tasks || 0)}</strong></span>
      <span>Ошибок страниц: <strong data-summary="failed">${Number(state.failed_pages || 0)}</strong></span>
      <span>Исключено по статусу: <strong data-summary="availabilitySkipped">${Number(state.availability_skipped || 0)}</strong></span>
      <span>Без прогресса: <span data-summary="stall">${formatDuration(Number(state.stall_seconds || 0))}</span></span>
      <span>Событие: <span data-summary="lastEvent">${escapeHtml(state.last_event || "—")}</span></span>
      <span>Предупреждение: <span data-summary="lastWarning">${escapeHtml(state.last_warning || "")}</span></span>
    </div>
    <div class="missing-summary-panel" data-role="modal-missing-summary">
      ${missingSummaryHtml(aggregateMissingByFeed([state]), Number(state.new_count || 0))}
    </div>
    <div class="news-progress-block">
      <div class="progress-track"><div class="progress-fill" data-role="modal-progress-fill" style="width: ${percent}%"></div></div>
      <div class="percent-row">
        <span>Прогресс сравнения: <span data-role="modal-percent">${percent}%</span></span>
        <span data-role="modal-current-url">${escapeHtml(state.currenturl || "")}</span>
      </div>
      <div class="active-url-list ${Array.isArray(state.active_urls) && state.active_urls.length ? "" : "hidden"}" data-role="modal-active-urls">
        ${(Array.isArray(state.active_urls) ? state.active_urls.slice(0, 8) : []).map((url) => escapeHtml(url)).join("<br>")}
      </div>
    </div>

    <div class="modal-settings-section modal-settings-section--scheduler">
      <div class="modal-settings-section__head">
        <h3>Настройки планировщика</h3>
      </div>
      <div class="modal-form-grid">
      <label class="field">
        <span>Расписание</span>
        <select data-field="schedule_type">${scheduleTypeOptionsHtml(monitor.schedule_type || "daily")}</select>
      </label>
      <label class="field">
        <span>Время МСК</span>
        <input data-field="scan_time" type="time" value="${escapeHtml(monitor.scan_time || "01:00")}">
      </label>
      <label class="field">
        <span>День недели</span>
        <select data-field="weekday">${weekdayOptionsHtml(monitor.weekday || 0)}</select>
      </label>
      <label class="field">
        <span>Разовый запуск</span>
        <input data-field="next_run_at" type="datetime-local" value="${escapeHtml(formatDateTimeLocal(monitor.next_run_at || ""))}">
      </label>
      </div>
    </div>

    <div class="modal-settings-section">
      <div class="modal-settings-section__head">
        <h3>Настройки выбранного донора</h3>
      </div>
      <div class="modal-form-grid">
      <label class="field modal-wide-field">
        <span>Основной сайт</span>
        <input data-field="site_url" type="text" value="${escapeHtml(monitor.site_url || "")}">
      </label>
      <label class="field modal-wide-field">
        <span>Стартовые URL</span>
        <textarea data-field="start_urls" rows="2">${escapeHtml((monitor.start_urls || []).join("\n"))}</textarea>
      </label>
      <label class="field">
        <span>Потоки</span>
        <input data-field="thread_count" type="number" min="1" max="16" value="${escapeHtml(monitor.thread_count || 4)}">
      </label>
      <label class="field">
        <span>Подключение</span>
        <select data-field="connection_method">${connectionOptionsHtml(monitor.connection_method || "requests")}</select>
      </label>
      <label class="toggle-field modal-inline-toggle">
        <input data-field="auto_connection_fallback" type="checkbox" ${monitor.auto_connection_fallback !== false ? "checked" : ""}>
        <span>Автопереключение</span>
      </label>
      <label class="field modal-wide-field">
        <span>Исключения</span>
        <textarea data-field="exclusions" rows="2">${escapeHtml((monitor.exclusions || []).join("\n"))}</textarea>
      </label>
      <label class="field modal-wide-field">
        <span>Фильтр товарных ссылок</span>
        <textarea data-field="product_url_filters" rows="2">${escapeHtml((monitor.product_url_filters || []).join("\n"))}</textarea>
      </label>
      <label class="field modal-wide-field">
        <span>Исключения товарных ссылок</span>
        <textarea data-field="product_url_exclusions" rows="2" placeholder="/recommend">${escapeHtml((monitor.product_url_exclusions || []).join("\n"))}</textarea>
      </label>
      </div>
    </div>

    <div class="modal-settings-section">
      <div class="selector-toggle-row">
        <button class="button secondary compact-button" data-action="toggle-modal-selectors" type="button">
          ${activeNewsSelectorsOpen ? "Свернуть селекторы" : "Селекторы"}
        </button>
      </div>
      <div class="modal-form-grid selector-panel ${activeNewsSelectorsOpen ? "" : "hidden"}">
      <label class="field">
        <span>Селектор карточки</span>
        <input data-rule="product_card_selector" type="text" value="${escapeHtml(monitor.extraction_rules?.product_card_selector || "")}">
      </label>
      <label class="field">
        <span>Селектор ссылки</span>
        <input data-rule="product_url_selector" type="text" value="${escapeHtml(monitor.extraction_rules?.product_url_selector || "")}">
      </label>
      <label class="field">
        <span>Селектор модели</span>
        <input data-rule="model_selector" type="text" value="${escapeHtml(monitor.extraction_rules?.model_selector || "")}">
      </label>
      <label class="field">
        <span>Селектор цены</span>
        <input data-rule="price_selector" type="text" value="${escapeHtml(monitor.extraction_rules?.price_selector || "")}">
      </label>
      <label class="field">
        <span>Селектор названия</span>
        <input data-selector="name_selector" type="text" value="${escapeHtml(monitor.selector_settings?.name_selector || "")}">
      </label>
      <label class="field">
        <span>Селектор наличия</span>
        <input data-selector="availability_selector" type="text" value="${escapeHtml(monitor.selector_settings?.availability_selector || "")}">
      </label>
      <label class="field">
        <span>Селектор фото</span>
        <input data-selector="photo_selector" type="text" value="${escapeHtml(monitor.selector_settings?.photo_selector || "")}">
      </label>
      <label class="field modal-wide-field">
        <span>Исключение товаров по статусу</span>
        <textarea data-selector="availability_exclusions" rows="3" placeholder="Снят с производства&#10;Нет в наличии">${escapeHtml((monitor.selector_settings?.availability_exclusions || []).join("\n"))}</textarea>
      </label>
      </div>
    </div>

    <div class="modal-settings-section">
      <div class="selector-toggle-row">
        <button class="button secondary compact-button" data-action="toggle-modal-replace-rules" type="button">
          ${activeNewsReplaceRulesOpen ? "Свернуть правила" : "Правила поиск/замены"}
        </button>
      </div>
      <div class="modal-form-grid selector-panel ${activeNewsReplaceRulesOpen ? "" : "hidden"}">
      <label class="field modal-wide-field">
        <span>Начало парсинга модели</span>
        <input data-rule="model_start_marker" type="text" value="${escapeHtml(monitor.extraction_rules?.model_start_marker || "")}" placeholder="<h1 class=&quot;detail__title&quot;>">
      </label>
      <label class="field modal-wide-field">
        <span>Конец парсинга модели</span>
        <input data-rule="model_end_marker" type="text" value="${escapeHtml(monitor.extraction_rules?.model_end_marker || "")}" placeholder="</h1>">
      </label>
      <label class="field modal-wide-field">
        <span>Правила для модели</span>
        <textarea data-rule="model_replace_rules" rows="5" placeholder="{reg[#[^A-Za-z0-9./\\-\\s]#]}|&#10;{reg[#\\s{2,}#]}| ">${escapeHtml(monitor.extraction_rules?.model_replace_rules || "")}</textarea>
      </label>
      </div>
    </div>

    <div class="modal-actions">
      <button class="button primary" data-action="save-news-monitor" type="button">Сохранить изменения</button>
      <button class="button secondary" data-action="scan-news" type="button" ${disabled ? "disabled" : ""}>Сканировать наличие новинок</button>
      <a class="button download ${state.csv_ready || state.last_csv ? "" : "disabled"}" data-role="modal-csv-download" href="${state.csv_ready || state.last_csv ? `/api/news/monitors/${monitor.id}/download` : "#"}" aria-disabled="${state.csv_ready || state.last_csv ? "false" : "true"}">Скачать CSV</a>
      <span class="save-notice" data-role="monitor-notice"></span>
    </div>
    <p class="error-text" data-role="modal-error">${escapeHtml(state.error || "")}</p>
  `;
}

function renderNews() {
  renderNewsSettings();
  renderFeedStorage();
  renderNewsMonitors();
}

function collectMonitorPayload(root) {
  const scope = root === newsModalContent ? newsMonitorModal : root;
  const payload = {
    collapsed: root.classList?.contains("news-monitor-card") ? root.classList.contains("collapsed") : true,
    extraction_rules: {},
    selector_settings: {},
  };
  if (root === newsModalContent) {
    const primaryDonorSelect = scope.querySelector("[data-action='modal-select-news-site']");
    if (primaryDonorSelect) {
      payload.primary_donor_id = primaryDonorSelect.value;
    }
  }
  scope.querySelectorAll("[data-field]").forEach((input) => {
    const key = input.dataset.field;
    if (input.type === "checkbox") {
      payload[key] = input.checked;
    } else if (key === "thread_count" || key === "weekday") {
      payload[key] = Number(input.value || 0);
    } else {
      payload[key] = input.value;
    }
  });
  scope.querySelectorAll("[data-rule]").forEach((input) => {
    payload.extraction_rules[input.dataset.rule] = input.value.trim();
  });
  scope.querySelectorAll("[data-selector]").forEach((input) => {
    if (input.dataset.selector === "availability_exclusions") {
      payload.selector_settings[input.dataset.selector] = input.value
        .split(/\r?\n|;/)
        .map((item) => item.trim())
        .filter(Boolean);
    } else {
      payload.selector_settings[input.dataset.selector] = input.value.trim();
    }
  });
  return payload;
}

async function saveNewsSettings() {
  if (isHydratingNews || !newsData) return;
  if (newsSettingsNotice) newsSettingsNotice.textContent = "Сохраняю...";
  const ownSites = collectOwnSites();
  const payload = {
    own_sites: ownSites,
    feed_urls: ownSites.map((site) => site.feed_url).join("\n"),
    feed_generate_urls: ownSites.map((site) => site.feed_generate_url).join("\n"),
    smtp: {
      host: smtpHost.value.trim(),
      port: Number(smtpPort.value || 465),
      security: smtpSecurity.value,
      username: smtpUsername.value.trim(),
      password: smtpPassword.value.trim(),
      recipients: smtpRecipients.value,
    },
  };
  newsData = applyNewsPayload(await requestJson("/api/news/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  }));
  renderNewsSettings();
  if (newsSettingsNotice) {
    newsSettingsNotice.textContent = "Настройки сохранены";
    window.setTimeout(() => {
      newsSettingsNotice.textContent = "";
    }, 2500);
  }
}

async function testNewsEmail() {
  if (newsSettingsNotice) newsSettingsNotice.textContent = "Проверяю email...";
  await saveNewsSettings();
  await requestJson("/api/news/email/test", { method: "POST" });
  if (newsSettingsNotice) {
    newsSettingsNotice.textContent = "Тестовое письмо отправлено";
    window.setTimeout(() => {
      newsSettingsNotice.textContent = "";
    }, 3000);
  }
}

function scheduleSaveNewsSettings() {
  if (isHydratingNews) return;
  window.clearTimeout(newsSaveTimer);
  newsSaveTimer = window.setTimeout(() => {
    saveNewsSettings().catch((error) => {
      errorText.textContent = error.message;
    });
  }, 500);
}
async function saveNewsMonitor(root) {
  const monitorId = root.dataset.monitorId;
  const notice = root.querySelector("[data-role='monitor-notice']");
  if (notice) notice.textContent = "Сохраняю...";
  try {
    const data = await requestJson(`/api/news/monitors/${monitorId}`, {
      method: "PATCH",
      body: JSON.stringify(collectMonitorPayload(root)),
    });
    const index = (newsData.monitors || []).findIndex((monitor) => monitor.id === monitorId);
    if (index >= 0) newsData.monitors[index] = data.monitor;
    if (notice) {
      notice.textContent = "Настройки сохранены";
      window.setTimeout(() => {
        notice.textContent = "";
      }, 2500);
    }
    return data.monitor;
  } catch (error) {
    if (notice) notice.textContent = error.message;
    throw error;
  }
}

async function saveNewsBrandTitle() {
  const monitor = activeNewsMonitor();
  if (!monitor) return;
  const input = newsModalTitle.querySelector("[data-role='brand-title-input']");
  const brand = input?.value.trim() || "";
  if (!brand) {
    input?.focus();
    return;
  }
  const data = await requestJson(`/api/news/monitors/${monitor.id}`, {
    method: "PATCH",
    body: JSON.stringify({ brand }),
  });
  newsData = applyNewsPayload(await requestJson("/api/news"));
  const updated = data.monitor || monitor;
  activeNewsBrandKey = `${updated.group || monitor.group || "Маржа"}::${updated.brand || brand}`;
  selectedNewsSites.set(activeNewsBrandKey, updated.id || monitor.id);
  activeNewsBrandNameEditing = false;
  renderNewsMonitors();
  renderNewsModal();
}

async function persistPendingNewsBrandTitle() {
  const monitor = activeNewsMonitor();
  if (!monitor) return null;
  const input = newsModalTitle.querySelector("[data-role='brand-title-input']");
  const brand = input?.value.trim() || "";
  if (!brand) return monitor;
  const data = await requestJson(`/api/news/monitors/${monitor.id}`, {
    method: "PATCH",
    body: JSON.stringify({ brand }),
  });
  newsData = applyNewsPayload(await requestJson("/api/news"));
  const updated = data.monitor || monitor;
  activeNewsBrandKey = `${updated.group || monitor.group || "Маржа"}::${updated.brand || brand}`;
  selectedNewsSites.set(activeNewsBrandKey, updated.id || monitor.id);
  activeNewsBrandNameEditing = false;
  return updated;
}

async function mergeNewsMonitorDetails(monitors) {
  if (!newsData) newsData = { monitors: [] };
  const byId = new Map((newsData.monitors || []).map((monitor) => [monitor.id, monitor]));
  (monitors || []).forEach((monitor) => {
    byId.set(monitor.id, mergeNewsMonitorPayloadItem({ ...monitor, __detail_loaded: true }));
  });
  newsData.monitors = Array.from(byId.values());
}

async function loadNewsMonitorDetail(monitorId) {
  if (!monitorId) return null;
  const data = await requestJson(`/api/news/monitors/${monitorId}`);
  const monitors = data.brand_monitors || (data.monitor ? [data.monitor] : []);
  await mergeNewsMonitorDetails(monitors);
  return data.monitor || null;
}

async function loadNewsSettingsOnly() {
  const data = await requestJson("/api/news?summary=1&monitors=0");
  setConnectionMethods(data.connection_methods);
  newsData = {
    ...(newsData || {}),
    ...data,
    monitors: newsData?.monitors || [],
  };
  renderNewsSettings();
  renderFeedStorage();
  return newsData;
}

async function loadNews() {
  if (!newsLoadPromise) {
    newsLoadPromise = requestJson("/api/news?summary=1")
      .then(async (data) => {
        newsData = applyNewsPayload(data);
        if (pendingNewsMonitorId) {
          const monitor = (newsData.monitors || []).find((item) => item.id === pendingNewsMonitorId);
          if (monitor) {
            activeNewsBrandKey = `${monitor.group || "Маржа"}::${monitor.brand || ""}`;
            selectedNewsSites.set(activeNewsBrandKey, monitor.id);
            await loadNewsMonitorDetail(monitor.id);
          }
        }
        return newsData;
      })
      .finally(() => {
        newsLoadPromise = null;
      });
  }
  await newsLoadPromise;
  renderNews();
  if (pendingNewsMonitorId) {
    const monitor = (newsData?.monitors || []).find((item) => item.id === pendingNewsMonitorId);
    pendingNewsMonitorId = "";
    if (monitor) {
      openNewsModal(`${monitor.group || "Маржа"}::${monitor.brand || ""}`, { replace: true });
    }
  }
}

function renderAll() {
  renderTabs();
  const project = activeProject();
  projectView.classList.toggle("hidden", activeView !== "projects");
  newItemsView.classList.toggle("hidden", activeView !== "news");
  fileImportView.classList.toggle("hidden", activeView !== "import");
  settingsView.classList.toggle("hidden", activeView !== "settings");
  logsView.classList.toggle("hidden", activeView !== "logs");
  if (activeView === "projects") {
    if (project && !project.__detail_loaded) {
      renderState(project);
      loadProjectDetail(project.id).then(renderAll).catch((error) => {
        errorText.textContent = error.message;
      });
      return;
    }
    renderProjectForm(project);
    renderState(project);
  } else if (activeView === "news") {
    if (newsData) {
      renderNews();
    } else {
      loadNews().catch((error) => {
        errorText.textContent = error.message;
      });
    }
  } else if (activeView === "settings") {
    if (newsData?.own_sites) {
      renderNewsSettings();
      renderFeedStorage();
    } else {
      loadNewsSettingsOnly().catch((error) => {
        errorText.textContent = error.message;
      });
    }
  } else if (activeView === "import") {
    if (fileImportLoaded) {
      renderFileImport();
    } else {
      loadFileImport().catch((error) => {
        errorText.textContent = error.message;
      });
    }
  } else {
    loadLogs();
  }
}

async function loadProjectDetail(projectId) {
  if (!projectId) return null;
  const data = await requestJson(`/api/projects/${projectId}`);
  const detail = { ...(data.project || {}), __detail_loaded: true };
  const index = projects.findIndex((project) => project.id === detail.id);
  if (index >= 0) {
    projects[index] = mergeProjectPayloadItem(detail);
  } else {
    projects.push(detail);
  }
  activeProjectId = detail.id;
  return detail;
}

async function loadProjects() {
  const data = await requestJson("/api/projects?summary=1");
  setConnectionMethods(data.connection_methods);
  projects = applyProjectPayload(data.projects || []);
  if (!activeProjectId && projects.length) {
    activeProjectId = projects[0].id;
  }
  if (!projects.some((project) => project.id === activeProjectId) && projects.length) {
    activeProjectId = projects[0].id;
  }
  if (activeProjectId) {
    await loadProjectDetail(activeProjectId);
    pushAppRoute("projects", { projectId: activeProjectId }, true);
  }
  renderAll();
}

async function saveActiveProject() {
  if (isHydratingForm) return null;
  const project = activeProject();
  if (!project) return null;

  const payload = {
    name: projectName.value.trim() || project.name,
    start_urls: startUrls.value,
    product_url_filters: project.product_url_filters || [],
    product_url_exclusions: project.product_url_exclusions || [],
    extraction_rules: {
      product_card_selector: productCardSelector.value.trim(),
      product_url_selector: productUrlSelector.value.trim(),
      model_selector: modelSelector.value.trim(),
      price_selector: priceSelector.value.trim(),
      model_start_marker: modelStartMarker.value.trim(),
      model_end_marker: modelEndMarker.value.trim(),
      model_replace_rules: modelReplaceRules.value.trim(),
    },
    thread_count: Number(threadCount.value || 4),
    connection_method: connectionMethod.value,
    auto_connection_fallback: autoConnectionFallback.checked,
    persist_profile: persistProfile.checked,
  };
  const data = await requestJson(`/api/projects/${project.id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  Object.assign(project, data.project);
  renderTabs();
  renderState(project);
  return project;
}

function scheduleSaveActiveProject() {
  if (isHydratingForm) return;
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    saveActiveProject().catch((error) => {
      errorText.textContent = error.message;
    });
  }, 350);
}

async function loadLogs(force = false) {
  const data = await requestJson("/api/logs?limit=200&page=1");
  autoCleanup.checked = Boolean(data.auto_cleanup);
  const nextSignature = data.logs_signature || "";
  if (!force && logsSignature && nextSignature && nextSignature === logsSignature) {
    return;
  }
  logsSignature = nextSignature;
  logsList.innerHTML = "";
  const logs = data.logs || [];
  if (!logs.length) {
    logsList.textContent = "Логов пока нет.";
    return;
  }
  logs.slice().reverse().forEach((entry) => {
    const row = document.createElement("div");
    row.className = "log-entry";
    row.innerHTML = `
      <span>${entry.time || ""}</span>
      <strong>${entry.project_name || ""}</strong>
      <span class="log-level-${entry.level || "info"}">${entry.level || "info"}</span>
      <span>${entry.message || ""}</span>
    `;
    logsList.append(row);
  });
}

addProjectButton.addEventListener("click", async () => {
  const name = `Проект ${projects.length + 1}`;
  const data = await requestJson("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name, start_urls: "https://www.maunfeld.ru/" }),
  });
  projects.push(data.project);
  activeProjectId = data.project.id;
  setActiveView("projects");
  renderAll();
});

projectsTabButton.addEventListener("click", () => {
  setActiveView("projects", { projectId: activeProjectId || "" });
  configureProgressStream();
  if (!projects.length) {
    loadProjects().catch((error) => { errorText.textContent = error.message; });
  } else {
    renderAll();
  }
});

logsTabButton.addEventListener("click", () => {
  setActiveView("logs");
  configureProgressStream();
  renderAll();
});

newItemsTabButton.addEventListener("click", () => {
  setActiveView("news");
  configureProgressStream();
  renderAll();
});

importTabButton.addEventListener("click", () => {
  setActiveView("import");
  configureProgressStream();
  renderAll();
});

settingsTabButton.addEventListener("click", () => {
  setActiveView("settings");
  configureProgressStream();
  renderAll();
});

if (fileImportExclusions && fileImportSaveNotice) {
  fileImportExclusions.addEventListener("input", () => {
    fileImportSaveNotice.textContent = "";
  });
}

if (fileImportModelField && fileImportSaveNotice) {
  fileImportModelField.addEventListener("input", () => {
    fileImportSaveNotice.textContent = "";
  });
}

for (const field of [fileImportModelReplaceRules]) {
  if (field && fileImportSaveNotice) {
    field.addEventListener("input", () => {
      fileImportSaveNotice.textContent = "";
    });
  }
}

if (saveFileImportButton && fileImportSaveNotice) {
  saveFileImportButton.addEventListener("click", () => {
    saveFileImport().catch((error) => {
      fileImportSaveNotice.textContent = error.message;
      saveFileImportButton.disabled = false;
    });
  });
}

if (fileImportInput) {
  fileImportInput.addEventListener("change", async () => {
    const file = fileImportInput.files?.[0] || null;
    if (!file) return;
    fileImportUploading = true;
    fileImportProgress.classList.remove("hidden");
    setFileImportProgress(0, "Подготовка...");
    renderFileImport();
    try {
      fileImportData = await uploadFileImport(file);
      fileImportLoaded = true;
      setFileImportProgress(100, "Файл выгружен");
    } catch (error) {
      fileImportInput.value = "";
      fileImportNotice.textContent = error.message;
    } finally {
      fileImportUploading = false;
      renderFileImport();
    }
  });
}

if (clearFileImportButton) {
  clearFileImportButton.addEventListener("click", async () => {
    clearFileImportButton.disabled = true;
    fileImportNotice.textContent = "Удаляю файл...";
    fileImportProgress.classList.remove("hidden");
    setFileImportProgress(100, "Удаляю файл...");
    try {
      await deleteFileImport();
    } catch (error) {
      fileImportNotice.textContent = error.message;
      clearFileImportButton.disabled = false;
    }
  });
}

if (compareFileImportButton) {
  compareFileImportButton.addEventListener("click", async () => {
    try {
      await saveFileImport();
      await compareFileImport();
    } catch (error) {
      fileImportNotice.textContent = error.message;
      compareFileImportButton.disabled = false;
    }
  });
}

projectName.addEventListener("input", scheduleSaveActiveProject);
startUrls.addEventListener("input", scheduleSaveActiveProject);
threadCount.addEventListener("input", scheduleSaveActiveProject);
threadCount.addEventListener("change", saveActiveProject);
connectionMethod.addEventListener("change", saveActiveProject);
autoConnectionFallback.addEventListener("change", saveActiveProject);
persistProfile.addEventListener("change", saveActiveProject);
[
  productCardSelector,
  productUrlSelector,
  modelSelector,
  priceSelector,
  modelStartMarker,
  modelEndMarker,
  modelReplaceRules,
].forEach((input) => input.addEventListener("input", scheduleSaveActiveProject));

[
  smtpHost,
  smtpPort,
  smtpSecurity,
  smtpUsername,
  smtpPassword,
  smtpRecipients,
].forEach((input) => {
  input.addEventListener("input", () => {
    if (newsSettingsNotice) newsSettingsNotice.textContent = "";
  });
});

ownSitesList.addEventListener("input", () => {
  if (newsSettingsNotice) newsSettingsNotice.textContent = "";
});

ownSitesList.addEventListener("click", (event) => {
  const removeButton = event.target.closest("[data-action='remove-own-site']");
  if (removeButton) {
    removeButton.closest("[data-own-site-index]")?.remove();
    if (!ownSitesList.querySelector("[data-own-site-index]")) {
      ownSitesList.innerHTML = `<div class="own-site-empty">Фиды не добавлены.</div>`;
    }
    if (newsSettingsNotice) newsSettingsNotice.textContent = "";
    return;
  }

  const saveButton = event.target.closest("[data-action='save-own-site']");
  if (saveButton) {
    const card = saveButton.closest("[data-own-site-index]");
    const notice = card?.querySelector("[data-role='own-site-notice']");
    if (notice) notice.textContent = "Сохраняю...";
    saveNewsSettings()
      .then(() => {
        if (notice) {
          notice.textContent = "Изменения сохранены";
          window.setTimeout(() => {
            notice.textContent = "";
          }, 2500);
        }
      })
      .catch((error) => {
        if (notice) notice.textContent = error.message;
        errorText.textContent = error.message;
      });
  }
});

function openAddFeedModal() {
  newFeedName.value = "";
  newFeedUrl.value = "";
  newFeedGenerateUrl.value = "";
  addFeedModal.classList.remove("hidden");
  addFeedModal.setAttribute("aria-hidden", "false");
  newFeedUrl.focus();
}

function closeAddFeedModal() {
  addFeedModal.classList.add("hidden");
  addFeedModal.setAttribute("aria-hidden", "true");
}

function appendOwnSiteCard(name, feedUrl, feedGenerateUrl) {
  const current = collectOwnSites();
  current.push({ name: name || `Фид ${current.length + 1}`, feed_url: feedUrl, feed_generate_url: feedGenerateUrl });
  newsData = {
    ...(newsData || {}),
    own_sites: current,
    feed_urls: current.map((site) => site.feed_url),
    feed_generate_urls: current.map((site) => site.feed_generate_url),
  };
  renderOwnSites();
}

addOwnSiteButton.addEventListener("click", openAddFeedModal);

confirmAddFeedButton.addEventListener("click", () => {
  const name = newFeedName.value.trim();
  const feedUrl = newFeedUrl.value.trim();
  const feedGenerateUrl = newFeedGenerateUrl.value.trim();
  if (!feedUrl && !feedGenerateUrl) return;
  appendOwnSiteCard(name, feedUrl, feedGenerateUrl);
  closeAddFeedModal();
  if (newsSettingsNotice) newsSettingsNotice.textContent = "";
});

[cancelAddFeedButton, cancelAddFeedIconButton].forEach((button) => {
  button.addEventListener("click", closeAddFeedModal);
});

addFeedModal.addEventListener("click", (event) => {
  if (event.target === addFeedModal) closeAddFeedModal();
});

saveNewsSettingsButton.addEventListener("click", () => {
  saveNewsSettings().catch((error) => {
    if (newsSettingsNotice) newsSettingsNotice.textContent = error.message;
    errorText.textContent = error.message;
  });
});

toggleSmtpPasswordButton.addEventListener("click", () => {
  const isHidden = smtpPassword.type === "password";
  smtpPassword.type = isHidden ? "text" : "password";
  toggleSmtpPasswordButton.title = isHidden ? "Скрыть пароль" : "Показать пароль";
  toggleSmtpPasswordButton.setAttribute("aria-label", toggleSmtpPasswordButton.title);
});

testNewsEmailButton.addEventListener("click", () => {
  testNewsEmail().catch((error) => {
    if (newsSettingsNotice) newsSettingsNotice.textContent = error.message;
    errorText.textContent = error.message;
  });
});

async function addNewsMonitorToGroup(group) {
  try {
    const data = await requestJson("/api/news/monitors", {
      method: "POST",
      body: JSON.stringify({
        brand: "Новый бренд",
        group,
        start_urls: "",
        create_new_brand: true,
      }),
    });
    if (!newsData) newsData = applyNewsPayload(await requestJson("/api/news"));
    newsData.monitors.push(data.monitor);
    renderNewsMonitors();
    selectedNewsSites.set(`${data.monitor.group}::${data.monitor.brand}`, data.monitor.id);
    openNewsModal(`${data.monitor.group}::${data.monitor.brand}`);
    activeNewsBrandNameEditing = true;
    renderNewsModal();
  } catch (error) {
    errorText.textContent = error.message;
  }
}

async function runNewsAction(monitorId, endpoint) {
  const data = await requestJson(`/api/news/monitors/${monitorId}/${endpoint}`, { method: "POST" });
  const index = (newsData?.monitors || []).findIndex((monitor) => monitor.id === monitorId);
  if (index >= 0) newsData.monitors[index] = data.monitor;
  return data.monitor;
}

function selectedMonitorIdForBrandKey(brandKey, action = "") {
  const monitors = monitorsForBrandKey(brandKey);
  if (!monitors.length) return null;
  if (action === "pause-news" || action === "stop-news") {
    const active = monitors.find((monitor) => ["running", "queued", "pausing", "stopping"].includes(monitor.state?.status));
    if (active) return active.id;
  }
  if (action === "resume-news") {
    const partial = monitors.find((monitor) => monitor.state?.status === "partial");
    if (partial) return partial.id;
  }
  const selectedId = selectedNewsSites.get(brandKey);
  return monitors.find((monitor) => monitor.id === selectedId)?.id || monitors[0].id;
}

newsGroups.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-action='pause-news'], [data-action='stop-news'], [data-action='resume-news']");
  if (actionButton) {
    event.preventDefault();
    event.stopPropagation();
    const tile = actionButton.closest("[data-action='open-news-brand']");
    const action = actionButton.dataset.action;
    const monitorId = selectedMonitorIdForBrandKey(tile?.dataset.brandKey || "", action);
    if (!monitorId) return;
    const endpoint = action === "pause-news" ? "pause" : action === "resume-news" ? "resume" : "stop";
    runNewsAction(monitorId, endpoint)
      .then(() => renderNewsMonitors())
      .catch((error) => {
        errorText.textContent = error.message;
      });
    return;
  }

  const toggleButton = event.target.closest("[data-action='toggle-news-group']");
  if (toggleButton) {
    const group = toggleButton.dataset.group || "";
    const section = toggleButton.closest(".news-group-panel");
    const list = section?.querySelector(".news-brand-grid");
    const icon = toggleButton.querySelector(".news-group-toggle-icon");
    const nextCollapsed = !collapsedNewsGroups.has(group);
    if (collapsedNewsGroups.has(group)) {
      collapsedNewsGroups.delete(group);
    } else {
      collapsedNewsGroups.add(group);
    }
    animateNewsGroup(list, nextCollapsed);
    toggleButton.setAttribute("aria-expanded", nextCollapsed ? "false" : "true");
    if (icon) icon.textContent = nextCollapsed ? "▸" : "▾";
    return;
  }

  const addButton = event.target.closest("[data-action='add-news-monitor-group']");
  if (addButton) {
    addNewsMonitorToGroup(addButton.dataset.group || "Маржа");
    return;
  }

  const deleteButton = event.target.closest("[data-action='delete-news-monitor-card']");
  if (deleteButton) {
    event.stopPropagation();
    openDeleteNewsMonitorModal(deleteButton.dataset.monitorId, "brand", deleteButton.dataset.brandKey);
    return;
  }

  const tile = event.target.closest("[data-action='open-news-brand']");
  if (!tile) return;
  openNewsModal(tile.dataset.brandKey);
});

closeNewsModalButton.addEventListener("click", closeNewsModal);

cancelDeleteProjectButton.addEventListener("click", closeDeleteProjectModal);
cancelDeleteProjectIconButton.addEventListener("click", closeDeleteProjectModal);
confirmDeleteProjectButton.addEventListener("click", () => {
  deletePendingProject().catch((error) => {
    errorText.textContent = error.message;
    closeDeleteProjectModal();
  });
});

deleteProjectModal.addEventListener("click", (event) => {
  if (event.target === deleteProjectModal) {
    closeDeleteProjectModal();
  }
});

cancelDeleteNewsMonitorButton.addEventListener("click", closeDeleteNewsMonitorModal);
cancelDeleteNewsMonitorIconButton.addEventListener("click", closeDeleteNewsMonitorModal);
async function confirmDeleteNewsMonitor() {
  if (!pendingDeleteNewsMonitorId) {
    deleteNewsMonitorText.textContent = "Не выбран донор для удаления.";
    return;
  }
  const originalText = confirmDeleteNewsMonitorButton.textContent;
  confirmDeleteNewsMonitorButton.disabled = true;
  confirmDeleteNewsMonitorButton.textContent = "Удаляю...";
  try {
    await deletePendingNewsMonitor();
  } catch (error) {
    deleteNewsMonitorText.textContent = error.message;
    errorText.textContent = error.message;
  } finally {
    confirmDeleteNewsMonitorButton.disabled = false;
    confirmDeleteNewsMonitorButton.textContent = originalText;
  }
}

deleteNewsMonitorModal.addEventListener("click", (event) => {
  const confirmButton = event.target.closest("[data-action='confirm-delete-news-monitor']");
  if (confirmButton) {
    event.preventDefault();
    event.stopPropagation();
    confirmDeleteNewsMonitor();
    return;
  }
  if (event.target === deleteNewsMonitorModal) {
    closeDeleteNewsMonitorModal();
  }
});

newsMonitorModal.addEventListener("click", (event) => {
  if (event.target === newsMonitorModal) {
    closeNewsModal();
  }
});

newsModalContent.addEventListener("change", async (event) => {
  const select = event.target.closest("[data-action='modal-select-news-site']");
  if (!select) return;
  selectedNewsSites.set(activeNewsBrandKey, select.value);
  const monitorId = newsModalContent.dataset.monitorId;
  if (monitorId) {
    try {
      const data = await requestJson(`/api/news/monitors/${monitorId}`, {
        method: "PATCH",
        body: JSON.stringify({ primary_donor_id: select.value }),
      });
      const index = (newsData.monitors || []).findIndex((monitor) => monitor.id === monitorId);
      if (index >= 0) newsData.monitors[index] = data.monitor;
    } catch (error) {
      errorText.textContent = error.message;
      return;
    }
  }
  activeNewsSelectorsOpen = false;
  activeNewsReplaceRulesOpen = false;
  renderNewsModal();
});

newsModalTitleActions.addEventListener("click", async (event) => {
  const actionButton = event.target.closest("[data-action='pause-news'], [data-action='stop-news'], [data-action='resume-news']");
  if (!actionButton) return;
  const action = actionButton.dataset.action;
  const endpoint = action === "pause-news" ? "pause" : action === "resume-news" ? "resume" : "stop";
  try {
    const monitorId = newsModalContent.dataset.monitorId;
    const data = await requestJson(`/api/news/monitors/${monitorId}/${endpoint}`, { method: "POST" });
    const index = (newsData.monitors || []).findIndex((monitor) => monitor.id === monitorId);
    if (index >= 0) newsData.monitors[index] = data.monitor;
    renderNewsMonitors();
    renderNewsModal();
  } catch (error) {
    errorText.textContent = error.message;
  }
});

newsModalTitle.addEventListener("click", (event) => {
  const editButton = event.target.closest("[data-action='edit-brand-title']");
  if (editButton) {
    activeNewsBrandNameEditing = true;
    renderNewsModal();
    newsModalTitle.querySelector("[data-role='brand-title-input']")?.focus();
    return;
  }

  const saveButton = event.target.closest("[data-action='save-brand-title']");
  if (saveButton) {
    saveNewsBrandTitle().catch((error) => {
      errorText.textContent = error.message;
    });
  }
});

newsModalTitle.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || !event.target.closest("[data-role='brand-title-input']")) return;
  event.preventDefault();
  saveNewsBrandTitle().catch((error) => {
    errorText.textContent = error.message;
  });
});

newsModalContent.addEventListener("click", async (event) => {
  const selectorToggle = event.target.closest("[data-action='toggle-modal-selectors']");
  if (selectorToggle) {
    activeNewsSelectorsOpen = !activeNewsSelectorsOpen;
    renderNewsModal();
    return;
  }

  const replaceRulesToggle = event.target.closest("[data-action='toggle-modal-replace-rules']");
  if (replaceRulesToggle) {
    activeNewsReplaceRulesOpen = !activeNewsReplaceRulesOpen;
    renderNewsModal();
    return;
  }

  const addSiteDonorButton = event.target.closest("[data-action='add-news-site-donor']");
  if (addSiteDonorButton) {
    const notice = newsModalContent.querySelector("[data-role='monitor-notice']");
    try {
      let currentMonitor = await persistPendingNewsBrandTitle();
      currentMonitor = activeNewsMonitor() || currentMonitor;
      if (!currentMonitor) return;
      const urlInput = newsModalContent.querySelector("[data-role='new-site-donor-url']");
      const siteUrl = urlInput?.value.trim() || "";
      if (!siteUrl) {
        errorText.textContent = "Укажите сайт-донора.";
        if (notice) notice.textContent = "Укажите сайт-донора.";
        urlInput?.focus();
        return;
      }
      if (notice) notice.textContent = "Сохраняю...";
      if (!newsData) newsData = applyNewsPayload(await requestJson("/api/news"));
      const currentSite = currentMonitor.site_url || "";
      if (!currentSite) {
        const payload = collectMonitorPayload(newsModalContent);
        payload.site_url = siteUrl;
        const data = await requestJson(`/api/news/monitors/${currentMonitor.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        newsData = applyNewsPayload(await requestJson("/api/news"));
        const updated = data.monitor || currentMonitor;
        activeNewsBrandKey = `${updated.group || currentMonitor.group || "Маржа"}::${updated.brand || currentMonitor.brand || "Новый донор"}`;
        selectedNewsSites.set(activeNewsBrandKey, updated.id);
        if (notice) {
          notice.textContent = "Сайт-донор сохранен";
          window.setTimeout(() => {
            notice.textContent = "";
          }, 2500);
        }
      } else {
        await saveNewsMonitor(newsModalContent);
        const data = await requestJson("/api/news/monitors", {
          method: "POST",
          body: JSON.stringify({
            group: currentMonitor.group || "Маржа",
            brand: currentMonitor.brand || "Новый донор",
            site_url: siteUrl,
          }),
        });
        newsData = applyNewsPayload(await requestJson("/api/news"));
        selectedNewsSites.set(activeNewsBrandKey, data.monitor.id);
      }
      urlInput.value = "";
      renderNewsMonitors();
      renderNewsModal();
    } catch (error) {
      if (notice) notice.textContent = error.message;
      errorText.textContent = error.message;
    }
    return;
  }

  const saveButton = event.target.closest("[data-action='save-news-monitor']");
  if (saveButton) {
    try {
      await saveNewsMonitor(newsModalContent);
      renderNewsMonitors();
    } catch (error) {
      const notice = newsModalContent.querySelector("[data-role='monitor-notice']");
      if (notice) notice.textContent = error.message;
      errorText.textContent = error.message;
    }
    return;
  }

  const stopButton = event.target.closest("[data-action='stop-news']");
  if (stopButton) {
    try {
      const monitorId = newsModalContent.dataset.monitorId;
      const data = await requestJson(`/api/news/monitors/${monitorId}/stop`, { method: "POST" });
      const index = (newsData.monitors || []).findIndex((monitor) => monitor.id === monitorId);
      if (index >= 0) newsData.monitors[index] = data.monitor;
      renderNewsMonitors();
      renderNewsModal();
    } catch (error) {
      errorText.textContent = error.message;
    }
    return;
  }

  const deleteButton = event.target.closest("[data-action='delete-news-monitor']");
  if (deleteButton) {
    openDeleteSelectedDonorModal();
    return;
  }

  const scanButton = event.target.closest("[data-action='scan-news']");
  if (!scanButton) return;
  try {
    await saveNewsMonitor(newsModalContent);
    const monitorId = newsModalContent.dataset.monitorId;
    const data = await requestJson(`/api/news/monitors/${monitorId}/scan`, { method: "POST" });
    const index = (newsData.monitors || []).findIndex((monitor) => monitor.id === monitorId);
    if (index >= 0) newsData.monitors[index] = data.monitor;
    renderNewsMonitors();
    renderNewsModal();
  } catch (error) {
    errorText.textContent = error.message;
  }
});

startButton.addEventListener("click", async () => {
  const project = activeProject();
  if (!project) return;
  try {
    await saveActiveProject();
    project.state = await requestJson(`/api/projects/${project.id}/start`, {
      method: "POST",
      body: JSON.stringify({
        start_urls: startUrls.value,
        product_url_filters: project.product_url_filters || [],
        product_url_exclusions: project.product_url_exclusions || [],
        extraction_rules: {
          product_card_selector: productCardSelector.value.trim(),
          product_url_selector: productUrlSelector.value.trim(),
          model_selector: modelSelector.value.trim(),
          price_selector: priceSelector.value.trim(),
          model_start_marker: modelStartMarker.value.trim(),
          model_end_marker: modelEndMarker.value.trim(),
          model_replace_rules: modelReplaceRules.value.trim(),
        },
        thread_count: Number(threadCount.value || 4),
        connection_method: connectionMethod.value,
        auto_connection_fallback: autoConnectionFallback.checked,
        persist_profile: persistProfile.checked,
      }),
    });
    renderState(project);
  } catch (error) {
    errorText.textContent = error.message;
  }
});

softPauseButton.addEventListener("click", async () => {
  const project = activeProject();
  if (!project) return;
  const status = project.state?.status;
  try {
    project.state = await requestJson(`/api/projects/${project.id}/${status === "paused" ? "resume" : "soft-pause"}`, {
      method: "POST",
    });
    renderState(project);
  } catch (error) {
    errorText.textContent = error.message;
  }
});

pauseButton.addEventListener("click", async () => {
  const project = activeProject();
  if (!project) return;
  const status = project.state?.status;
  try {
    project.state = await requestJson(`/api/projects/${project.id}/${status === "partial" ? "resume" : "pause"}`, {
      method: "POST",
    });
    renderState(project);
  } catch (error) {
    errorText.textContent = error.message;
  }
});

restartButton.addEventListener("click", async () => {
  const project = activeProject();
  if (!project) return;
  try {
    await saveActiveProject();
    project.state = await requestJson(`/api/projects/${project.id}/restart`, { method: "POST" });
    renderState(project);
  } catch (error) {
    errorText.textContent = error.message;
  }
});

stopButton.addEventListener("click", async () => {
  const project = activeProject();
  if (!project) return;
  try {
    project.state = await requestJson(`/api/projects/${project.id}/stop`, { method: "POST" });
    renderState(project);
  } catch (error) {
    errorText.textContent = error.message;
  }
});

exclusionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const project = activeProject();
  const pattern = exclusionInput.value.trim();
  if (!project || !pattern) return;

  try {
    const data = await requestJson(`/api/projects/${project.id}/exclusions`, {
      method: "POST",
      body: JSON.stringify({ pattern }),
    });
    project.exclusions = data.exclusions || [];
    exclusionInput.value = "";
    renderExclusions(project.exclusions);
  } catch (error) {
    errorText.textContent = error.message;
  }
});

productUrlFilterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const project = activeProject();
  const pattern = productUrlFilterInput.value.trim();
  if (!project || !pattern) return;

  try {
    const data = await requestJson(`/api/projects/${project.id}/product-url-filters`, {
      method: "POST",
      body: JSON.stringify({ pattern }),
    });
    project.product_url_filters = data.product_url_filters || [];
    productUrlFilterInput.value = "";
    renderProductUrlFilters(project.product_url_filters);
  } catch (error) {
    errorText.textContent = error.message;
  }
});

if (productUrlExclusionForm) {
  productUrlExclusionForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const project = activeProject();
    const pattern = productUrlExclusionInput.value.trim();
    if (!project || !pattern) return;

    try {
      const data = await requestJson(`/api/projects/${project.id}/product-url-exclusions`, {
        method: "POST",
        body: JSON.stringify({ pattern }),
      });
      project.product_url_exclusions = data.product_url_exclusions || [];
      productUrlExclusionInput.value = "";
      renderProductUrlExclusions(project.product_url_exclusions);
    } catch (error) {
      errorText.textContent = error.message;
    }
  });
}

downloadButton.addEventListener("click", (event) => {
  if (downloadButton.classList.contains("disabled")) {
    event.preventDefault();
  }
});

refreshLogsButton.addEventListener("click", () => loadLogs(true));

clearLogsButton.addEventListener("click", async () => {
  await requestJson("/api/logs", { method: "DELETE" });
  loadLogs(true);
});

autoCleanup.addEventListener("change", async () => {
  await requestJson("/api/logs/settings", {
    method: "POST",
    body: JSON.stringify({ auto_cleanup: autoCleanup.checked }),
  });
  loadLogs(true);
});

window.setInterval(tickNewsModalTimers, 1000);

function wantsNewsProgress() {
  return activeView === "news";
}

function handleProgressEvent(event) {
  const data = JSON.parse(event.data);
  if (Array.isArray(data.connection_methods)) {
    setConnectionMethods(data.connection_methods);
  }
  if (Array.isArray(data.projects)) {
    projects = applyProjectPayload(data.projects);
    if (!activeProjectId && projects.length) activeProjectId = projects[0].id;
    if (activeView === "projects") {
      renderTabs();
      renderState(activeProject());
    }
  }
  if (activeView === "logs" && data.logs_signature && data.logs_signature !== logsSignature) {
    loadLogs();
  }
  if (data.news) {
    newsData = applyNewsPayload(data.news);
    if (activeView === "news") {
      scheduleNewsListRender();
      if (activeNewsBrandKey && newsMonitorModal && !newsMonitorModal.classList.contains("hidden")) {
        scheduleNewsModalProgressUpdate();
      }
    } else if (activeView === "settings") {
      renderFeedStorage();
    }
  }
}

function configureProgressStream() {
  const includeNews = wantsNewsProgress();
  if (progressEvents && progressIncludesNews === includeNews) return;
  if (progressEvents) {
    progressEvents.close();
    progressEvents = null;
  }
  progressIncludesNews = includeNews;
  const includeProjects = activeView === "projects";
  progressEvents = new EventSource(`/progress?projects=${includeProjects ? "1" : "0"}&news=${includeNews ? "1" : "0"}`);
  progressEvents.addEventListener("progress", handleProgressEvent);
}

async function bootstrapActiveRoute() {
  if (activeView === "projects") {
    await loadProjects();
  } else {
    renderAll();
  }
  configureProgressStream();
}

window.addEventListener("popstate", () => {
  activeView = viewFromPath();
  activeProjectId = idFromEditPath("projects") || activeProjectId;
  pendingNewsMonitorId = idFromEditPath("news") || "";
  configureProgressStream();
  if (activeView === "projects" && !projects.length) {
    loadProjects().catch((error) => { errorText.textContent = error.message; });
  } else {
    renderAll();
  }
});

bootstrapActiveRoute().catch((error) => {
  errorText.textContent = error.message;
});


