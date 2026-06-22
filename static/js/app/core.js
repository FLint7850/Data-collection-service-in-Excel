/* DOM references, shared state and common UI helpers. */
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
const exclusionForm = document.querySelector("#exclusionForm");
const exclusionInput = document.querySelector("#exclusionInput");
const exclusionList = document.querySelector("#exclusionList");
const productUrlFilterForm = document.querySelector("#productUrlFilterForm");
const productUrlFilterInput = document.querySelector("#productUrlFilterInput");
const productUrlFilterList = document.querySelector("#productUrlFilterList");
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
let activeProjectId = null;
const activeViewStorageKey = "excelServiceActiveView";
const allowedActiveViews = new Set(["projects", "news", "import", "settings", "logs"]);

function readStoredActiveView() {
  try {
    const storedView = window.localStorage.getItem(activeViewStorageKey);
    if (storedView === "project") return "projects";
    return allowedActiveViews.has(storedView) ? storedView : "projects";
  } catch {
    return "projects";
  }
}

function setActiveView(view) {
  activeView = allowedActiveViews.has(view) ? view : "projects";
  try {
    window.localStorage.setItem(activeViewStorageKey, activeView);
  } catch {
  }
}

let activeView = readStoredActiveView();
let isHydratingForm = false;
let isHydratingNews = false;
let saveTimer = null;
let newsSaveTimer = null;
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

function applyNewsPayload(data) {
  setConnectionMethods(data?.connection_methods);
  newsData = stampNewsStates(data);
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
      setActiveView("projects");
      activeProjectId = project.id;
      renderAll();
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
  isHydratingForm = true;
  projectName.value = project.name || "";
  startUrls.value = (project.start_urls || []).join("\n");
  threadCount.value = project.thread_count || project.state?.thread_count || 4;
  hydrateConnectionSelect(connectionMethod, project.connection_method);
  autoConnectionFallback.checked = project.auto_connection_fallback !== false;
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

