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

  function normalizeStatusPayload(payload) {
    const status = payload || {};
    const state = status.state || {};
    const active = state.active || status.active || null;
    const progress = progressPercent(active);
    const currentJob = active ? {
      source_path: active.source || active.source_path || "--",
      output_iso: active.target || active.output_iso || "--",
      elapsed: active.duration || active.elapsed || active.elapsed_human || "--",
      progress,
      stage_text: active.stage_text || active.status_label || active.status || "底层引擎执行中..."
    } : null;

    return {
      ...status,
      state,
      active,
      current_job: status.current_job || currentJob,
      cd2_status: status.cd2_status || state.cd2_status || {}
    };
  }

  return { qs, qsa, clearNode, setText, fetchJson, notify, normalizeStatusPayload };
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
          globalBadge.innerText = "PACKING";
          globalBadge.className = "ml-auto bg-blue-50 text-blue-600 border border-blue-200 text-[9px] font-extrabold px-2 py-0.5 rounded-full animate-pulse";
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
