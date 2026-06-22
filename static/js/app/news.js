/* News-monitor rendering and persistence. */
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
    monitors.find((item) => item.id === primaryId) ||
    monitors.find((item) => item.id === selectedId) ||
    monitors[0];
  selectedNewsSites.set(activeNewsBrandKey, monitor.id);
  return monitor;
}

function openNewsModal(brandKey) {
  activeNewsBrandKey = brandKey;
  const monitors = monitorsForBrandKey(brandKey);
  const primaryId = String(monitors[0]?.primary_donor_id || "");
  if (primaryId) {
    selectedNewsSites.set(brandKey, primaryId);
  }
  activeNewsSelectorsOpen = false;
  activeNewsReplaceRulesOpen = false;
  activeNewsBrandNameEditing = false;
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
  activeNewsBrandNameEditing = false;
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
      <label class="field">
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
      <label class="field modal-wide-field">
        <span>Исключение товаров по статусу</span>
        <textarea data-selector="availability_exclusions" rows="3" placeholder="Снят с производства&#10;Нет в наличии">${escapeHtml((monitor.selector_settings?.availability_exclusions || []).join("\n"))}</textarea>
      </label>
      <label class="field">
        <span>Селектор фото</span>
        <input data-selector="photo_selector" type="text" value="${escapeHtml(monitor.selector_settings?.photo_selector || "")}">
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

async function loadNews() {
  newsData = applyNewsPayload(await requestJson("/api/news"));
  renderNews();
}

