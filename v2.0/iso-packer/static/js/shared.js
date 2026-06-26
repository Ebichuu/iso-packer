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
      const task = item.cd2_source_task || {};
      const progress = Number(task.percent ?? item.progress ?? 0);
      return {
        source_path: source || item.source || "--",
        output_iso: item.target || item.output_iso || "--",
        elapsed: (item.timings && (item.timings.human || item.timings.summary)) || "--",
        progress: Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0,
        status,
        phase: status,
        stage_text: item.error || item.status_label || status,
        current: task.current || task.current_bytes || item.last_size || 0,
        total: task.total || task.total_bytes || item.size || 0
      };
    }
    return null;
  }

  function normalizeStatusPayload(payload) {
    const status = payload || {};
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

    return {
      ...status,
      state,
      active,
      current_job: status.current_job || currentJob,
      cd2_status: status.cd2_status || state.cd2_status || {}
    };
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

  return { qs, qsa, clearNode, setText, fetchJson, notify, normalizeStatusPayload, formatBytes };
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

  async function executePollStep() {
    try {
      const response = await fetch("/api/status", { signal: AbortSignal.timeout(15000) });
      if (response.status === 401) {
        window.location.href = "/login";
        return;
      }

      const statusData = IsoPacker.normalizeStatusPayload(await response.json());
      nextPollDelay = statusData.current_job ? STATUS_POLL_ACTIVE_MS : STATUS_POLL_IDLE_MS;
      const globalBadge = document.getElementById("global-worker-badge");
      if (globalBadge) {
        if (statusData.current_job) {
          const phase = String(statusData.current_job.phase || statusData.current_job.status || "").toLowerCase();
          const isWaiting = phase.startsWith("waiting") || phase === "receiving";
          const isTransfer = phase === "transfer" || phase === "transferring";
          const isVerify = phase === "verify" || phase === "verifying" || phase === "validating" || phase === "checking" || phase === "transfer_verify";
          const isFinalize = phase === "finalize" || phase === "finalizing" || phase === "refresh_cd2_dir" || phase === "refreshing_cd2_dir";
          globalBadge.innerText = isWaiting ? "WAITING" : isTransfer ? "TRANSFER" : isVerify ? "VERIFY" : isFinalize ? "FINAL" : "PACKING";
          globalBadge.className = isWaiting
            ? "ml-auto bg-amber-50 text-amber-700 border border-amber-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse"
            : isTransfer
              ? "ml-auto bg-emerald-50 text-emerald-700 border border-emerald-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse"
              : isVerify || isFinalize
                ? "ml-auto bg-amber-50 text-amber-700 border border-amber-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse"
                : "ml-auto bg-blue-50 text-blue-600 border border-blue-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse";
        } else {
          globalBadge.innerText = "IDLE";
          globalBadge.className = "ml-auto bg-zinc-100 text-zinc-400 border border-zinc-200 text-[9px] font-bold px-2 py-0.5 rounded-full";
        }
      }

      window.dispatchEvent(new CustomEvent("coreStatusUpdated", { detail: statusData }));
    } catch (error) {
      nextPollDelay = STATUS_POLL_ERROR_MS;
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
