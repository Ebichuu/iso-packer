(function () {
  const ROOT_LABELS = {
    watch: "本机监控",
    output: "本机输出",
    cd2: "网盘挂载",
  };

  const ACTION_LABELS = {
    copy: "复制",
    move: "移动",
    delete: "删除",
  };

  const state = {
    root: "watch",
    path: "/",
    parent: null,
    entries: [],
    query: "",
    filter: "all",
    rootPath: "",
    selected: new Set(),
    operationTimer: null,
  };

  function helper() {
    return window.IsoPacker;
  }

  function rootPathFor(rootName = state.root) {
    return String((helper().qs(`[data-root="${rootName}"]`) || {}).dataset?.rootPath || "");
  }

  function rootLabel(rootName = state.root) {
    return ROOT_LABELS[rootName] || rootName;
  }

  function isDiscHint(entry) {
    const name = String((entry && entry.name) || "").toUpperCase();
    const path = String((entry && entry.path) || "").toUpperCase();
    return entry && entry.type === "dir" && (
      name === "BDMV" ||
      name === "CERTIFICATE" ||
      path.includes("/BDMV") ||
      path.includes("\\BDMV") ||
      path.includes("UHD") ||
      path.includes("BLURAY") ||
      path.includes("BLU-RAY")
    );
  }

  function entryGroup(entry) {
    if (isDiscHint(entry)) return "disc";
    return entry && entry.type === "dir" ? "dir" : "file";
  }

  function filteredEntries() {
    const query = state.query.trim().toLowerCase();
    return state.entries.filter((entry) => {
      const group = entryGroup(entry);
      if (state.filter !== "all" && group !== state.filter) return false;
      if (!query) return true;
      return [entry.name, entry.path, entry.type].some((value) => String(value || "").toLowerCase().includes(query));
    });
  }

  function selectedEntries() {
    return state.entries.filter((entry) => state.selected.has(entry.path));
  }

  function renderBreadcrumb(payload) {
    const root = helper().qs("#file-breadcrumb");
    if (!root) return;
    helper().clearNode(root);

    const rootButton = document.createElement("button");
    rootButton.type = "button";
    rootButton.dataset.breadcrumbPath = "/";
    rootButton.textContent = rootLabel(payload.root || state.root);
    root.appendChild(rootButton);

    const rootPath = state.rootPath || rootPathFor();
    const currentPath = String(state.path || "");
    const normalizedRoot = rootPath.replace(/\\/g, "/").replace(/\/+$/, "");
    const normalizedCurrent = currentPath.replace(/\\/g, "/");
    const relative = normalizedRoot && normalizedCurrent.startsWith(normalizedRoot)
      ? normalizedCurrent.slice(normalizedRoot.length).replace(/^\/+/, "")
      : "";
    if (!relative) return;

    let builtPath = rootPath;
    relative.split("/").filter(Boolean).forEach((part) => {
      const separator = document.createElement("span");
      separator.className = "breadcrumb-separator";
      separator.textContent = "/";
      root.appendChild(separator);

      builtPath = `${builtPath.replace(/[\\/]+$/, "")}/${part}`;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.breadcrumbPath = builtPath;
      button.textContent = part;
      root.appendChild(button);
    });
  }

  function renderSummary() {
    const dirs = state.entries.filter((entry) => entry.type === "dir").length;
    const discs = state.entries.filter(isDiscHint).length;
    helper().setText(helper().qs("#file-dir-count"), dirs);
    helper().setText(helper().qs("#file-disc-count"), discs);
    helper().setText(helper().qs("#file-current-root"), state.rootPath ? `${rootLabel()} · ${state.rootPath}` : rootLabel());
    helper().setText(helper().qs("#file-entry-count"), `${filteredEntries().length} / ${state.entries.length} 项`);
    helper().setText(helper().qs("#file-selected-count"), `${state.selected.size} 项已选`);
  }

  function renderOperationBar() {
    const bar = helper().qs("#file-operation-bar");
    if (!bar) return;
    const hasSelection = state.selected.size > 0;
    bar.classList.toggle("hidden", !hasSelection);
    const inlineCount = helper().qs("#file-selected-count-inline");
    if (inlineCount) {
      inlineCount.textContent = `${state.selected.size} 项已选`;
      inlineCount.classList.toggle("hidden", !hasSelection);
    }
    helper().qsa("[data-file-action]", bar).forEach((button) => {
      button.disabled = !hasSelection;
    });
  }

  function syncSelectAll(entries) {
    const selectAll = helper().qs("#file-select-all");
    if (!selectAll) return;
    const selectable = entries.filter((entry) => entry.path);
    const selectedVisible = selectable.filter((entry) => state.selected.has(entry.path)).length;
    selectAll.checked = selectable.length > 0 && selectedVisible === selectable.length;
    selectAll.indeterminate = selectedVisible > 0 && selectedVisible < selectable.length;
  }

  function renderEntryList() {
    const list = helper().qs("#file-browser-list");
    if (!list) return;
    helper().clearNode(list);
    const entries = filteredEntries();
    renderSummary();
    renderOperationBar();
    syncSelectAll(entries);
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state slim";
      empty.textContent = state.entries.length ? "当前筛选条件下没有内容。" : "当前目录为空，或没有可读取的内容。";
      list.appendChild(empty);
      return;
    }
    entries.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "file-row";
      row.dataset.kind = entryGroup(entry);
      row.dataset.path = entry.path || "";
      row.dataset.selected = state.selected.has(entry.path) ? "true" : "false";
      if (entry.type === "dir" && entry.path) {
        row.dataset.openable = "true";
        row.dataset.rowOpenPath = entry.path;
      }

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "file-select";
      checkbox.dataset.selectPath = entry.path || "";
      checkbox.checked = state.selected.has(entry.path);
      checkbox.setAttribute("aria-label", `选择 ${entry.name || "文件"}`);

      const kind = document.createElement("span");
      kind.className = "file-kind";
      kind.textContent = isDiscHint(entry) ? "DISC" : (entry.type === "dir" ? "DIR" : "FILE");

      const main = document.createElement("div");
      main.className = "file-main";
      if (entry.type === "dir" && entry.path) {
        main.dataset.openPath = entry.path;
        main.tabIndex = 0;
        main.setAttribute("role", "link");
        main.setAttribute("aria-label", `进入 ${entry.name || "目录"}`);
      }
      const name = document.createElement("strong");
      name.className = "file-name";
      name.textContent = entry.name || "-";
      const meta = document.createElement("div");
      meta.className = "file-meta";
      const path = document.createElement("span");
      path.textContent = entry.path || "";
      meta.append(path);
      main.append(name, meta);

      const mtime = document.createElement("span");
      mtime.className = "file-time";
      mtime.textContent = entry.mtime || "-";

      const attr = document.createElement("div");
      attr.className = "file-attrs";
      attr.appendChild(kind);

      const size = document.createElement("span");
      size.className = "file-size";
      size.textContent = entry.type === "dir" ? "-" : helper().formatBytes(entry.size);

      const actions = document.createElement("div");
      actions.className = "file-row-actions";
      const props = document.createElement("button");
      props.type = "button";
      props.dataset.propsPath = entry.path || "";
      props.textContent = "属性";
      actions.appendChild(props);

      row.append(checkbox, main, mtime, attr, size, actions);
      list.appendChild(row);
    });
  }

  function renderEntries(payload) {
    state.path = payload.path || "/";
    state.parent = payload.parent || null;
    state.rootPath = payload.root_path || rootPathFor();
    state.entries = Array.isArray(payload.entries) ? payload.entries : [];
    state.selected.clear();
    renderBreadcrumb(payload);
    renderEntryList();
  }

  async function loadDirectory(path) {
    const targetPath = path || state.path || "/";
    const list = helper().qs("#file-browser-list");
    if (list) {
      list.replaceChildren(Object.assign(document.createElement("div"), {
        className: "empty-state slim",
        textContent: "正在读取目录。",
      }));
    }
    try {
      const payload = await helper().fetchJson(`/api/browse?root=${encodeURIComponent(state.root)}&path=${encodeURIComponent(targetPath)}`);
      renderEntries(payload);
    } catch (error) {
      if (list) {
        list.replaceChildren(Object.assign(document.createElement("div"), {
          className: "empty-state slim",
          textContent: error.message || "目录读取失败。",
        }));
      }
    }
  }

  function switchRoot(root) {
    state.root = root;
    state.path = "/";
    state.parent = null;
    state.entries = [];
    state.query = "";
    state.filter = "all";
    state.rootPath = rootPathFor(root);
    state.selected.clear();
    const search = helper().qs("#file-search");
    if (search) search.value = "";
    helper().qsa("[data-file-filter]").forEach((button) => {
      button.dataset.active = button.dataset.fileFilter === "all" ? "true" : "false";
    });
    helper().qsa("[data-root]").forEach((button) => {
      button.dataset.active = button.dataset.root === root ? "true" : "false";
    });
    loadDirectory("/");
  }

  function toggleSelected(path, checked) {
    if (!path) return;
    if (checked) state.selected.add(path);
    else state.selected.delete(path);
    renderEntryList();
  }

  function toggleAllVisible(checked) {
    filteredEntries().forEach((entry) => {
      if (entry.path) {
        if (checked) state.selected.add(entry.path);
        else state.selected.delete(entry.path);
      }
    });
    renderEntryList();
  }

  function openProperties(path) {
    const entry = state.entries.find((item) => item.path === path);
    if (!entry) return;
    const panel = helper().qs("#file-properties-panel");
    const body = helper().qs("#file-properties-body");
    if (!panel || !body) return;
    body.innerHTML = "";
    [
      ["名称", entry.name || "-"],
      ["路径", entry.path || "-"],
      ["类型", entry.type === "dir" ? "目录" : "文件"],
      ["属性", isDiscHint(entry) ? "原盘结构" : (entry.type === "dir" ? "普通目录" : "文件")],
      ["大小", entry.type === "dir" ? "-" : helper().formatBytes(entry.size)],
      ["修改时间", entry.mtime || "-"],
      ["可读取", entry.readable ? "是" : "否"],
    ].forEach(([label, value]) => {
      const row = document.createElement("div");
      row.className = "file-prop-row";
      row.innerHTML = `<span>${label}</span><strong></strong>`;
      row.querySelector("strong").textContent = value;
      body.appendChild(row);
    });
    panel.classList.remove("hidden");
  }

  function closeProperties() {
    helper().qs("#file-properties-panel")?.classList.add("hidden");
  }

  function setOperationStatus(message, isError = false) {
    const node = helper().qs("#file-operation-status");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("text-red-600", Boolean(isError));
    node.classList.toggle("text-zinc-500", !isError);
  }

  async function pollOperation(taskId) {
    window.clearTimeout(state.operationTimer);
    try {
      const payload = await helper().fetchJson(`/api/file-actions/${encodeURIComponent(taskId)}`);
      const task = payload.task || {};
      const total = Number(task.total || 0);
      const done = Number(task.done || 0);
      setOperationStatus(`${ACTION_LABELS[task.action] || "操作"}中：${done}/${total} · ${task.message || ""}`, task.status === "failed");
      if (["done", "partial", "failed"].includes(task.status)) {
        helper().notify(task.message || "文件操作完成", task.status === "failed");
        loadDirectory(state.path || "/");
        return;
      }
      state.operationTimer = window.setTimeout(() => pollOperation(taskId), 1500);
    } catch (error) {
      setOperationStatus(error.message || "操作状态读取失败", true);
    }
  }

  async function submitFileAction(action, destination) {
    const entries = selectedEntries();
    if (!entries.length) {
      helper().notify("请先选择文件或目录", true);
      return;
    }
    const payload = {
      action,
      root: state.root,
      paths: entries.map((entry) => entry.path),
    };
    if (action === "copy" || action === "move") {
      payload.destination = destination;
      if (destination === "custom") {
        const custom = helper().qs("#file-custom-destination")?.value?.trim() || "";
        if (!custom) {
          helper().notify("请先填写其他目录路径", true);
          return;
        }
        payload.destination_path = custom;
      }
    }
    if (action === "move") {
      payload.confirm = "MOVE";
    }
    if (action === "delete") {
      payload.confirm = "DELETE";
    }
    setOperationStatus("正在提交后台任务。");
    try {
      const response = await helper().fetchJson("/api/file-actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      helper().notify("文件操作已开始");
      pollOperation(response.task_id);
    } catch (error) {
      setOperationStatus(error.message || "文件操作提交失败", true);
      helper().notify(error.message || "文件操作提交失败", true);
    }
  }

  function bindEvents() {
    helper().qs(".root-switcher")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-root]");
      if (button) switchRoot(button.dataset.root);
    });
    helper().qs("#file-browser-list")?.addEventListener("click", (event) => {
      const checkbox = event.target.closest("[data-select-path]");
      if (checkbox) {
        toggleSelected(checkbox.dataset.selectPath, checkbox.checked);
        return;
      }
      const props = event.target.closest("[data-props-path]");
      if (props) {
        openProperties(props.dataset.propsPath);
        return;
      }
      const open = event.target.closest("[data-open-path]");
      if (open) {
        loadDirectory(open.dataset.openPath);
        return;
      }
      const row = event.target.closest("[data-row-open-path]");
      if (row && !event.target.closest("button,input,a")) {
        loadDirectory(row.dataset.rowOpenPath);
      }
    });
    helper().qs("#file-browser-list")?.addEventListener("keydown", (event) => {
      if (!["Enter", " "].includes(event.key)) return;
      const open = event.target.closest("[data-open-path]");
      if (!open) return;
      event.preventDefault();
      loadDirectory(open.dataset.openPath);
    });
    helper().qs("#file-breadcrumb")?.addEventListener("click", (event) => {
      const target = event.target.closest("[data-breadcrumb-path]");
      if (target) loadDirectory(target.dataset.breadcrumbPath);
    });
    helper().qs("#file-select-all")?.addEventListener("change", (event) => {
      toggleAllVisible(event.target.checked);
    });
    helper().qs("#file-operation-bar")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-file-action]");
      if (!button || button.disabled) return;
      if (["delete", "move"].includes(button.dataset.fileAction) && button.dataset.confirming !== "true") {
        button.dataset.confirming = "true";
        const oldText = button.textContent;
        const actionText = button.dataset.fileAction === "delete" ? "删除" : "移动";
        button.textContent = `再次点击确认${actionText}`;
        setOperationStatus(`${actionText}会改变源目录，请再次点击按钮确认。`, true);
        window.setTimeout(() => {
          button.dataset.confirming = "false";
          button.textContent = oldText;
        }, 3500);
        return;
      }
      submitFileAction(button.dataset.fileAction, button.dataset.destination || "");
    });
    helper().qs("#file-properties-close")?.addEventListener("click", closeProperties);
    helper().qs("#file-search")?.addEventListener("input", (event) => {
      state.query = event.target.value || "";
      renderEntryList();
    });
    helper().qs("#file-filters")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-file-filter]");
      if (!button) return;
      state.filter = button.dataset.fileFilter || "all";
      helper().qsa("[data-file-filter]").forEach((item) => {
        item.dataset.active = item === button ? "true" : "false";
      });
      renderEntryList();
    });
    helper().qs("#file-up")?.addEventListener("click", () => {
      if (state.parent) loadDirectory(state.parent);
    });
    helper().qs("#file-refresh")?.addEventListener("click", () => loadDirectory(state.path || "/"));
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadDirectory("/");
  });
})();
