/* Settings, own sites, feeds and file-import UI. */
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
  return ["running", "queued", "pausing", "stopping"].includes(status);
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

