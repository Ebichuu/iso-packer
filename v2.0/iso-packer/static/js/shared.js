const IsoPacker = (() => {
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function clearNode(node) {
    if (!node) return;
    node.replaceChildren();
  }

  function setText(node, value) {
    if (!node) return;
    node.textContent = value == null || value === "" ? "--" : String(value);
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || `请求失败: ${response.status}`);
    }
    return payload;
  }

  function notify(message, isError = false) {
    const text = String(message || (isError ? "操作失败" : "操作完成"));
    const toast = qs("#app-toast");
    if (toast) {
      toast.textContent = text;
      toast.classList.toggle("is-error", Boolean(isError));
      toast.classList.add("is-visible");
      window.clearTimeout(notify.timer);
      notify.timer = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
      return;
    }
    if (isError) console.error(text);
    else console.info(text);
  }

  function progressPercent(active) {
    const progress = active && active.progress;
    if (!progress) return 0;
    if (typeof progress === "number") return progress;
    const raw = progress.percent ?? progress.progress ?? progress.total_progress ?? 0;
    const value = Number(raw);
    return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  }

  function waitingJobFromItems(items) {
    const waitingStatuses = new Set([
      "waiting_cd2_pull",
      "waiting_cd2_upload",
      "waiting_partial",
      "waiting_stable",
      "receiving",
      "ready"
    ]);
    for (const [source, item] of Object.entries(items || {})) {
      const status = item && item.status;
      if (!waitingStatuses.has(status)) continue;
      const task = status === "waiting_cd2_upload"
        ? (item.cd2_upload || {})
        : (item.cd2_source_task || {});
      const progress = Number(task.percent ?? item.progress ?? 0);
      const uploadText = task.human || task.summary || task.status || "";
      return {
        source_path: source || item.source || "--",
        output_iso: item.target || item.output_iso || "--",
        elapsed: (item.timings && (item.timings.human || item.timings.summary)) || "--",
        progress: Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0,
        status,
        phase: status,
        stage_text: uploadText || item.error || item.status_label || status,
        current: task.current || task.current_bytes || item.last_size || 0,
        total: task.total || task.total_bytes || item.size || 0,
        failure_code: item.failure_code || "",
        can_recheck: item.can_recheck === true,
        can_confirm_upload: item.can_confirm_upload === true
      };
    }
    return null;
  }

  function serviceHealth(worker, connectionError = false) {
    if (connectionError) {
      return { state: "disconnected", label: "数据更新中断", detail: "暂时无法更新状态，页面保留上次数据并将自动重试。", tone: "amber" };
    }
    if (!worker) return { state: "healthy" };
    if (worker.alive === false) {
      return { state: "offline", label: "后台服务离线", detail: "当前显示上次保存的数据，任务运行状态暂不可确认。请重启服务后查看。", tone: "red" };
    }
    if (worker.startup_complete === false) {
      return { state: "recovering", label: "后台服务恢复中", detail: "正在恢复上次任务，暂时保留历史数据。恢复完成后会自动更新。", tone: "amber" };
    }
    if (worker.snapshot_stale === true) {
      const age = Number(worker.snapshot_age_seconds);
      const elapsed = Number.isFinite(age) && age >= 0 ? `，距上次更新 ${Math.floor(age)} 秒` : "";
      return { state: "stale", label: "数据更新延迟", detail: `当前显示上次数据${elapsed}，任务运行状态待更新确认。`, tone: "amber" };
    }
    return { state: "healthy" };
  }

  function normalizeStatusPayload(payload) {
    const status = payload || {};
    const health = serviceHealth(status.worker, status.connection_error === true);
    const currentStatusAvailable = health.state === "healthy";
    const state = status.state || {};
    const active = state.active || status.active || null;
    const progress = progressPercent(active);
    const activeProgress = (active && active.progress) || {};
    const currentJob = active ? {
      source_path: active.source || active.source_path || "--",
      output_iso: active.target || active.output_iso || "--",
      elapsed: active.duration || active.elapsed || active.elapsed_human || "--",
      progress,
      status: active.status || "running",
      phase: activeProgress.phase || active.phase || active.status || "packing",
      current: activeProgress.current || 0,
      total: activeProgress.total || 0,
      stage_text: activeProgress.stage_text || activeProgress.label || active.stage_text || active.status_label || active.status || "底层引擎执行中..."
    } : waitingJobFromItems(state.items);

    const fileOperations = status.file_operations || { active_count: 0, items: [] };
    return {
      ...status,
      state,
      active: currentStatusAvailable ? active : null,
      current_job: currentStatusAvailable ? (status.current_job || currentJob) : null,
      service_health: health,
      cd2_status: status.cd2_status || state.cd2_status || {},
      file_operations: fileOperations,
      has_active_file_operation: currentStatusAvailable && Number(fileOperations.active_count || 0) > 0
    };
  }

  function presentServiceHealth(health) {
    const issue = health && health.state !== "healthy";
    let notice = qs("#service-health-notice");
    if (!notice && issue) {
      const content = qs("main > div");
      if (content) {
        notice = document.createElement("div");
        notice.id = "service-health-notice";
        notice.setAttribute("role", "status");
        notice.setAttribute("aria-live", "polite");
        content.prepend(notice);
      }
    }
    if (notice) {
      notice.hidden = !issue;
      if (issue) {
        notice.className = `rounded-xl border px-4 py-3 text-xs font-semibold leading-6 ${health.tone === "red" ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-800"}`;
        notice.textContent = `${health.label}：${health.detail}`;
      }
    }
    if (!issue) return;
    const badge = qs("#global-worker-badge");
    if (badge) {
      badge.innerText = health.label;
      badge.title = health.detail;
      badge.className = `ml-auto border text-[9px] font-bold px-2 py-0.5 rounded-full ${health.tone === "red" ? "border-red-200 bg-red-50 text-red-700" : "border-amber-200 bg-amber-50 text-amber-700"}`;
    }
    for (const id of ["workspace-worker-state", "pipeline-primary-status", "pipeline-progress-meta"]) {
      setText(qs(`#${id}`), health.label);
    }
    for (const id of ["workspace-worker-detail", "pipeline-current-action", "pipeline-stage-log", "index-worker-note"]) {
      setText(qs(`#${id}`), health.detail);
    }
    setText(qs("#pipeline-status-kicker"), "服务状态");
    setText(qs("#pipeline-progress-text"), "--");
    setText(qs("#index-active-count"), "--");
    setText(qs("#pipeline-next-step"), health.state === "offline" ? "重启服务后查看任务状态" : "等待状态自动更新");
    const dot = qs("#workspace-worker-dot");
    if (dot) dot.className = `h-2.5 w-2.5 rounded-full ${health.tone === "red" ? "bg-red-500" : "bg-amber-500"}`;
    const stateLabel = qs("#workspace-worker-state");
    if (stateLabel) stateLabel.className = `font-mono text-sm ${health.tone === "red" ? "text-red-700" : "text-amber-700"}`;
    const cancel = qs("#pipeline-cancel-pack");
    if (cancel) {
      cancel.disabled = true;
      cancel.classList.add("hidden");
    }
  }

  function formatBytes(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = value;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex += 1;
    }
    const digits = unitIndex === 0 || size >= 100 ? 0 : size >= 10 ? 1 : 2;
    return `${size.toFixed(digits)} ${units[unitIndex]}`;
  }

  return { qs, qsa, clearNode, setText, fetchJson, notify, normalizeStatusPayload, presentServiceHealth, formatBytes };
})();

window.IsoPacker = IsoPacker;

let isLoopRunning = false;
const STATUS_POLL_ACTIVE_MS = 2000;
const STATUS_POLL_IDLE_MS = 6000;
const STATUS_POLL_ERROR_MS = 8000;

function startSerializedSystemLoop() {
  if (isLoopRunning) return;
  isLoopRunning = true;
  let nextPollDelay = STATUS_POLL_IDLE_MS;
  let lastStatus = {};

  async function executePollStep() {
    let reportedWorker = null;
    try {
      const response = await fetch("/api/status", { signal: AbortSignal.timeout(15000) });
      if (response.status === 401) {
        window.location.href = "/login";
        return;
      }

      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        reportedWorker = payload.worker || null;
        throw new Error(payload.message || `请求失败: ${response.status}`);
      }
      lastStatus = payload;
      const statusData = IsoPacker.normalizeStatusPayload(payload);
      const hasActiveFileOperation = statusData.has_active_file_operation;
      nextPollDelay = (statusData.current_job || hasActiveFileOperation) ? STATUS_POLL_ACTIVE_MS : STATUS_POLL_IDLE_MS;
      const globalBadge = document.getElementById("global-worker-badge");
      if (globalBadge) {
        globalBadge.removeAttribute("title");
        if (statusData.current_job) {
          const phase = String(statusData.current_job.phase || statusData.current_job.status || "").toLowerCase();
          const isWaiting = phase.startsWith("waiting") || phase === "receiving";
          const isUpload = phase === "waiting_cd2_upload";
          const isTransfer = phase === "transfer" || phase === "transferring";
          const isVerify = phase === "verify" || phase === "verifying" || phase === "validating" || phase === "checking" || phase === "transfer_verify";
          const isFinalize = phase === "finalize" || phase === "finalizing" || phase === "refresh_cd2_dir" || phase === "refreshing_cd2_dir";
          globalBadge.innerText = isUpload ? "UPLOAD" : isWaiting ? "WAITING" : isTransfer ? "TRANSFER" : isVerify ? "VERIFY" : isFinalize ? "FINAL" : "PACKING";
          globalBadge.className = isUpload
            ? "ml-auto bg-emerald-50 text-emerald-700 border border-emerald-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse"
            : isWaiting
            ? "ml-auto bg-amber-50 text-amber-700 border border-amber-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse"
            : isTransfer
              ? "ml-auto bg-emerald-50 text-emerald-700 border border-emerald-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse"
              : isVerify || isFinalize
                ? "ml-auto bg-amber-50 text-amber-700 border border-amber-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse"
                : "ml-auto bg-blue-50 text-blue-600 border border-blue-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse";
        } else if (hasActiveFileOperation) {
          globalBadge.innerText = "COPYING";
          globalBadge.className = "ml-auto bg-sky-50 text-sky-700 border border-sky-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse";
        } else {
          globalBadge.innerText = "IDLE";
          globalBadge.className = "ml-auto bg-zinc-100 text-zinc-400 border border-zinc-200 text-[9px] font-bold px-2 py-0.5 rounded-full";
        }
      }

      window.dispatchEvent(new CustomEvent("coreStatusUpdated", { detail: statusData }));
      IsoPacker.presentServiceHealth(statusData.service_health);
    } catch (error) {
      nextPollDelay = STATUS_POLL_ERROR_MS;
      const reportedIssue = reportedWorker && (reportedWorker.alive === false || reportedWorker.startup_complete === false || reportedWorker.snapshot_stale === true);
      const statusData = IsoPacker.normalizeStatusPayload({ ...lastStatus, worker: reportedWorker || lastStatus.worker, connection_error: !reportedIssue });
      window.dispatchEvent(new CustomEvent("coreStatusUpdated", { detail: statusData }));
      IsoPacker.presentServiceHealth(statusData.service_health);
      console.error("状态同步失败，稍后自动重试", error);
    } finally {
      setTimeout(executePollStep, nextPollDelay);
    }
  }

  executePollStep();
}

function setupMobileMenu() {
  const button = document.querySelector("[data-mobile-menu-toggle]");
  const sidebar = document.getElementById("sidebar");
  if (!button || !sidebar) return;

  function paintState() {
    const isOpen = !sidebar.classList.contains("-translate-x-full");
    button.setAttribute("aria-expanded", String(isOpen));
    button.setAttribute("aria-label", isOpen ? "关闭导航菜单" : "打开导航菜单");
  }

  button.addEventListener("click", () => {
    sidebar.classList.toggle("-translate-x-full");
    paintState();
  });
  paintState();
}

document.addEventListener("DOMContentLoaded", () => {
  startSerializedSystemLoop();
  setupMobileMenu();
});
