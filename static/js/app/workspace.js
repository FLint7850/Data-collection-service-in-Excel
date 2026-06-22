/* Main workspace loading, rendering and logs. */
function renderAll() {
  renderTabs();
  const project = activeProject();
  projectView.classList.toggle("hidden", activeView !== "projects");
  newItemsView.classList.toggle("hidden", activeView !== "news");
  fileImportView.classList.toggle("hidden", activeView !== "import");
  settingsView.classList.toggle("hidden", activeView !== "settings");
  logsView.classList.toggle("hidden", activeView !== "logs");
  if (activeView === "projects") {
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
    if (newsData) {
      renderNewsSettings();
      renderFeedStorage();
    } else {
      loadNews().catch((error) => {
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

async function loadProjects() {
  const data = await requestJson("/api/projects");
  setConnectionMethods(data.connection_methods);
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
  const data = await requestJson("/api/logs");
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

