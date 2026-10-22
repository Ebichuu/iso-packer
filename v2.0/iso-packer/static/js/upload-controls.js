(function () {
  const ENDPOINT = "/api/cd2/upload-control";
  const TIME = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
  const helper = () => window.IsoPacker;

  function parseWindows(text, enabled) {
    const lines = String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines.length > 48) throw new Error("每天最多设置 48 个暂停窗口。");
    const windows = lines.map((line) => {
      const match = /^(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})$/.exec(line);
      if (!match || !TIME.test(match[1]) || !TIME.test(match[2])) throw new Error("暂停窗口使用 HH:MM-HH:MM，时间范围为 00:00–23:59。");
      if (match[1] === match[2]) throw new Error("暂停窗口开始和结束时间不能相同。");
      return { start: match[1], end: match[2] };
    });
    if (enabled && !windows.length) throw new Error("启用每日暂停窗口前，请至少添加一个时间段。");
    return windows.filter((item, index) => windows.findIndex((other) => item.start === other.start && item.end === other.end) === index);
  }

  function beijingInputValue(timestamp) {
    return new Date(timestamp + 8 * 3600000).toISOString().slice(0, 16);
  }

  function pauseUntilIso(value, now = Date.now()) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value || "")) throw new Error("请选择暂停结束的北京时间。");
    const timestamp = Date.parse(`${value}:00+08:00`);
    if (!Number.isFinite(timestamp) || beijingInputValue(timestamp) !== value) throw new Error("暂停结束日期或时间无效。");
    if (timestamp <= now) throw new Error("恢复时间必须晚于当前北京时间。");
    return `${value}:00+08:00`;
  }

  function formatBeijing(value) {
    if (!value) return "";
    const timestamp = Date.parse(value);
    return Number.isFinite(timestamp) ? `${beijingInputValue(timestamp).replace("T", " ")}（北京时间）` : String(value);
  }

  function statusSummary(control) {
    if (control.effective_paused) return control.remote_pause_confirmed
      ? "已阻止本项目转存，CD2 全部上传暂停已确认"
      : "已阻止本项目转存，CD2 暂停待确认";
    return control.last_error ? "暂停策略已解除，CD2 任务状态待确认" : "当前允许本项目转存与上传";
  }

  function setupControls(root) {
    const status = root.querySelector("[data-upload-status]");
    const detail = root.querySelector("[data-upload-detail]");
    const errorNode = root.querySelector("[data-upload-error]");
    const until = root.querySelector("[data-upload-until]");
    const refreshButton = root.querySelector("[data-upload-refresh]");
    const buttons = Array.from(root.querySelectorAll("[data-upload-action]"));
    let control = null;
    let generation = 0;
    let busy = false;
    let loading = false;
    let available = false;
    let serviceHealthy = true;

    function updateButtons() {
      buttons.forEach((button) => { button.disabled = busy || !available || !serviceHealthy; });
      refreshButton.disabled = busy || loading;
      root.setAttribute("aria-busy", String(busy || loading));
    }

    function showError(message) {
      errorNode.textContent = message || "";
      errorNode.classList.toggle("hidden", !message);
    }

    function render(value) {
      if (!value || value.scope !== "all_cd2_uploads") throw new Error("服务未返回可确认的 CD2 全部上传控制状态。");
      control = value;
      available = true;
      status.textContent = statusSummary(value);
      const reasons = { manual: "手动暂停", schedule: "每日暂停窗口", manual_and_schedule: "手动暂停与每日窗口", none: "无暂停规则生效" };
      const parts = [reasons[value.reason] || "状态待确认"];
      if (value.manual_paused) parts.push(value.manual_until ? `手动暂停至 ${formatBeijing(value.manual_until)}` : "手动暂停至主动解除");
      const windows = Array.isArray(value.windows) ? value.windows : [];
      parts.push(value.schedule_enabled ? `已保存的每日窗口：${windows.map((item) => `${item.start}–${item.end}${item.end < item.start ? "（跨午夜）" : ""}`).join("、") || "未配置"}` : "每日窗口未启用");
      if (value.next_transition) parts.push(`下次策略变化：${formatBeijing(value.next_transition)}`);
      if (value.effective_paused && Number(value.pending_upload_count) > 0) parts.push(`仍待确认暂停 ${Number(value.pending_upload_count)} 项`);
      if (value.queue_complete === false) parts.push("上传队列读取不完整，远端状态待确认");
      parts.push("时间均按北京时间执行");
      detail.textContent = parts.join(" · ");
      showError(value.last_error || "");
      if (!serviceHealthy) {
        status.textContent = "后台服务或连接异常，上传状态待确认";
        showError("等待后台服务恢复后重新读取。");
      }
      updateButtons();
    }

    async function refresh(showToast = false) {
      if (busy || loading) return;
      const request = ++generation;
      loading = true;
      updateButtons();
      try {
        const payload = await helper().fetchJson(ENDPOINT, { signal: AbortSignal.timeout(20000) });
        if (request !== generation) return;
        render(payload.upload_control);
      } catch (error) {
        if (request !== generation) return;
        available = false;
        status.textContent = "上传控制状态暂不可确认";
        detail.textContent = control ? `上次状态：${statusSummary(control)}。等待重新读取。` : "请检查已保存的 CD2 连接配置和后台服务状态。";
        showError(error.message || "读取上传控制状态失败。");
        if (showToast) helper().notify(error.message || "读取上传控制状态失败。", true);
      } finally {
        if (request === generation) loading = false;
        updateButtons();
      }
    }

    async function applyAction(action) {
      if (busy || !available || !serviceHealthy) return;
      let body;
      try {
        body = { action: action === "resume" ? "resume" : "pause" };
        if (action === "pause-until") body.until = pauseUntilIso(until.value);
      } catch (error) {
        helper().notify(error.message, true);
        until.focus();
        return;
      }
      ++generation;
      loading = false;
      busy = true;
      updateButtons();
      try {
        const payload = await helper().fetchJson(ENDPOINT, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body), signal: AbortSignal.timeout(20000),
        });
        render(payload.upload_control);
        helper().notify(payload.message || statusSummary(payload.upload_control), Boolean(payload.upload_control.last_error));
      } catch (error) {
        available = false;
        status.textContent = "操作结果待确认，请刷新状态";
        showError(error.message || "上传控制操作失败。");
        helper().notify(error.message || "上传控制操作失败。", true);
      } finally {
        busy = false;
        updateButtons();
      }
    }

    buttons.forEach((button) => button.addEventListener("click", () => applyAction(button.dataset.uploadAction)));
    refreshButton.addEventListener("click", () => refresh(true));
    ["input", "change"].forEach((name) => until.addEventListener(name, (event) => event.stopPropagation()));
    window.addEventListener("coreStatusUpdated", (event) => {
      const healthy = !event.detail?.service_health || event.detail.service_health.state === "healthy";
      const recovered = healthy && !serviceHealthy;
      serviceHealthy = healthy;
      if (!healthy) {
        status.textContent = "后台服务或连接异常，上传状态待确认";
        showError(event.detail.service_health.detail || "等待后台服务恢复后重新读取。");
      }
      updateButtons();
      if (recovered) refresh();
    });
    async function poll() {
      if (!document.hidden && serviceHealthy) await refresh();
      window.setTimeout(poll, 10000);
    }
    poll();
  }

  function setupSchedule(section) {
    const form = section.closest("form");
    const field = form.elements.cd2_upload_pause_windows_text;
    const enabled = form.elements.cd2_upload_schedule_enabled;
    const rows = section.querySelector("[data-upload-window-rows]");
    const errorNode = section.querySelector("[data-upload-window-error]");
    const add = section.querySelector("[data-upload-window-add]");

    function changed() {
      field.value = Array.from(rows.children).map((row) => {
        const start = row.querySelector("[data-window-start]").value;
        const end = row.querySelector("[data-window-end]").value;
        row.querySelector("[data-window-overnight]").textContent = TIME.test(start) && TIME.test(end) && end < start ? "结束于次日" : "";
        return start || end ? `${start}-${end}` : "";
      }).filter(Boolean).join("\n");
      errorNode.classList.add("hidden");
      form.dispatchEvent(new Event("input", { bubbles: true }));
      add.disabled = rows.children.length >= 48;
    }

    function addRow(value = {}) {
      if (rows.children.length >= 48) return;
      const row = document.createElement("div");
      row.className = "flex flex-wrap items-end gap-2 rounded-lg border border-zinc-200 bg-white p-3";
      row.innerHTML = '<label class="min-w-0 flex-1 text-[11px] font-semibold text-zinc-700">开始（北京时间）<input type="time" data-window-start step="60" class="mt-1 block min-h-10 w-full rounded-lg border border-zinc-200 px-2 py-1 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-zinc-900"></label><label class="min-w-0 flex-1 text-[11px] font-semibold text-zinc-700">结束（北京时间）<input type="time" data-window-end step="60" class="mt-1 block min-h-10 w-full rounded-lg border border-zinc-200 px-2 py-1 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-zinc-900"></label><button type="button" data-window-remove class="min-h-10 rounded-lg border border-zinc-200 px-3 py-2 text-[11px] font-bold text-zinc-600 hover:bg-zinc-50 focus:outline-none focus:ring-2 focus:ring-zinc-900">移除</button><span data-window-overnight class="w-full text-[10px] text-amber-700"></span>';
      row.querySelector("[data-window-start]").value = value.start || "";
      row.querySelector("[data-window-end]").value = value.end || "";
      row.addEventListener("input", changed);
      row.querySelector("[data-window-remove]").addEventListener("click", () => { row.remove(); changed(); });
      rows.appendChild(row);
      add.disabled = rows.children.length >= 48;
      row.querySelector("[data-window-overnight]").textContent = value.end < value.start ? "结束于次日" : "";
    }

    try {
      parseWindows(field.value, false).forEach(addRow);
      section.querySelector("[data-upload-windows-fallback]").classList.add("hidden");
    } catch (error) {
      errorNode.textContent = error.message;
      errorNode.classList.remove("hidden");
      add.disabled = true;
      return;
    }
    add.addEventListener("click", () => { addRow(); changed(); rows.lastElementChild?.querySelector("input")?.focus(); });
    form.addEventListener("submit", (event) => {
      try {
        const windows = parseWindows(field.value, enabled.checked);
        field.value = windows.map((item) => `${item.start}-${item.end}`).join("\n");
      } catch (error) {
        event.preventDefault();
        event.stopImmediatePropagation();
        errorNode.textContent = error.message;
        errorNode.classList.remove("hidden");
        helper().notify(error.message, true);
        (rows.querySelector("input") || add).focus();
      }
    }, true);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("cd2-upload-manual-form")?.addEventListener("submit", (event) => event.preventDefault());
    document.querySelectorAll("[data-upload-control]").forEach(setupControls);
    document.querySelectorAll("[data-upload-schedule]").forEach(setupSchedule);
  });
})();
