const projectTabs = document.querySelector("#projectTabs");
const addProjectButton = document.querySelector("#addProjectButton");
const newItemsTabButton = document.querySelector("#newItemsTabButton");
const logsTabButton = document.querySelector("#logsTabButton");
const projectView = document.querySelector("#projectView");
const newItemsView = document.querySelector("#newItemsView");
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

const logsList = document.querySelector("#logsList");
const clearLogsButton = document.querySelector("#clearLogsButton");
const refreshLogsButton = document.querySelector("#refreshLogsButton");
const autoCleanup = document.querySelector("#autoCleanup");
const newsGroups = document.querySelector("#newsGroups");
const addNewsMonitorButton = document.querySelector("#addNewsMonitorButton");
const newsFeedUrl = document.querySelector("#newsFeedUrl");
const newsFeedGenerateUrl = document.querySelector("#newsFeedGenerateUrl");
const smtpHost = document.querySelector("#smtpHost");
const smtpPort = document.querySelector("#smtpPort");
const smtpSecurity = document.querySelector("#smtpSecurity");
const smtpUsername = document.querySelector("#smtpUsername");
const smtpSender = document.querySelector("#smtpSender");
const smtpPassword = document.querySelector("#smtpPassword");
const smtpRecipients = document.querySelector("#smtpRecipients");
const saveNewsSettingsButton = document.querySelector("#saveNewsSettingsButton");
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

let projects = [];
let newsData = null;
let activeProjectId = null;
let activeView = "project";
let isHydratingForm = false;
let isHydratingNews = false;
let saveTimer = null;
let newsSaveTimer = null;
const monitorSaveTimers = new Map();
const selectedNewsSites = new Map();
let activeNewsBrandKey = null;
let activeNewsSelectorsOpen = false;
let activeNewsReplaceRulesOpen = false;
let pendingDeleteProjectId = null;
let pendingDeleteNewsMonitorId = null;
let pendingDeleteNewsMonitorMode = "brand";
let pendingDeleteNewsBrandKey = null;
let pendingDeleteDonorBrandKey = null;
let tabsRenderKey = "";

const statusLabels = {
  idle: "ожидание",
  running: "выполняется",
  paused: "пауза",
  completed: "завершено",
  error: "ошибка",
  stopping: "останавливается",
  stopped: "остановлено",
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
    tab.className = `project-tab ${project.id === activeProjectId && activeView === "project" ? "active" : ""}`;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "project-tab-button";
    button.textContent = project.name;
    button.addEventListener("click", () => {
      activeView = "project";
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
  newItemsTabButton.classList.toggle("active", activeView === "news");
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
    activeView = "project";
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
    const data = await requestJson(`/api/news/monitors/${id}`, { method: "DELETE" });
    if (Array.isArray(data.monitors)) latestMonitors = data.monitors;
  }
  if (mode === "donor") {
    newsData = await requestJson("/api/news");
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
  connectionMethod.value = project.connection_method || "requests";
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
  statusText.textContent = statusLabels[status] || status;
  statusDot.className = `status-dot status-${status}`;
  progressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  percentText.textContent = `${percent}%`;
  currentUrl.textContent = state.currenturl || "Текущий URL появится после запуска.";
  processedCount.textContent = state.totalprocessed || 0;
  foundCount.textContent = state.found_products || 0;
  skippedCount.textContent = state.skipped || 0;
  elapsedTime.textContent = formatDuration(state.elapsed_seconds || 0);
  etaTime.textContent = state.eta_seconds === null || state.eta_seconds === undefined ? "—" : formatDuration(state.eta_seconds);
  errorText.textContent = state.error || "";
  fileName.textContent = state.filename || "";

  const ready = Boolean(state.download_ready);
  downloadButton.classList.toggle("disabled", !ready);
  downloadButton.setAttribute("aria-disabled", ready ? "false" : "true");
  downloadButton.href = ready && project ? `/api/projects/${project.id}/download` : "#";
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

function renderNewsSettings() {
  if (!newsData) return;
  isHydratingNews = true;
  const smtp = newsData.smtp || {};
  newsFeedUrl.value = (newsData.feed_urls || (newsData.feed_url ? [newsData.feed_url] : [])).join("\n");
  newsFeedGenerateUrl.value = (newsData.feed_generate_urls || (newsData.feed_generate_url ? [newsData.feed_generate_url] : [])).join("\n");
  smtpHost.value = smtp.host || "smtp.yandex.ru";
  smtpPort.value = smtp.port || 465;
  smtpSecurity.value = smtp.security || "ssl";
  smtpUsername.value = smtp.username || "";
  smtpSender.value = smtp.sender || "";
  smtpPassword.value = "";
  smtpPassword.placeholder = smtp.password_set ? "Пароль уже задан" : "Введите пароль приложения";
  smtpRecipients.value = (smtp.recipients || []).join("\n");
  isHydratingNews = false;
}

function connectionOptionsHtml(current) {
  const options = [
    ["requests", "Requests"],
    ["botasaurus-request", "Botasaurus Request"],
    ["botasaurus-browser", "Botasaurus Browser Google"],
    ["botasaurus-browser-direct", "Botasaurus Browser Direct"],
    ["botasaurus-visible", "Botasaurus Visible Browser"],
    ["crawl4ai", "Crawl4AI"],
    ["firecrawl", "Firecrawl"],
    ["scrapy", "Scrapy"],
    ["crawlee", "Crawlee"],
  ];
  return options
    .map(([value, label]) => `<option value="${value}" ${value === current ? "selected" : ""}>${label}</option>`)
    .join("");
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

function newsStatusClass(status) {
  if (status === "running" || status === "queued") return "status-running";
  if (status === "completed") return "status-completed";
  if (status === "stopping" || status === "stopped" || status === "pausing" || status === "partial") return "status-paused";
  if (status === "error") return "status-error";
  return "status-idle";
}

function newsStatusText(status) {
  if (status === "running" || status === "queued") return "в работе";
  if (status === "completed") return "завершено";
  if (status === "stopping") return "останавливается";
  if (status === "stopped") return "остановлено";
  if (status === "pausing") return "приостанавливается";
  if (status === "partial") return "приостановлено";
  if (status === "error") return "ошибка";
  return "ожидание";
}

function aggregateNewsStatus(states) {
  if (states.some((state) => state.status === "error")) return "error";
  if (states.some((state) => ["running", "queued", "pausing", "stopping"].includes(state.status))) return "running";
  if (states.some((state) => state.status === "partial" || state.status === "stopped")) return "partial";
  if (states.some((state) => state.status === "completed")) return "completed";
  return "idle";
}

function clampPercent(value) {
  const percent = Number(value || 0);
  if (!Number.isFinite(percent)) return 0;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function formatFileSize(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

function renderFeedStorage() {
  if (!newsFeedsStorage || !newsData) return;
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
      <span class="local-feeds-title">Локальные фиды</span>
      ${Object.entries(groups)
        .map(([source, group]) => `
          <div class="local-feed-source">
            <strong>${escapeHtml(group.label)}</strong>
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

function renderNewsMonitors() {
  if (!newsData || !newsGroups) return;
  const grouped = groupNewsMonitors();
  newsGroups.innerHTML = "";
  ["Маржа", "Немаржа"].forEach((group) => {
    const brands = grouped[group] || {};
    const section = document.createElement("section");
    section.className = "panel news-group-panel";
    section.innerHTML = `<h2>${escapeHtml(group)}</h2>`;
    const list = document.createElement("div");
    list.className = "news-brand-grid";
    Object.entries(brands).forEach(([brand, brandMonitors]) => {
      const brandKey = `${group}::${brand}`;
      const selectedId = selectedNewsSites.get(brandKey);
      const monitor = brandMonitors.find((item) => item.id === selectedId) || brandMonitors[0];
      selectedNewsSites.set(brandKey, monitor.id);
      const states = brandMonitors.map((item) => item.state || {});
      const status = aggregateNewsStatus(states);
      const activeState = states.find((state) => state.status === "running" || state.status === "queued") || states[0] || {};
      const percent = clampPercent(activeState.percent || (status === "completed" ? 100 : 0));
      const newCount = states.reduce((sum, state) => sum + Number(state.new_count || 0), 0);
      const lastScan = states.map((state) => state.last_scan_at || "").filter(Boolean).sort().pop() || "—";
      const tile = document.createElement("button");
      tile.className = "news-brand-tile";
      tile.type = "button";
      tile.dataset.action = "open-news-brand";
      tile.dataset.brandKey = brandKey;
      tile.innerHTML = `
        <span class="news-tile-remove-wrap">
          <button class="news-tile-remove" data-action="delete-news-monitor-card" data-monitor-id="${monitor.id}" data-brand-key="${escapeHtml(brandKey)}" type="button" aria-label="Удалить">×</button>
        </span>
        <span class="brand-name">${escapeHtml(brand)}</span>
        <span class="brand-meta">${brandMonitors.length} сайт${brandMonitors.length > 1 ? "а" : ""}</span>
        <span class="brand-sites">${brandMonitors.map((item) => escapeHtml(item.site_url || (item.start_urls || [])[0] || "")).join("<br>")}</span>
        <span class="brand-row">
          <span class="news-status ${newsStatusClass(status)}">${escapeHtml(newsStatusText(status))}</span>
          <span>Новинок: <strong>${newCount}</strong></span>
        </span>
        <span class="mini-progress-track"><span class="mini-progress-fill" style="width: ${percent}%"></span></span>
        <span class="brand-counters">
          Стр: ${Number(activeState.processed || 0)} · Тов: ${Number(activeState.found_products || 0)} · Сравнено: ${Number(activeState.compared_products || 0)}
        </span>
        <span class="brand-stage">${escapeHtml(activeState.stage || "")}</span>
        ${activeState.error ? `<span class="brand-error">${escapeHtml(activeState.error)}</span>` : ""}
        <span class="brand-last">Последнее: ${escapeHtml(lastScan)}</span>
      `;
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
  const selectedId = selectedNewsSites.get(activeNewsBrandKey);
  const monitor = monitors.find((item) => item.id === selectedId) || monitors[0];
  selectedNewsSites.set(activeNewsBrandKey, monitor.id);
  return monitor;
}

function openNewsModal(brandKey) {
  activeNewsBrandKey = brandKey;
  activeNewsSelectorsOpen = false;
  activeNewsReplaceRulesOpen = false;
  renderNewsModal();
  newsMonitorModal.classList.remove("hidden");
  newsMonitorModal.setAttribute("aria-hidden", "false");
}

function closeNewsModal() {
  newsMonitorModal.classList.add("hidden");
  newsMonitorModal.setAttribute("aria-hidden", "true");
  activeNewsBrandKey = null;
  activeNewsSelectorsOpen = false;
  activeNewsReplaceRulesOpen = false;
}

function updateNewsModalProgress() {
  const monitor = activeNewsMonitor();
  if (!monitor || newsModalContent.dataset.monitorId !== monitor.id) return;
  const state = monitor.state || {};
  const percent = clampPercent(state.percent || (state.status === "completed" ? 100 : 0));
  const statusNode = newsMonitorModal.querySelector("[data-role='news-status']");
  if (statusNode) {
    const nextClass = `news-status ${newsStatusClass(state.status)}`;
    if (statusNode.className !== nextClass) statusNode.className = nextClass;
    const statusTextNode = statusNode.querySelector("[data-role='status-text']");
    if (statusTextNode) statusTextNode.textContent = newsStatusText(state.status);
  }

  const summaryValues = {
    lastScan: state.last_scan_at || "—",
    newCount: Number(state.new_count || 0),
    csv: state.last_csv || "—",
    stage: state.stage || "—",
    processed: Number(state.processed || 0),
    found: Number(state.found_products || 0),
    compared: Number(state.compared_products || 0),
    candidates: Number(state.candidate_products || state.found_products || 0),
    elapsed: formatDuration(state.elapsed_seconds || 0),
  };
  Object.entries(summaryValues).forEach(([key, value]) => {
    const node = newsModalContent.querySelector(`[data-summary='${key}']`);
    if (node) node.textContent = value;
  });

  const fill = newsModalContent.querySelector("[data-role='modal-progress-fill']");
  if (fill) fill.style.width = `${percent}%`;
  const percentNode = newsModalContent.querySelector("[data-role='modal-percent']");
  if (percentNode) percentNode.textContent = `${percent}%`;
  const currentUrlNode = newsModalContent.querySelector("[data-role='modal-current-url']");
  if (currentUrlNode) currentUrlNode.textContent = state.currenturl || "";

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
    const ready = Boolean(state.last_csv);
    downloadLink.classList.toggle("disabled", !ready);
    downloadLink.setAttribute("aria-disabled", ready ? "false" : "true");
    downloadLink.href = ready ? `/api/news/monitors/${monitor.id}/download` : "#";
  }
  const errorNode = newsModalContent.querySelector("[data-role='modal-error']");
  if (errorNode) errorNode.textContent = state.error || "";
}

function renderNewsModal() {
  const monitor = activeNewsMonitor();
  const monitors = monitorsForBrandKey(activeNewsBrandKey);
  if (!monitor) return;

  const state = monitor.state || {};
  const disabled = ["running", "queued", "stopping"].includes(state.status);
  const percent = clampPercent(state.percent || (state.status === "completed" ? 100 : 0));
  const brand = monitor.brand || "Донор";
  const site = monitor.site_url || (monitor.start_urls || [])[0] || "";
  newsModalTitle.textContent = brand;
  newsModalSubtitle.textContent = site;
  newsModalTitleActions.innerHTML = `
  <span class="news-status ${newsStatusClass(state.status)}" data-role="news-status">
    <span data-role="status-text">${escapeHtml(newsStatusText(state.status))}</span>
  </span>
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
  <button class="button warning compact-button" data-action="pause-news" type="button" ${["running", "queued"].includes(state.status) ? "" : "disabled"}>Приостановить</button>
  <button class="button danger compact-button" data-action="stop-news" type="button" ${["running", "queued", "pausing", "stopping"].includes(state.status) ? "" : "disabled"}>Стоп</button>
  <button class="button secondary compact-button" data-action="resume-news" type="button" ${state.status === "partial" ? "" : "disabled"}>Продолжить</button>
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
              return `<option value="${item.id}" ${item.id === monitor.id ? "selected" : ""}>${escapeHtml(itemSite)}</option>`;
            })
            .join("")}
        </select>
        <div class="add-modal-donor-row">
          <input data-role="new-site-donor-url" type="url" placeholder="https://site.ru/">
          <button class="button secondary compact-button add-modal-donor-button" data-action="add-news-site-donor" type="button">Добавить</button>
        </div>
      </label>
      <button class="button danger compact-button" data-action="delete-news-monitor" type="button" ${monitors.length ? "" : "disabled"}>Удалить донор</button>
    </div>

    <div class="modal-summary-row">
      <span>Последнее сканирование: <span data-summary="lastScan">${escapeHtml(state.last_scan_at || "—")}</span></span>
      <span>Новинок: <strong data-summary="newCount">${Number(state.new_count || 0)}</strong></span>
      <span>CSV: <span data-summary="csv">${escapeHtml(state.last_csv || "—")}</span></span>
      <span>Этап: <span data-summary="stage">${escapeHtml(state.stage || "—")}</span></span>
      <span>Ссылок/страниц: <strong data-summary="processed">${Number(state.processed || 0)}</strong></span>
      <span>Товаров найдено: <strong data-summary="found">${Number(state.found_products || 0)}</strong></span>
      <span>Сравнено: <strong data-summary="compared">${Number(state.compared_products || 0)}</strong> / <span data-summary="candidates">${Number(state.candidate_products || state.found_products || 0)}</span></span>
      <span>Время: <span data-summary="elapsed">${formatDuration(state.elapsed_seconds || 0)}</span></span>
    </div>
    <div class="news-progress-block">
      <div class="progress-track"><div class="progress-fill" data-role="modal-progress-fill" style="width: ${percent}%"></div></div>
      <div class="percent-row">
        <span data-role="modal-percent">${percent}%</span>
        <span data-role="modal-current-url">${escapeHtml(state.currenturl || "")}</span>
      </div>
    </div>

    <div class="modal-form-grid">
      <label class="field">
        <span>Группа</span>
        <input data-field="group" type="text" value="${escapeHtml(monitor.group || "")}">
      </label>
      <label class="field">
        <span>Название бренда</span>
        <input data-field="brand" type="text" value="${escapeHtml(monitor.brand || "")}">
      </label>
      <label class="field">
        <span>Основной сайт</span>
        <input data-field="site_url" type="text" value="${escapeHtml(monitor.site_url || "")}">
      </label>
      <label class="field modal-wide-field">
        <span>Стартовые URL</span>
        <textarea data-field="start_urls" rows="2">${escapeHtml((monitor.start_urls || []).join("\n"))}</textarea>
      </label>
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
    </div>

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
    </div>

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

    <div class="modal-actions">
      <button class="button primary" data-action="save-news-monitor" type="button">Сохранить изменения</button>
      <button class="button secondary" data-action="scan-news" type="button" ${disabled ? "disabled" : ""}>Сканировать наличие новинок</button>
      <a class="button download ${state.last_csv ? "" : "disabled"}" data-role="modal-csv-download" href="${state.last_csv ? `/api/news/monitors/${monitor.id}/download` : "#"}" aria-disabled="${state.last_csv ? "false" : "true"}">Скачать CSV</a>
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
    payload.selector_settings[input.dataset.selector] = input.value.trim();
  });
  return payload;
}

async function saveNewsSettings() {
  if (isHydratingNews || !newsData) return;
  if (newsSettingsNotice) newsSettingsNotice.textContent = "Сохраняю...";
  const payload = {
    feed_urls: newsFeedUrl.value.trim(),
    feed_generate_urls: newsFeedGenerateUrl.value.trim(),
    smtp: {
      host: smtpHost.value.trim(),
      port: Number(smtpPort.value || 465),
      security: smtpSecurity.value,
      username: smtpUsername.value.trim(),
      sender: smtpSender.value.trim(),
      password: smtpPassword.value.trim(),
      recipients: smtpRecipients.value,
    },
  };
  newsData = await requestJson("/api/news/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  smtpPassword.value = "";
  renderNewsSettings();
  if (newsSettingsNotice) {
    newsSettingsNotice.textContent = "Настройки сохранены";
    window.setTimeout(() => {
      newsSettingsNotice.textContent = "";
    }, 2500);
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

function scheduleSaveMonitor(card) {
  const monitorId = card.dataset.monitorId;
  window.clearTimeout(monitorSaveTimers.get(monitorId));
  monitorSaveTimers.set(
    monitorId,
    window.setTimeout(async () => {
      try {
        const data = await requestJson(`/api/news/monitors/${monitorId}`, {
          method: "PATCH",
          body: JSON.stringify(collectMonitorPayload(card)),
        });
        const index = (newsData.monitors || []).findIndex((monitor) => monitor.id === monitorId);
        if (index >= 0) newsData.monitors[index] = data.monitor;
      } catch (error) {
        errorText.textContent = error.message;
      }
    }, 500),
  );
}

async function saveNewsMonitor(root) {
  const monitorId = root.dataset.monitorId;
  const notice = root.querySelector("[data-role='monitor-notice']");
  if (notice) notice.textContent = "Сохраняю...";
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
}

async function loadNews() {
  newsData = await requestJson("/api/news");
  renderNews();
}

function renderAll() {
  renderTabs();
  const project = activeProject();
  projectView.classList.toggle("hidden", activeView !== "project");
  newItemsView.classList.toggle("hidden", activeView !== "news");
  logsView.classList.toggle("hidden", activeView !== "logs");
  if (activeView === "project") {
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
  } else {
    loadLogs();
  }
}

async function loadProjects() {
  const data = await requestJson("/api/projects");
  projects = data.projects || [];
  if (!activeProjectId && projects.length) {
    activeProjectId = projects[0].id;
  }
  if (!projects.some((project) => project.id === activeProjectId) && projects.length) {
    activeProjectId = projects[0].id;
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
  };
  const data = await requestJson(`/api/projects/${project.id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  Object.assign(project, data.project);
  renderTabs();
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

async function loadLogs() {
  const data = await requestJson("/api/logs");
  autoCleanup.checked = Boolean(data.auto_cleanup);
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
  activeView = "project";
  renderAll();
});

logsTabButton.addEventListener("click", () => {
  activeView = "logs";
  renderAll();
});

newItemsTabButton.addEventListener("click", () => {
  activeView = "news";
  loadNews().catch((error) => {
    errorText.textContent = error.message;
  });
  renderAll();
});

projectName.addEventListener("input", scheduleSaveActiveProject);
startUrls.addEventListener("input", scheduleSaveActiveProject);
threadCount.addEventListener("input", scheduleSaveActiveProject);
threadCount.addEventListener("change", saveActiveProject);
connectionMethod.addEventListener("change", saveActiveProject);
autoConnectionFallback.addEventListener("change", saveActiveProject);
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
  newsFeedUrl,
  newsFeedGenerateUrl,
  smtpHost,
  smtpPort,
  smtpSecurity,
  smtpUsername,
  smtpSender,
  smtpPassword,
  smtpRecipients,
].forEach((input) => {
  input.addEventListener("input", () => {
    if (newsSettingsNotice) newsSettingsNotice.textContent = "";
  });
});

saveNewsSettingsButton.addEventListener("click", () => {
  saveNewsSettings().catch((error) => {
    if (newsSettingsNotice) newsSettingsNotice.textContent = error.message;
    errorText.textContent = error.message;
  });
});

addNewsMonitorButton.addEventListener("click", async () => {
  try {
    const data = await requestJson("/api/news/monitors", {
      method: "POST",
      body: JSON.stringify({ brand: "Новый донор", group: "Маржа", start_urls: "https://example.com/" }),
    });
    if (!newsData) newsData = await requestJson("/api/news");
    newsData.monitors.push(data.monitor);
    renderNewsMonitors();
  } catch (error) {
    errorText.textContent = error.message;
  }
});

newsGroups.addEventListener("click", (event) => {
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

newsGroups.addEventListener("click", async (event) => {
  return;
  const toggleButton = event.target.closest("[data-action='toggle-news-settings']");
  if (toggleButton) {
    const card = toggleButton.closest(".news-monitor-card");
    if (!card) return;
    const grid = card.querySelector(".news-monitor-grid");
    const collapsed = !card.classList.contains("collapsed");
    card.classList.toggle("collapsed", collapsed);
    grid?.classList.toggle("hidden", collapsed);
    toggleButton.textContent = collapsed ? "Настройки" : "Свернуть";
    return;
  }

  const saveButton = event.target.closest("[data-action='save-news-monitor']");
  if (saveButton) {
    const card = saveButton.closest(".news-monitor-card");
    if (!card) return;
    try {
      await saveNewsMonitor(card);
    } catch (error) {
      const notice = card.querySelector("[data-role='monitor-notice']");
      if (notice) notice.textContent = error.message;
      errorText.textContent = error.message;
    }
    return;
  }

  const button = event.target.closest("[data-action='scan-news']");
  if (!button) return;
  const card = button.closest(".news-monitor-card");
  if (!card) return;
  try {
    await saveNewsMonitor(card);
    const data = await requestJson(`/api/news/monitors/${card.dataset.monitorId}/scan`, { method: "POST" });
    const index = (newsData.monitors || []).findIndex((monitor) => monitor.id === card.dataset.monitorId);
    if (index >= 0) newsData.monitors[index] = data.monitor;
    renderNewsMonitors();
  } catch (error) {
    errorText.textContent = error.message;
  }
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

newsModalContent.addEventListener("change", (event) => {
  const select = event.target.closest("[data-action='modal-select-news-site']");
  if (!select) return;
  selectedNewsSites.set(activeNewsBrandKey, select.value);
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
    updateNewsModalProgress();
  } catch (error) {
    errorText.textContent = error.message;
  }
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
    try {
      const currentMonitor = activeNewsMonitor();
      if (!currentMonitor) return;
      const urlInput = newsModalContent.querySelector("[data-role='new-site-donor-url']");
      const siteUrl = urlInput?.value.trim() || "";
      if (!siteUrl) {
        errorText.textContent = "Укажите сайт-донора.";
        urlInput?.focus();
        return;
      }
      await saveNewsMonitor(newsModalContent);
      const data = await requestJson("/api/news/monitors", {
        method: "POST",
        body: JSON.stringify({
          group: currentMonitor.group || "Маржа",
          brand: currentMonitor.brand || "Новый донор",
          site_url: siteUrl,
          start_urls: siteUrl,
        }),
      });
      if (!newsData) newsData = await requestJson("/api/news");
      newsData.monitors.push(data.monitor);
      selectedNewsSites.set(activeNewsBrandKey, data.monitor.id);
      renderNewsMonitors();
      renderNewsModal();
    } catch (error) {
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

downloadButton.addEventListener("click", (event) => {
  if (downloadButton.classList.contains("disabled")) {
    event.preventDefault();
  }
});

refreshLogsButton.addEventListener("click", loadLogs);

clearLogsButton.addEventListener("click", async () => {
  await requestJson("/api/logs", { method: "DELETE" });
  loadLogs();
});

autoCleanup.addEventListener("change", async () => {
  await requestJson("/api/logs/settings", {
    method: "POST",
    body: JSON.stringify({ auto_cleanup: autoCleanup.checked }),
  });
  loadLogs();
});

const events = new EventSource("/progress");
events.addEventListener("progress", (event) => {
  const data = JSON.parse(event.data);
  if (Array.isArray(data.projects)) {
    projects = data.projects;
    if (!activeProjectId && projects.length) activeProjectId = projects[0].id;
    if (activeView === "project") {
      renderTabs();
      renderState(activeProject());
    }
    if (activeView === "logs") {
      loadLogs();
    }
  }
  if (data.news) {
    newsData = data.news;
    if (activeView === "news") {
      renderFeedStorage();
      renderNewsMonitors();
      if (activeNewsBrandKey && newsMonitorModal && !newsMonitorModal.classList.contains("hidden")) {
        updateNewsModalProgress();
      }
    }
  }
});

loadProjects().catch((error) => {
  errorText.textContent = error.message;
});
loadNews().catch(() => {});
