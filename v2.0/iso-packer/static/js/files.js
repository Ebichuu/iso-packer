(function () {
  const DIRECTORY_ROOT = "@roots";
  const LOCATION_STORE = "iso-packer:file-browser-location";
  const ROOT_LABELS = {
    watch: "本机监控",
    output: "本机输出",
    cd2: "网盘挂载",
  };

  const ACTION_LABELS = {
    copy: "复制",
    move: "移动",
    delete: "删除",
    rename: "重命名",
  };

  const state = {
    root: "watch",
    path: "/",
    parent: null,
    entries: [],
    query: "",
    rootPath: "",
    selected: new Set(),
    operationTimer: null,
    customDestination: "",
    destinationAction: "copy",
    destinationPath: DIRECTORY_ROOT,
    destinationParent: null,
    contextPath: "",
    renamePath: "",
    renameName: "",
    sortKey: "name",
    sortDir: "asc",
    page: 1,
    pageSize: 50,
  };

  function helper() {
    return window.IsoPacker;
  }

  function readSavedLocation() {
    try {
      return JSON.parse(window.localStorage.getItem(LOCATION_STORE) || "{}") || {};
    } catch (_) {
      return {};
    }
  }

  function saveCurrentLocation() {
    try {
      const saved = readSavedLocation();
      saved.root = state.root;
      saved.paths = Object.assign({}, saved.paths || {}, { [state.root]: state.path || "/" });
      window.localStorage.setItem(LOCATION_STORE, JSON.stringify(saved));
    } catch (_) {}
  }

  function savedCd2Shortcut() {
    const saved = readSavedLocation();
    return String(((saved.shortcuts || {}).cd2) || "").trim();
  }

  function saveCd2Shortcut(path) {
    try {
      const saved = readSavedLocation();
      saved.shortcuts = Object.assign({}, saved.shortcuts || {}, { cd2: path || "" });
      window.localStorage.setItem(LOCATION_STORE, JSON.stringify(saved));
    } catch (_) {}
  }

  function clearSavedPath(rootName) {
    try {
      const saved = readSavedLocation();
      if (saved.paths) delete saved.paths[rootName];
      window.localStorage.setItem(LOCATION_STORE, JSON.stringify(saved));
    } catch (_) {}
  }

  function rootPathFor(rootName = state.root) {
    return String((helper().qs(`[data-root="${rootName}"]`) || {}).dataset?.rootPath || "");
  }

  function rootLabel(rootName = state.root) {
    return ROOT_LABELS[rootName] || rootName;
  }

  function normalizeBrowserPath(path) {
    return String(path || "").replace(/\\/g, "/").replace(/\/+$/, "");
  }

  function cd2ShortcutDefaultPath() {
    return String((helper().qs('[data-file-shortcut="cd2"]') || {}).dataset?.defaultPath || rootPathFor("cd2") || "");
  }

  function cd2ShortcutPath() {
    return savedCd2Shortcut() || cd2ShortcutDefaultPath() || rootPathFor("cd2") || "/";
  }

  function isDiscHint(entry) {
    if (entry && Object.prototype.hasOwnProperty.call(entry, "disc_type")) {
      return Boolean(entry.disc_type);
    }
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
      if (!query) return true;
      return [entry.name, entry.path, entry.type].some((value) => String(value || "").toLowerCase().includes(query));
    });
  }

  function sortValue(entry, key) {
    if (key === "size") return Number(entry.size || 0);
    if (key === "mtime") {
      const time = Date.parse(entry.mtime || "");
      return Number.isFinite(time) ? time : 0;
    }
    if (key === "kind") return entryGroup(entry);
    return String(entry.name || "").toLowerCase();
  }

  function sortedEntries() {
    const entries = filteredEntries().slice();
    entries.sort((a, b) => {
      const aDir = a.type === "dir";
      const bDir = b.type === "dir";
      if (aDir !== bDir) return aDir ? -1 : 1;
      const av = sortValue(a, state.sortKey);
      const bv = sortValue(b, state.sortKey);
      let result = 0;
      if (typeof av === "number" && typeof bv === "number") result = av - bv;
      else result = String(av).localeCompare(String(bv), "zh-Hans-CN", { numeric: true, sensitivity: "base" });
      if (result === 0) result = String(a.name || "").localeCompare(String(b.name || ""), "zh-Hans-CN", { numeric: true, sensitivity: "base" });
      return state.sortDir === "desc" ? -result : result;
    });
    return entries;
  }

  function pageSizeValue() {
    return state.pageSize === "all" ? Infinity : Number(state.pageSize || 50);
  }

  function pageCount(total) {
    const size = pageSizeValue();
    if (!Number.isFinite(size)) return 1;
    return Math.max(1, Math.ceil(total / size));
  }

  function pagedEntries(entries) {
    const pages = pageCount(entries.length);
    state.page = Math.min(Math.max(1, Number(state.page || 1)), pages);
    const size = pageSizeValue();
    if (!Number.isFinite(size)) return entries;
    const start = (state.page - 1) * size;
    return entries.slice(start, start + size);
  }

  function updateSortIndicators() {
    helper().qsa("[data-sort-indicator]").forEach((node) => {
      const key = node.dataset.sortIndicator;
      node.textContent = key === state.sortKey ? (state.sortDir === "asc" ? "↑" : "↓") : "";
    });
  }

  function renderPagination(total) {
    const pages = pageCount(total);
    state.page = Math.min(Math.max(1, Number(state.page || 1)), pages);
    helper().setText(helper().qs("#file-page-summary"), `第 ${state.page} / ${pages} 页 · ${total} 项`);
    const jump = helper().qs("#file-page-jump");
    if (jump) {
      jump.max = String(pages);
      jump.value = String(state.page);
    }
    const size = helper().qs("#file-page-size");
    if (size) size.value = String(state.pageSize);
    helper().qsa("[data-page-action]").forEach((button) => {
      if (button.dataset.pageAction === "prev") button.disabled = state.page <= 1;
      if (button.dataset.pageAction === "next") button.disabled = state.page >= pages;
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
    renderShortcutState();
  }

  function renderShortcutState() {
    helper().qsa("[data-file-shortcut]").forEach((button) => {
      const shortcut = button.dataset.fileShortcut || "";
      let targetRoot = shortcut;
      let targetPath = rootPathFor(shortcut);
      if (shortcut === "cd2") {
        targetRoot = "cd2";
        targetPath = cd2ShortcutPath();
      }
      const active = state.root === targetRoot && normalizeBrowserPath(state.path) === normalizeBrowserPath(targetPath);
      button.dataset.active = active ? "true" : "false";
      if (shortcut === "cd2") {
        button.title = `CD2 快捷：${targetPath || rootPathFor("cd2") || "-"}`;
      }
    });
    const save = helper().qs("#file-save-cd2-shortcut");
    if (save) save.classList.toggle("hidden", state.root !== "cd2");
    const status = helper().qs("#file-shortcut-status");
    if (status) {
      const shortcut = cd2ShortcutPath();
      status.textContent = state.root === "cd2" ? `CD2 快捷：${shortcut || "-"}` : "CD2 快捷可保存当前网盘位置";
      status.title = shortcut || "";
    }
  }

  function renderOperationBar() {
    const bar = helper().qs("#file-operation-bar");
    if (!bar) return;
    const hasSelection = state.selected.size > 0;
    bar.classList.toggle("hidden", !hasSelection);
    const destinationLabel = helper().qs("#file-custom-destination-label");
    const destinationInput = helper().qs("#file-custom-destination");
    if (destinationInput) destinationInput.value = state.customDestination;
    if (destinationLabel) {
      destinationLabel.textContent = state.customDestination || "未选择其他目录";
      destinationLabel.title = state.customDestination || "";
    }
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
    const entries = sortedEntries();
    const pageEntries = pagedEntries(entries);
    renderSummary();
    renderOperationBar();
    syncSelectAll(pageEntries);
    updateSortIndicators();
    renderPagination(entries.length);
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state slim";
      empty.textContent = state.entries.length ? "当前搜索条件下没有内容。" : "当前目录为空，或没有可读取的内容。";
      list.appendChild(empty);
      return;
    }
    pageEntries.forEach((entry) => {
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
      if (isDiscHint(entry)) {
        const pack = document.createElement("span");
        pack.className = "file-pack-state";
        pack.dataset.state = entry.pack_state || "unpacked";
        pack.textContent = entry.pack_label || "未封装";
        if (entry.pack_target) pack.title = entry.pack_target;
        attr.appendChild(pack);
      }

      const size = document.createElement("span");
      size.className = "file-size";
      size.textContent = entry.type === "dir" ? "-" : helper().formatBytes(entry.size);

      const actions = document.createElement("div");
      actions.className = "file-row-actions";
      const props = document.createElement("button");
      props.type = "button";
      props.dataset.propsPath = entry.path || "";
      props.innerHTML = '<span aria-hidden="true">ⓘ</span>';
      props.title = "查看属性";
      props.setAttribute("aria-label", `查看 ${entry.name || "文件"} 属性`);
      actions.appendChild(props);

      row.append(checkbox, main, size, mtime, attr, actions);
      list.appendChild(row);
    });
  }

  function renderEntries(payload) {
    state.path = payload.path || "/";
    state.parent = payload.parent || null;
    state.rootPath = payload.root_path || rootPathFor();
    state.entries = Array.isArray(payload.entries) ? payload.entries : [];
    state.page = 1;
    state.selected.clear();
    renderBreadcrumb(payload);
    renderEntryList();
    saveCurrentLocation();
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
      if (targetPath !== "/") {
        clearSavedPath(state.root);
        loadDirectory("/");
        return;
      }
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
    const saved = readSavedLocation();
    state.path = (saved.paths && saved.paths[root]) || "/";
    state.parent = null;
    state.entries = [];
    state.query = "";
    state.rootPath = rootPathFor(root);
    state.selected.clear();
    state.page = 1;
    const search = helper().qs("#file-search");
    if (search) search.value = "";
    helper().qsa("[data-root]").forEach((button) => {
      button.dataset.active = button.dataset.root === root ? "true" : "false";
    });
    loadDirectory(state.path || "/");
  }

  function openShortcut(shortcut) {
    if (shortcut === "watch" || shortcut === "output") {
      state.root = shortcut;
      state.path = "/";
      state.parent = null;
      state.entries = [];
      state.query = "";
      state.rootPath = rootPathFor(shortcut);
      state.selected.clear();
      state.page = 1;
      const search = helper().qs("#file-search");
      if (search) search.value = "";
      helper().qsa("[data-root]").forEach((button) => {
        button.dataset.active = button.dataset.root === shortcut ? "true" : "false";
      });
      loadDirectory("/");
      return;
    }
    if (shortcut === "cd2") {
      state.root = "cd2";
      state.path = cd2ShortcutPath();
      state.parent = null;
      state.entries = [];
      state.query = "";
      state.rootPath = rootPathFor("cd2");
      state.selected.clear();
      state.page = 1;
      const search = helper().qs("#file-search");
      if (search) search.value = "";
      helper().qsa("[data-root]").forEach((button) => {
        button.dataset.active = button.dataset.root === "cd2" ? "true" : "false";
      });
      loadDirectory(state.path || "/");
    }
  }

  function saveCurrentCd2Shortcut() {
    if (state.root !== "cd2" || !state.path) {
      helper().notify("请先进入一个网盘挂载目录", true);
      return;
    }
    saveCd2Shortcut(state.path);
    renderShortcutState();
    helper().notify("已保存 CD2 快捷入口");
  }

  function toggleSelected(path, checked) {
    if (!path) return;
    if (checked) state.selected.add(path);
    else state.selected.delete(path);
    renderEntryList();
  }

  function toggleAllVisible(checked) {
    pagedEntries(sortedEntries()).forEach((entry) => {
      if (entry.path) {
        if (checked) state.selected.add(entry.path);
        else state.selected.delete(entry.path);
      }
    });
    renderEntryList();
  }

  function appendPropertyRow(body, label, value) {
    const row = document.createElement("div");
    row.className = "file-prop-row";
    const key = document.createElement("span");
    key.textContent = label;
    const text = document.createElement("strong");
    text.textContent = value || "-";
    row.append(key, text);
    body.appendChild(row);
  }

  function appendDiskUsage(body, disk) {
    if (!disk) return;
    const wrap = document.createElement("div");
    wrap.className = "mt-3 rounded-xl border border-zinc-100 bg-zinc-50 p-3";
    const title = document.createElement("div");
    title.className = "mb-2 text-[11px] font-black text-zinc-700";
    title.textContent = "空间使用";
    const meta = document.createElement("div");
    meta.className = "mb-2 flex justify-between gap-3 font-mono text-[10px] font-bold text-zinc-500";
    const used = document.createElement("span");
    used.textContent = `已用 ${helper().formatBytes(disk.used)}`;
    const free = document.createElement("span");
    free.textContent = `可用 ${helper().formatBytes(disk.free)}`;
    const bar = document.createElement("div");
    bar.className = "h-2 overflow-hidden rounded-full bg-zinc-200";
    const fill = document.createElement("div");
    fill.className = "h-full rounded-full bg-emerald-600";
    const pct = disk.total ? Math.min(100, Math.max(0, (Number(disk.used || 0) / Number(disk.total || 1)) * 100)) : 0;
    fill.style.width = `${pct.toFixed(1)}%`;
    const total = document.createElement("div");
    total.className = "mt-2 font-mono text-[10px] font-bold text-zinc-500";
    total.textContent = `总共 ${helper().formatBytes(disk.total)}`;
    meta.append(used, free);
    bar.appendChild(fill);
    wrap.append(title, meta, bar, total);
    body.appendChild(wrap);
  }

  async function openProperties(path) {
    const entry = state.entries.find((item) => item.path === path);
    const panel = helper().qs("#file-properties-panel");
    const body = helper().qs("#file-properties-body");
    const shell = helper().qs("#file-browser-shell");
    if (!panel || !body) return;
    panel.classList.remove("hidden");
    if (shell) shell.dataset.propertiesOpen = "true";
    helper().clearNode(body);
    appendPropertyRow(body, "名称", entry?.name || path || "-");
    appendPropertyRow(body, "状态", "正在读取属性...");
    try {
      const payload = await helper().fetchJson(`/api/file-properties?root=${encodeURIComponent(state.root)}&path=${encodeURIComponent(path)}`);
      helper().clearNode(body);
      appendPropertyRow(body, "名称", payload.name || "-");
      appendPropertyRow(body, "类型", payload.type === "dir" ? "文件夹" : "文件");
      if (payload.disc_type) {
        appendPropertyRow(body, "原盘结构", payload.disc_type || "DISC");
        appendPropertyRow(body, "是否封装", payload.pack_label || "未封装");
        if (payload.pack_task_label) appendPropertyRow(body, "封装状态", payload.pack_task_label);
        if (payload.pack_target) appendPropertyRow(body, "ISO 位置", payload.pack_target);
      }
      appendPropertyRow(body, "大小", helper().formatBytes(payload.size));
      if (payload.type === "dir") {
        const count = `${payload.file_count || 0} 个文件 / ${payload.dir_count || 0} 个子目录${payload.partial ? "（部分目录不可读）" : ""}`;
        appendPropertyRow(body, "内容", count);
      }
      appendPropertyRow(body, "修改时间", payload.mtime || "-");
      appendPropertyRow(body, "创建时间", payload.ctime || "-");
      appendPropertyRow(body, "访问时间", payload.atime || "-");
      appendPropertyRow(body, "可读写", `${payload.readable ? "可读" : "不可读"} / ${payload.writable ? "可写" : "不可写"}`);
      appendPropertyRow(body, "路径", payload.path || "-");
      appendPropertyRow(body, "根目录", `${rootLabel(payload.root)} · ${payload.root_path || ""}`);
      appendDiskUsage(body, payload.disk);
    } catch (error) {
      helper().clearNode(body);
      appendPropertyRow(body, "属性读取失败", error.message || "无法读取文件属性");
    }
  }

  function closeProperties() {
    helper().qs("#file-properties-panel")?.classList.add("hidden");
    const shell = helper().qs("#file-browser-shell");
    if (shell) delete shell.dataset.propertiesOpen;
  }

  function setOperationStatus(message, isError = false) {
    const node = helper().qs("#file-operation-status");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("text-red-600", Boolean(isError));
    node.classList.toggle("text-zinc-500", !isError);
  }

  function closeDestinationPicker() {
    const picker = helper().qs("#file-destination-picker");
    if (picker) picker.classList.add("hidden");
    document.body.classList.remove("has-modal");
    const use = helper().qs("#file-destination-use");
    if (use) {
      use.dataset.confirming = "false";
      use.textContent = state.destinationAction === "move" ? "移动到这里" : "复制到这里";
    }
  }

  function updateDestinationSelection(path) {
    state.customDestination = path || "";
    const input = helper().qs("#file-custom-destination");
    const label = helper().qs("#file-custom-destination-label");
    if (input) input.value = state.customDestination;
    if (label) {
      label.textContent = state.customDestination || "未选择其他目录";
      label.title = state.customDestination || "";
    }
  }

  function renderDestinationMessage(message) {
    const list = helper().qs("#file-destination-list");
    if (!list) return;
    list.replaceChildren(Object.assign(document.createElement("div"), {
      className: "empty-state slim",
      textContent: message,
    }));
  }

  function renderDestinationEntries(payload) {
    state.destinationPath = payload.path || DIRECTORY_ROOT;
    state.destinationParent = payload.parent || null;
    helper().setText(helper().qs("#file-destination-path"), payload.display_path || state.destinationPath);
    helper().setText(helper().qs("#file-destination-selected"), state.destinationPath === DIRECTORY_ROOT ? "未选择" : state.destinationPath);
    const up = helper().qs("#file-destination-up");
    const use = helper().qs("#file-destination-use");
    if (up) up.disabled = !state.destinationParent;
    if (use) {
      use.disabled = state.destinationPath === DIRECTORY_ROOT || state.destinationPath === "/";
      use.textContent = state.destinationAction === "move" ? "移动到这里" : "复制到这里";
      use.dataset.confirming = "false";
    }
    const list = helper().qs("#file-destination-list");
    if (!list) return;
    helper().clearNode(list);
    const entries = Array.isArray(payload.entries) ? payload.entries : [];
    if (!entries.length) {
      renderDestinationMessage("没有可进入的子目录。");
      return;
    }
    const wrap = document.createElement("div");
    wrap.className = "grid gap-2";
    entries.forEach((entry) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "file-destination-row";
      row.dataset.dirPath = entry.path || "";
      row.dataset.selected = entry.path === state.destinationPath ? "true" : "false";
      row.disabled = entry.readable === false;

      const kind = document.createElement("span");
      kind.className = "file-kind";
      kind.textContent = "DIR";
      const main = document.createElement("span");
      main.className = "file-destination-main";
      const name = document.createElement("strong");
      name.textContent = entry.name || entry.path || "未命名目录";
      const path = document.createElement("small");
      path.textContent = entry.path || "";
      const statePill = document.createElement("span");
      statePill.className = "soft-pill";
      statePill.textContent = entry.readable === false ? "不可读" : "进入";
      main.append(name, path);
      row.append(kind, main, statePill);
      wrap.appendChild(row);
    });
    list.appendChild(wrap);
  }

  async function loadDestinationDirectory(path) {
    renderDestinationMessage("正在读取目录。");
    try {
      const targetPath = path || DIRECTORY_ROOT;
      const payload = await helper().fetchJson(`/api/directories?scope=file_destination&path=${encodeURIComponent(targetPath)}`);
      renderDestinationEntries(payload);
    } catch (error) {
      renderDestinationMessage(error.message || "目录读取失败。");
    }
  }

  function openDestinationPicker(action) {
    if (!selectedEntries().length) {
      helper().notify("请先选择文件或目录", true);
      return;
    }
    state.destinationAction = action || "copy";
    const picker = helper().qs("#file-destination-picker");
    if (!picker) return;
    helper().setText(helper().qs("#file-destination-title"), state.destinationAction === "move" ? "移动到..." : "复制到...");
    helper().setText(helper().qs("#file-destination-status"), `${state.selected.size} 项已选`);
    picker.classList.remove("hidden");
    document.body.classList.add("has-modal");
    loadDestinationDirectory(state.customDestination || DIRECTORY_ROOT);
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

  async function submitFileAction(action, destination, customDestination) {
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
        const custom = (customDestination || state.customDestination || helper().qs("#file-custom-destination")?.value || "").trim();
        if (!custom) {
          helper().notify("请先选择其他目录", true);
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
    const isRemoteCopy = action === "copy" && destination === "watch";
    setOperationStatus(isRemoteCopy ? "正在提交 CD2 网盘复制任务..." : "正在提交后台任务。");
    try {
      const response = await helper().fetchJson("/api/file-actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (response.remote_copy) {
        const message = response.message || "CD2 网盘复制任务已创建";
        setOperationStatus(message, !response.ok);
        helper().notify(message, !response.ok);
        state.selected.clear();
        renderEntryList();
        loadDirectory(state.path || "/");
        return;
      }
      helper().notify("文件操作已开始");
      pollOperation(response.task_id);
    } catch (error) {
      setOperationStatus(error.message || "文件操作提交失败", true);
      helper().notify(error.message || "文件操作提交失败", true);
    }
  }

  function openRenameDialog(path) {
    const entry = state.entries.find((item) => item.path === path);
    const dialog = helper().qs("#file-rename-dialog");
    const input = helper().qs("#file-rename-input");
    if (!dialog || !input || !path) return;
    state.renamePath = path;
    state.renameName = entry?.name || path.split(/[\\/]/).filter(Boolean).pop() || "";
    helper().setText(helper().qs("#file-rename-current"), state.renameName || path);
    helper().setText(helper().qs("#file-rename-error"), "");
    input.value = state.renameName;
    dialog.classList.remove("hidden");
    document.body.classList.add("has-modal");
    window.setTimeout(() => {
      input.focus();
      input.select();
    }, 0);
  }

  function closeRenameDialog() {
    helper().qs("#file-rename-dialog")?.classList.add("hidden");
    document.body.classList.remove("has-modal");
    state.renamePath = "";
    state.renameName = "";
  }

  async function submitRename() {
    const input = helper().qs("#file-rename-input");
    const error = helper().qs("#file-rename-error");
    const newName = (input?.value || "").trim();
    if (!state.renamePath || !newName) {
      if (error) error.textContent = "请填写新名称";
      return;
    }
    if (newName === state.renameName) {
      closeRenameDialog();
      return;
    }
    if (/[\\/]/.test(newName) || newName === "." || newName === "..") {
      if (error) error.textContent = "名称不能包含路径分隔符";
      return;
    }
    try {
      const response = await helper().fetchJson("/api/file-actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "rename",
          root: state.root,
          paths: [state.renamePath],
          new_name: newName,
        }),
      });
      closeRenameDialog();
      helper().notify("重命名已开始");
      pollOperation(response.task_id);
    } catch (err) {
      if (error) error.textContent = err.message || "重命名失败";
    }
  }

  function hideContextMenu() {
    const menu = helper().qs("#file-context-menu");
    if (!menu) return;
    menu.classList.add("hidden");
    helper().qsa("[data-context-action]", menu).forEach((item) => {
      item.dataset.confirming = "false";
      if (item.dataset.originalText) item.textContent = item.dataset.originalText;
    });
  }

  function prepareContextSelection(path) {
    if (!path) return;
    if (!state.selected.has(path)) {
      state.selected.clear();
      state.selected.add(path);
      renderEntryList();
    }
    state.contextPath = path;
  }

  function showContextMenu(event, path) {
    const menu = helper().qs("#file-context-menu");
    if (!menu || !path) return;
    prepareContextSelection(path);
    menu.classList.remove("hidden");
    const margin = 8;
    const rect = menu.getBoundingClientRect();
    const left = Math.min(event.clientX, window.innerWidth - rect.width - margin);
    const top = Math.min(event.clientY, window.innerHeight - rect.height - margin);
    menu.style.left = `${Math.max(margin, left)}px`;
    menu.style.top = `${Math.max(margin, top)}px`;
  }

  function handleContextAction(button) {
    const action = button.dataset.contextAction || "";
    if (action === "select") {
      toggleSelected(state.contextPath, !state.selected.has(state.contextPath));
      hideContextMenu();
      return;
    }
    if (action === "properties") {
      openProperties(state.contextPath);
      hideContextMenu();
      return;
    }
    if (action === "copy-watch") {
      hideContextMenu();
      submitFileAction("copy", "watch");
      return;
    }
    if (action === "copy-output") {
      hideContextMenu();
      submitFileAction("copy", "output");
      return;
    }
    if (action === "copy-custom") {
      hideContextMenu();
      openDestinationPicker("copy");
      return;
    }
    if (action === "move-custom") {
      hideContextMenu();
      openDestinationPicker("move");
      return;
    }
    if (action === "rename") {
      openRenameDialog(state.contextPath);
      hideContextMenu();
      return;
    }
    if (action === "delete") {
      if (button.dataset.confirming !== "true") {
        button.dataset.confirming = "true";
        button.dataset.originalText = button.dataset.originalText || button.textContent;
        button.textContent = "再次点击确认删除";
        setOperationStatus("删除会改变源目录，请再次点击确认。", true);
        window.setTimeout(() => {
          button.dataset.confirming = "false";
          button.textContent = button.dataset.originalText || "删除";
        }, 3500);
        return;
      }
      hideContextMenu();
      submitFileAction("delete", "");
    }
  }

  function bindEvents() {
    helper().qs(".root-switcher")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-root]");
      if (button) switchRoot(button.dataset.root);
    });
    helper().qs("#file-shortcuts")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-file-shortcut]");
      if (button) openShortcut(button.dataset.fileShortcut);
    });
    helper().qs("#file-save-cd2-shortcut")?.addEventListener("click", saveCurrentCd2Shortcut);
    helper().qs("#file-browser-list")?.addEventListener("click", (event) => {
      hideContextMenu();
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
    helper().qs("#file-browser-list")?.addEventListener("contextmenu", (event) => {
      const row = event.target.closest("[data-path]");
      if (!row || !row.dataset.path) return;
      event.preventDefault();
      showContextMenu(event, row.dataset.path);
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
    helper().qsa("[data-file-sort]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.fileSort || "name";
        if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
        else {
          state.sortKey = key;
          state.sortDir = key === "mtime" || key === "size" ? "desc" : "asc";
        }
        state.page = 1;
        renderEntryList();
      });
    });
    helper().qs("#file-select-all")?.addEventListener("change", (event) => {
      toggleAllVisible(event.target.checked);
    });
    helper().qs("#file-page-size")?.addEventListener("change", (event) => {
      state.pageSize = event.target.value === "all" ? "all" : Number(event.target.value || 50);
      state.page = 1;
      renderEntryList();
    });
    helper().qsa("[data-page-action]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.pageAction === "prev") state.page -= 1;
        if (button.dataset.pageAction === "next") state.page += 1;
        renderEntryList();
      });
    });
    helper().qs("#file-page-go")?.addEventListener("click", () => {
      const jump = Number(helper().qs("#file-page-jump")?.value || 1);
      state.page = Number.isFinite(jump) ? jump : 1;
      renderEntryList();
    });
    helper().qs("#file-pick-destination")?.addEventListener("click", () => openDestinationPicker("copy"));
    helper().qs("#file-operation-bar")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-file-action]");
      if (!button || button.disabled) return;
      if (button.dataset.destination === "custom" && ["copy", "move"].includes(button.dataset.fileAction)) {
        openDestinationPicker(button.dataset.fileAction);
        return;
      }
      if (button.dataset.fileAction === "delete" && button.dataset.confirming !== "true") {
        button.dataset.confirming = "true";
        const oldText = button.textContent;
        button.textContent = "再次点击确认删除";
        setOperationStatus("删除会改变源目录，请再次点击按钮确认。", true);
        window.setTimeout(() => {
          button.dataset.confirming = "false";
          button.textContent = oldText;
        }, 3500);
        return;
      }
      submitFileAction(button.dataset.fileAction, button.dataset.destination || "");
    });
    helper().qs("#file-context-menu")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-context-action]");
      if (button) handleContextAction(button);
    });
    helper().qs("#file-rename-submit")?.addEventListener("click", submitRename);
    helper().qs("#file-rename-close")?.addEventListener("click", closeRenameDialog);
    helper().qs("#file-rename-cancel")?.addEventListener("click", closeRenameDialog);
    helper().qs("#file-rename-dialog")?.addEventListener("click", (event) => {
      if (event.target.id === "file-rename-dialog") closeRenameDialog();
    });
    helper().qs("#file-rename-input")?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        submitRename();
      }
      if (event.key === "Escape") closeRenameDialog();
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest("#file-context-menu")) hideContextMenu();
    });
    helper().qs("#file-destination-list")?.addEventListener("click", (event) => {
      const row = event.target.closest("[data-dir-path]");
      if (row && !row.disabled) loadDestinationDirectory(row.dataset.dirPath);
    });
    helper().qs("#file-destination-up")?.addEventListener("click", () => {
      if (state.destinationParent) loadDestinationDirectory(state.destinationParent);
    });
    helper().qs("#file-destination-roots")?.addEventListener("click", () => loadDestinationDirectory(DIRECTORY_ROOT));
    helper().qs("#file-destination-close")?.addEventListener("click", closeDestinationPicker);
    helper().qs("#file-destination-cancel")?.addEventListener("click", closeDestinationPicker);
    helper().qs("#file-destination-picker")?.addEventListener("click", (event) => {
      if (event.target.id === "file-destination-picker") closeDestinationPicker();
    });
    helper().qs("#file-destination-use")?.addEventListener("click", (event) => {
      const button = event.currentTarget;
      if (!state.destinationPath || state.destinationPath === DIRECTORY_ROOT || state.destinationPath === "/") return;
      if (state.destinationAction === "move" && button.dataset.confirming !== "true") {
        button.dataset.confirming = "true";
        button.textContent = "再次点击确认移动";
        setOperationStatus("移动会改变源目录，请再次点击确认。", true);
        return;
      }
      updateDestinationSelection(state.destinationPath);
      const action = state.destinationAction;
      const destination = state.destinationPath;
      closeDestinationPicker();
      submitFileAction(action, "custom", destination);
    });
    helper().qs("#file-properties-close")?.addEventListener("click", closeProperties);
    helper().qs("#file-search")?.addEventListener("input", (event) => {
      state.query = event.target.value || "";
      state.page = 1;
      renderEntryList();
    });
    helper().qs("#file-up")?.addEventListener("click", () => {
      if (state.parent) loadDirectory(state.parent);
    });
    helper().qs("#file-refresh")?.addEventListener("click", () => loadDirectory(state.path || "/"));
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    const saved = readSavedLocation();
    const savedRoot = saved.root && rootPathFor(saved.root) ? saved.root : state.root;
    state.root = savedRoot;
    state.rootPath = rootPathFor(savedRoot);
    helper().qsa("[data-root]").forEach((button) => {
      button.dataset.active = button.dataset.root === savedRoot ? "true" : "false";
    });
    loadDirectory((saved.paths && saved.paths[savedRoot]) || "/");
  });
})();
