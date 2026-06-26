(function () {
  const state = {
    root: "watch",
    path: "/",
    parent: null,
    entries: [],
    query: "",
    filter: "all",
  };

  function helper() {
    return window.IsoPacker;
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

  function renderBreadcrumb(payload) {
    const root = helper().qs("#file-breadcrumb");
    if (!root) return;
    helper().clearNode(root);

    const rootButton = document.createElement("button");
    rootButton.type = "button";
    rootButton.dataset.breadcrumbPath = "/";
    rootButton.textContent = payload.root || state.root;
    root.appendChild(rootButton);

    const rootPath = String((helper().qs(`[data-root="${state.root}"]`) || {}).dataset?.rootPath || "");
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
    helper().setText(helper().qs("#file-current-root"), state.root);
    helper().setText(helper().qs("#file-entry-count"), `${filteredEntries().length} / ${state.entries.length} 项`);
  }

  function renderEntryList() {
    const list = helper().qs("#file-browser-list");
    if (!list) return;
    helper().clearNode(list);
    const entries = filteredEntries();
    renderSummary();
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state slim";
      empty.textContent = state.entries.length ? "当前筛选条件下没有内容。" : "当前目录为空，或没有可读取的内容。";
      list.appendChild(empty);
      return;
    }
    entries.forEach((entry) => {
      const row = document.createElement(entry.type === "dir" ? "button" : "div");
      row.className = "file-row";
      row.dataset.kind = entryGroup(entry);
      if (entry.type === "dir") {
        row.type = "button";
        row.dataset.path = entry.path || "";
      }

      const kind = document.createElement("span");
      kind.className = "file-kind";
      kind.textContent = isDiscHint(entry) ? "DISC" : (entry.type === "dir" ? "DIR" : "FILE");

      const main = document.createElement("div");
      main.className = "file-main";
      const name = document.createElement("strong");
      name.className = "file-name";
      name.textContent = entry.name || "-";
      const meta = document.createElement("div");
      meta.className = "file-meta";
      const path = document.createElement("span");
      path.textContent = entry.path || "";
      const time = document.createElement("span");
      time.textContent = entry.mtime || "";
      meta.append(path, time);
      main.append(name, meta);

      const size = document.createElement("span");
      size.className = "file-size";
      size.textContent = entry.type === "dir" ? "-" : helper().formatBytes(entry.size);

      row.append(kind, main, size);
      list.appendChild(row);
    });
  }

  function renderEntries(payload) {
    state.path = payload.path || "/";
    state.parent = payload.parent || null;
    state.entries = Array.isArray(payload.entries) ? payload.entries : [];
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

  function bindEvents() {
    helper().qs(".root-switcher")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-root]");
      if (button) switchRoot(button.dataset.root);
    });
    helper().qs("#file-browser-list")?.addEventListener("click", (event) => {
      const row = event.target.closest("[data-path]");
      if (row) loadDirectory(row.dataset.path);
    });
    helper().qs("#file-breadcrumb")?.addEventListener("click", (event) => {
      const target = event.target.closest("[data-breadcrumb-path]");
      if (target) loadDirectory(target.dataset.breadcrumbPath);
    });
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
