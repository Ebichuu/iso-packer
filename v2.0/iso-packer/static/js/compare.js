(function () {
  const state = {
    root: "cd2",
    path: "",
    depth: 1,
    query: "",
    loading: false,
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

  function kindLabel(kind) {
    return {
      disc: "原盘目录",
      iso: "ISO",
      video: "视频文件",
      folder: "目录",
      file: "文件",
    }[kind || "file"] || kind || "文件";
  }

  function syncRoots() {
    helper().qsa("[data-compare-root]").forEach((button) => {
      const active = button.dataset.compareRoot === state.root;
      button.dataset.active = String(active);
    });
  }

  function activeRootPath(rootName = state.root) {
    const button = helper().qs(`[data-compare-root="${rootName}"]`);
    return String((button && button.dataset.rootPath) || "");
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
      root.appendChild(node("div", "p-8 text-center text-sm font-bold text-zinc-400", "没有扫描到可用于比对的候选。"));
      return;
    }
    groups.forEach((group) => {
      const section = node("article", "bg-white");
      const header = node("div", "p-4");
      const top = node("div", "flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between");
      const titleBox = node("div", "min-w-0 space-y-2");
      const kicker = node("div", "flex flex-wrap items-center gap-2");
      kicker.append(
        tag(group.multi_group ? "多组线索" : `${group.count || 0} 个候选`, group.multi_group ? "amber" : "zinc"),
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
      renderStats(payload.summary);
      renderGroups(payload.groups || []);
      setText("#compare-summary", `${payload.summary?.group_count || 0} 个分组 · ${payload.summary?.candidate_count || 0} 个候选${payload.summary?.truncated ? " · 已达到本轮上限" : ""}`);
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

  function setupEvents() {
    helper().qsa("[data-compare-root]").forEach((button) => {
      button.addEventListener("click", () => {
        state.root = button.dataset.compareRoot || "cd2";
        state.path = activeRootPath(state.root);
        const input = helper().qs("#compare-path");
        if (input) input.value = state.path;
        syncRoots();
        scan();
      });
    });
    const path = helper().qs("#compare-path");
    if (path) {
      state.path = path.value || activeRootPath();
      path.addEventListener("change", () => {
        state.path = path.value.trim() || activeRootPath();
        scan();
      });
      path.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          state.path = path.value.trim() || activeRootPath();
          scan();
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
    const scanButton = helper().qs("#compare-scan");
    if (scanButton) {
      scanButton.addEventListener("click", () => {
        const input = helper().qs("#compare-path");
        state.path = (input && input.value.trim()) || activeRootPath();
        scan();
      });
    }
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
