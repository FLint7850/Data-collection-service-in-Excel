/* User actions, modal handlers and live progress stream. */
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
  setActiveView("projects");
  renderAll();
});

logsTabButton.addEventListener("click", () => {
  setActiveView("logs");
  renderAll();
});

newItemsTabButton.addEventListener("click", () => {
  setActiveView("news");
  loadNews().catch((error) => {
    errorText.textContent = error.message;
  });
  renderAll();
});

importTabButton.addEventListener("click", () => {
  setActiveView("import");
  renderAll();
});

settingsTabButton.addEventListener("click", () => {
  setActiveView("settings");
  loadNews().catch((error) => {
    errorText.textContent = error.message;
  });
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

const events = new EventSource("/progress");
events.addEventListener("progress", (event) => {
  const data = JSON.parse(event.data);
  if (Array.isArray(data.connection_methods)) {
    setConnectionMethods(data.connection_methods);
  }
  if (Array.isArray(data.projects)) {
    projects = data.projects;
    if (!activeProjectId && projects.length) activeProjectId = projects[0].id;
    if (activeView === "projects") {
      renderTabs();
      renderState(activeProject());
    }
    if (activeView === "logs" && data.logs_signature && data.logs_signature !== logsSignature) {
      loadLogs();
    }
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
});

loadProjects().catch((error) => {
  errorText.textContent = error.message;
});
loadNews().catch(() => {});
