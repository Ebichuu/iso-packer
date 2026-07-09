(function () {
  const DIRECTORY_ROOT = "@roots";

  const state = {
    root: "cd2",
    path: "",
    depth: 1,
    query: "",
    loading: false,
    pickerPath: DIRECTORY_ROOT,
    pickerParent: null,
  };

  function helper() {
    return window.IsoPacker;
  }

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function setText(selector, value) {
    helper().setText(helper().qs(selector), value);
  }

  function normalizePath(value) {
    return String(value || "").replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  }

  function isPathInside(path, base) {
    const current = normalizePath(path);
    const root = normalizePath(base);
    if (!current || !root) return false;
    return current === root || current.startsWith(`${root}/`);
  }

  function rootButton(rootName = state.root) {
    return helper().qs(`[data-compare-root="${rootName}"]`);
  }

  function syncRoots() {
    helper().qsa("[data-compare-root]").forEach((button) => {
      const active = button.dataset.compareRoot === state.root;
      button.dataset.active = String(active);
    });
  }

  function activeRootPath(rootName = state.root) {
    const button = rootButton(rootName);
    return String((button && button.dataset.rootPath) || "");
  }

  function rootBasePath(rootName = state.root) {
    const button = rootButton(rootName);
    return String((button && (button.dataset.rootBase || button.dataset.rootPath)) || "");
  }

  function inferRootFromPath(path) {
    const matches = [];
    helper().qsa("[data-compare-root]").forEach((button) => {
      const rootName = button.dataset.compareRoot || "";
      const candidates = [button.dataset.rootBase, button.dataset.rootPath].filter(Boolean);
      candidates.forEach((base) => {
        if (isPathInside(path, base)) matches.push({ root: rootName, length: normalizePath(base).length });
      });
    });
    matches.sort((left, right) => right.length - left.length);
    return matches[0]?.root || "";
  }

  function updatePathInput() {
    const input = helper().qs("#compare-path");
    if (input) input.value = state.path || activeRootPath();
  }

  function setComparePath(path, shouldScan = true) {
    state.path = String(path || activeRootPath() || "").trim();
    const inferred = inferRootFromPath(state.path);
    if (inferred) state.root = inferred;
    syncRoots();
    updatePathInput();
    if (shouldScan) scan();
  }

  function renderStats(summary) {
    const data = summary || {};
    setText("#compare-stat-candidates", data.candidate_count ?? 0);
    setText("#compare-stat-groups", data.group_count ?? 0);
    setText("#compare-stat-multi", data.multi_group_count ?? 0);
    setText("#compare-stat-duplicates", data.duplicate_like_count ?? 0);
    setText("#compare-stat-scanned", data.scanned_dirs ?? 0);
  }

  function tag(text, tone) {
    const classes = {
      amber: "border-amber-200 bg-amber-50 text-amber-700",
      blue: "border-blue-200 bg-blue-50 text-blue-700",
      emerald: "border-emerald-200 bg-emerald-50 text-emerald-700",
      zinc: "border-zinc-200 bg-zinc-50 text-zinc-600",
    };
    return node("span", `rounded-full border px-2 py-0.5 text-[10px] font-black ${classes[tone || "zinc"]}`, text);
  }

  function renderItem(item) {
    const row = node("div", "grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1.4fr)_110px_120px_110px_110px]");
    const nameWrap = node("div", "min-w-0");
    const name = node("div", "truncate font-mono text-[11px] font-black text-zinc-800", item.name || "--");
    name.title = item.name || "";
    const path = node("div", "mt-1 truncate font-mono text-[10px] font-bold text-zinc-400", item.relative_path || item.path || "");
    path.title = item.path || "";
    nameWrap.append(name, path);
    row.append(
      nameWrap,
      node("div", "font-mono text-[11px] font-bold text-zinc-600", item.group || "未知组"),
      node("div", "font-mono text-[11px] font-bold text-zinc-600", item.resolution || "未知清晰度"),
      node("div", "font-mono text-[11px] font-bold text-zinc-600", item.source || "未知来源"),
      node("div", "font-mono text-[11px] font-bold text-zinc-500", item.mtime || "--")
    );
    return row;
  }

  function renderGroups(groups) {
    const root = helper().qs("#compare-groups");
    helper().clearNode(root);
    if (!groups || !groups.length) {
      root.appendChild(node("div", "p-8 text-center text-sm font-bold text-zinc-400", "没有发现同片多版本或多组的成品电影文件。"));
      return;
    }
    groups.forEach((group) => {
      const section = node("article", "bg-white");
      const header = node("div", "p-4");
      const top = node("div", "flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between");
      const titleBox = node("div", "min-w-0 space-y-2");
      const kicker = node("div", "flex flex-wrap items-center gap-2");
      kicker.append(
        tag(group.multi_group ? "多组影片" : `${group.count || 0} 个成品`, group.multi_group ? "amber" : "zinc"),
        tag(`${group.group_count || 0} 个发布组`, "blue")
      );
      const title = node("h4", "truncate text-base font-black tracking-tight text-zinc-950", `${group.title || "未命名"}${group.year ? ` (${group.year})` : ""}`);
      title.title = group.title || "";
      const meta = node("div", "flex flex-wrap gap-1.5");
      (group.sources || []).slice(0, 4).forEach((value) => meta.appendChild(tag(value, "emerald")));
      (group.resolutions || []).slice(0, 4).forEach((value) => meta.appendChild(tag(value, "zinc")));
      titleBox.append(kicker, title, meta);

      const groupBox = node("div", "flex max-w-full flex-wrap gap-1.5 lg:max-w-[420px] lg:justify-end");
      (group.groups || []).slice(0, 8).forEach((value) => groupBox.appendChild(tag(value, group.multi_group ? "amber" : "zinc")));
      top.append(titleBox, groupBox);
      header.appendChild(top);
      section.appendChild(header);

      const table = node("div", "border-t border-zinc-100");
      const head = node("div", "hidden gap-3 bg-zinc-50 px-4 py-2 font-mono text-[10px] font-black uppercase tracking-[0.12em] text-zinc-400 md:grid md:grid-cols-[minmax(0,1.4fr)_110px_120px_110px_110px]");
      head.append(
        node("span", "", "名称 / 路径"),
        node("span", "", "发布组"),
        node("span", "", "清晰度"),
        node("span", "", "来源"),
        node("span", "", "修改时间")
      );
      table.appendChild(head);
      (group.items || []).forEach((item) => table.appendChild(renderItem(item)));
      section.appendChild(table);
      root.appendChild(section);
    });
  }

  function summaryText(summary) {
    const data = summary || {};
    const groupCount = data.group_count || 0;
    const candidateCount = data.candidate_count || 0;
    const scannedCount = data.scanned_candidate_count || candidateCount;
    const hiddenCount = Math.max(0, scannedCount - candidateCount);
    const hiddenText = hiddenCount ? ` · 已忽略 ${hiddenCount} 个单片` : "";
    const truncatedText = data.truncated ? " · 已达到本轮上限" : "";
    return `${groupCount} 个多版本分组 · ${candidateCount} 个参与比对的成品${hiddenText}${truncatedText}`;
  }

  async function scan() {
    if (state.loading) return;
    state.loading = true;
    const button = helper().qs("#compare-scan");
    if (button) {
      button.disabled = true;
      button.classList.add("opacity-60");
    }
    const params = new URLSearchParams();
    params.set("root", state.root);
    params.set("path", state.path || activeRootPath());
    params.set("depth", String(state.depth));
    if (state.query) params.set("q", state.query);
    setText("#compare-summary", "扫描中...");
    try {
      const payload = await helper().fetchJson(`/api/compare?${params.toString()}`);
      if (payload.path) {
        state.path = payload.path;
        updatePathInput();
      }
      renderStats(payload.summary);
      renderGroups(payload.groups || []);
      setText("#compare-summary", summaryText(payload.summary));
      setText("#compare-current-path", payload.path || state.path || "--");
    } catch (error) {
      helper().notify(error.message || "扫描失败", true);
      renderStats({});
      renderGroups([]);
      setText("#compare-summary", error.message || "扫描失败");
    } finally {
      state.loading = false;
      if (button) {
        button.disabled = false;
        button.classList.remove("opacity-60");
      }
    }
  }

  function renderPickerMessage(message) {
    const list = helper().qs("#compare-directory-list");
    if (!list) return;
    list.replaceChildren(Object.assign(document.createElement("div"), {
      className: "empty-state slim",
      textContent: message,
    }));
  }

  function renderPickerEntries(payload) {
    state.pickerPath = payload.path || DIRECTORY_ROOT;
    state.pickerParent = payload.parent || null;
    setText("#compare-directory-path", payload.display_path || state.pickerPath);
    setText("#compare-directory-selected", state.pickerPath === DIRECTORY_ROOT ? "未选择" : state.pickerPath);
    const up = helper().qs("#compare-directory-up");
    const use = helper().qs("#compare-directory-use");
    if (up) up.disabled = !state.pickerParent;
    if (use) use.disabled = state.pickerPath === DIRECTORY_ROOT || state.pickerPath === "/";

    const entries = Array.isArray(payload.entries) ? payload.entries : [];
    setText("#compare-directory-status", entries.length ? `${entries.length} 个子目录` : "没有子目录");
    const list = helper().qs("#compare-directory-list");
    if (!list) return;
    helper().clearNode(list);
    if (!entries.length) {
      renderPickerMessage("没有可进入的子目录。");
      return;
    }
    const wrap = node("div", "grid gap-2");
    entries.forEach((entry) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "compare-directory-row";
      row.dataset.dirPath = entry.path || "";
      row.dataset.selected = entry.path === state.pickerPath ? "true" : "false";
      row.disabled = entry.readable === false;

      const kind = node("span", "rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1 text-center font-mono text-[10px] font-black text-zinc-500", "DIR");
      const main = node("span", "compare-directory-main");
      const name = node("strong", "", entry.name || entry.path || "未命名目录");
      const path = node("small", "", entry.path || "");
      const action = node("span", "rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[10px] font-black text-zinc-500", entry.readable === false ? "不可读" : "进入");
      main.append(name, path);
      row.append(kind, main, action);
      wrap.appendChild(row);
    });
    list.appendChild(wrap);
  }

  async function loadPickerDirectory(path) {
    renderPickerMessage("正在读取目录。");
    try {
      const target = path || DIRECTORY_ROOT;
      const payload = await helper().fetchJson(`/api/directories?scope=media_compare&path=${encodeURIComponent(target)}`);
      renderPickerEntries(payload);
    } catch (error) {
      renderPickerMessage(error.message || "目录读取失败。");
      setText("#compare-directory-status", "读取失败");
    }
  }

  function openPicker() {
    const picker = helper().qs("#compare-directory-picker");
    if (!picker) return;
    picker.classList.remove("hidden");
    document.body.classList.add("has-modal");
    loadPickerDirectory(state.path || activeRootPath() || DIRECTORY_ROOT);
  }

  function closePicker() {
    const picker = helper().qs("#compare-directory-picker");
    if (picker) picker.classList.add("hidden");
    document.body.classList.remove("has-modal");
  }

  function usePickerDirectory() {
    if (!state.pickerPath || state.pickerPath === DIRECTORY_ROOT || state.pickerPath === "/") return;
    const selected = state.pickerPath;
    closePicker();
    setComparePath(selected, true);
  }

  function setupEvents() {
    helper().qsa("[data-compare-root]").forEach((button) => {
      button.addEventListener("click", () => {
        state.root = button.dataset.compareRoot || "cd2";
        state.path = activeRootPath(state.root);
        syncRoots();
        updatePathInput();
        scan();
      });
    });
    const path = helper().qs("#compare-path");
    if (path) {
      state.path = path.value || activeRootPath();
      path.addEventListener("change", () => setComparePath(path.value, true));
      path.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          setComparePath(path.value, true);
        }
      });
    }
    const depth = helper().qs("#compare-depth");
    if (depth) {
      depth.addEventListener("change", () => {
        state.depth = Number(depth.value || 1);
        scan();
      });
    }
    const search = helper().qs("#compare-search");
    if (search) {
      let debounce = null;
      search.addEventListener("input", () => {
        window.clearTimeout(debounce);
        debounce = window.setTimeout(() => {
          state.query = search.value.trim();
          scan();
        }, 260);
      });
    }
    helper().qs("#compare-scan")?.addEventListener("click", () => {
      const input = helper().qs("#compare-path");
      setComparePath((input && input.value.trim()) || activeRootPath(), true);
    });
    helper().qs("#compare-pick-directory")?.addEventListener("click", openPicker);
    helper().qs("#compare-directory-list")?.addEventListener("click", (event) => {
      const row = event.target.closest("[data-dir-path]");
      if (row && !row.disabled) loadPickerDirectory(row.dataset.dirPath);
    });
    helper().qs("#compare-directory-up")?.addEventListener("click", () => {
      if (state.pickerParent) loadPickerDirectory(state.pickerParent);
    });
    helper().qs("#compare-directory-roots")?.addEventListener("click", () => loadPickerDirectory(DIRECTORY_ROOT));
    helper().qs("#compare-directory-use")?.addEventListener("click", usePickerDirectory);
    helper().qs("#compare-directory-close")?.addEventListener("click", closePicker);
    helper().qs("#compare-directory-cancel")?.addEventListener("click", closePicker);
    helper().qs("#compare-directory-picker")?.addEventListener("click", (event) => {
      if (event.target.id === "compare-directory-picker") closePicker();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    state.path = activeRootPath();
    const path = helper().qs("#compare-path");
    if (path && !path.value) path.value = state.path;
    syncRoots();
    setupEvents();
    scan();
  });
})();
