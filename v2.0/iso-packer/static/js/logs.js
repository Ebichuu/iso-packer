(function () {
  const state = {
    type: "all",
    query: "",
    limit: 200,
    timer: null,
    loading: false,
    latestStatus: null,
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

  function levelClass(level) {
    return {
      error: "border-red-200 bg-red-50 text-red-700",
      success: "border-emerald-200 bg-emerald-50 text-emerald-700",
      active: "border-blue-200 bg-blue-50 text-blue-700",
      info: "border-zinc-200 bg-zinc-50 text-zinc-600",
    }[level || "info"] || "border-zinc-200 bg-zinc-50 text-zinc-600";
  }

  function categoryClass(category) {
    return {
      error: "bg-red-100 text-red-700 border-red-200",
      pack: "bg-blue-100 text-blue-700 border-blue-200",
      cd2: "bg-emerald-100 text-emerald-700 border-emerald-200",
      file: "bg-zinc-100 text-zinc-700 border-zinc-200",
      system: "bg-zinc-100 text-zinc-500 border-zinc-200",
    }[category || "system"] || "bg-zinc-100 text-zinc-500 border-zinc-200";
  }

  function renderStats(summary) {
    const data = summary || {};
    setText("#logs-stat-total", data.total ?? 0);
    setText("#logs-stat-error", data.error ?? 0);
    setText("#logs-stat-pack", data.pack ?? 0);
    setText("#logs-stat-cd2", data.cd2 ?? 0);
    setText("#logs-stat-file", data.file ?? 0);
    setText("#logs-stat-system", data.system ?? 0);
  }

  function syncFilters() {
    helper().qsa("[data-log-filter]").forEach((button) => {
      const active = button.dataset.logFilter === state.type;
      button.dataset.active = String(active);
      button.className = active
        ? "rounded-lg border border-zinc-900 bg-zinc-900 px-3 py-1.5 text-white"
        : "rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-zinc-600 hover:bg-zinc-50";
    });
  }

  function renderEvents(events) {
    const list = helper().qs("#logs-list");
    helper().clearNode(list);
    if (!events || !events.length) {
      const empty = node("div", "p-8 text-center text-sm font-bold text-zinc-400", "没有匹配的日志记录。");
      list.appendChild(empty);
      setText("#logs-list-summary", "当前筛选没有结果。");
      return;
    }
    setText("#logs-list-summary", `显示 ${events.length} 条记录 · ${state.type === "all" ? "全部类型" : state.type}`);
    events.forEach((event) => {
      const row = node("article", "grid gap-3 p-4 transition hover:bg-zinc-50/70 sm:grid-cols-[132px_minmax(0,1fr)]");
      const time = node("div", "font-mono text-[11px] font-black text-zinc-400", event.time || "--");
      row.appendChild(time);

      const body = node("div", "min-w-0 space-y-2");
      const head = node("div", "flex flex-wrap items-center gap-2");
      const category = node("span", `rounded-full border px-2 py-0.5 text-[10px] font-black ${categoryClass(event.category)}`, event.category_label || event.category || "系统");
      const level = node("span", `rounded-full border px-2 py-0.5 text-[10px] font-black ${levelClass(event.level)}`, event.level || "info");
      const source = node("span", "font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-zinc-400", event.source || "runtime");
      head.append(category, level, source);
      body.appendChild(head);

      const message = node("p", "break-words text-sm font-bold leading-6 text-zinc-800", event.message || "--");
      body.appendChild(message);
      if (event.path) {
        const path = node("p", "truncate rounded-lg border border-zinc-100 bg-zinc-50 px-2 py-1 font-mono text-[11px] font-bold text-zinc-500", event.path);
        path.title = event.path;
        body.appendChild(path);
      }
      row.appendChild(body);
      list.appendChild(row);
    });
  }

  function renderFileOperations(payload) {
    const root = helper().qs("#logs-file-ops");
    helper().clearNode(root);
    const items = (payload && payload.items) || [];
    if (!items.length) {
      root.appendChild(node("div", "rounded-xl border border-zinc-100 bg-zinc-50 px-3 py-3 font-bold text-zinc-400", "暂无文件操作记录"));
      return;
    }
    items.slice(0, 5).forEach((item) => {
      const box = node("div", "rounded-xl border border-zinc-100 bg-zinc-50 px-3 py-2");
      const top = node("div", "flex items-center justify-between gap-2");
      top.append(
        node("span", "font-black text-zinc-800", item.action || "operation"),
        node("span", "font-mono text-[10px] font-black text-zinc-500", item.status || "--")
      );
      const msg = node("p", "mt-1 truncate font-mono text-[11px] font-bold text-zinc-500", item.message || "--");
      msg.title = item.message || "";
      box.append(top, msg);
      root.appendChild(box);
    });
  }

  function renderCurrentStatus(status) {
    const payload = status || state.latestStatus || {};
    const current = payload.current_job;
    const cd2 = payload.cd2_status || {};
    const fileOps = payload.file_operations || {};
    setText("#logs-current-worker", current ? (current.stage_text || current.phase || current.status || "运行中") : "待命");
    setText("#logs-current-cd2", cd2.human || cd2.last_error || (cd2.connected ? "已连接" : "未连接"));
    setText("#logs-current-file", Number(fileOps.active_count || 0) > 0 ? `${fileOps.active_count} 项执行中` : "待命");
  }

  async function loadLogs() {
    if (state.loading) return;
    state.loading = true;
    window.clearTimeout(state.timer);
    const params = new URLSearchParams();
    params.set("type", state.type);
    params.set("limit", String(state.limit));
    if (state.query) params.set("q", state.query);
    try {
      const payload = await helper().fetchJson(`/api/logs?${params.toString()}`);
      renderStats(payload.summary);
      renderEvents(payload.events || []);
      renderFileOperations(payload.file_operations || {});
      setText("#logs-last-refresh", new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    } catch (error) {
      helper().notify(error.message || "日志载入失败", true);
    } finally {
      state.loading = false;
      state.timer = window.setTimeout(loadLogs, 8000);
    }
  }

  function setupEvents() {
    helper().qsa("[data-log-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.type = button.dataset.logFilter || "all";
        syncFilters();
        loadLogs();
      });
    });
    const search = helper().qs("#logs-search");
    if (search) {
      let debounce = null;
      search.addEventListener("input", () => {
        window.clearTimeout(debounce);
        debounce = window.setTimeout(() => {
          state.query = search.value.trim();
          loadLogs();
        }, 220);
      });
    }
    const limit = helper().qs("#logs-limit");
    if (limit) {
      limit.addEventListener("change", () => {
        state.limit = Number(limit.value || 200);
        loadLogs();
      });
    }
    const refresh = helper().qs("#logs-refresh");
    if (refresh) refresh.addEventListener("click", loadLogs);
    window.addEventListener("coreStatusUpdated", (event) => {
      state.latestStatus = event.detail || {};
      renderCurrentStatus(state.latestStatus);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    syncFilters();
    setupEvents();
    loadLogs();
  });
})();
