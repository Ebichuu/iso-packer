(function () {
  const helper = () => window.IsoPacker;
  const state = {
    candidates: [],
    pullConfigured: false,
    pullEnabled: false,
    pullGuardEnabled: false
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.innerText = value == null || value === "" ? "--" : String(value);
  }

  function showFeedback(message, isError = false) {
    const feedback = document.getElementById("workspace-feedback");
    if (!feedback) {
      helper().notify(message, isError);
      return;
    }
    feedback.textContent = String(message || (isError ? "操作失败" : "操作完成"));
    feedback.className = isError
      ? "rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs font-bold text-red-700"
      : "rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs font-bold text-emerald-800";
    window.clearTimeout(showFeedback.timer);
    showFeedback.timer = window.setTimeout(() => feedback.classList.add("hidden"), 3600);
  }

  function setWorkerVisual(isActive) {
    const dot = document.getElementById("workspace-worker-dot");
    const stateLabel = document.getElementById("workspace-worker-state");
    if (dot) {
      dot.className = isActive
        ? "h-2.5 w-2.5 rounded-full bg-blue-500 shadow-[0_0_0_5px_rgba(59,130,246,0.12)]"
        : "h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_0_5px_rgba(16,185,129,0.12)]";
    }
    if (stateLabel) {
      stateLabel.textContent = isActive ? "运行中" : "待命";
      stateLabel.className = isActive
        ? "font-mono text-sm text-blue-700"
        : "font-mono text-sm text-emerald-700";
    }
  }

  function renderPipeline(status) {
    const widget = document.getElementById("workspace-pipeline-widget");
    const job = status && status.current_job;
    if (!widget) return;

    const isActive = Boolean(job);
    const progress = Math.max(0, Math.min(100, Number((job && job.progress) || 0)));
    setWorkerVisual(isActive);
    setText("workspace-worker-detail", isActive ? "封装引擎正在执行，下面显示当前任务流。" : "当前没有封装任务，工作台处于待命状态。");
    setText("pipeline-src", isActive ? job.source_path : "--");
    setText("pipeline-out", isActive ? job.output_iso : "--");
    setText("pipeline-stream-elapsed", isActive ? `耗时：${job.elapsed || "--"}` : "耗时：--");
    setText("pipeline-progress-text", `${progress.toFixed(progress % 1 ? 1 : 0)}%`);
    setText("pipeline-stage-log", isActive ? (job.stage_text || "底层引擎执行中...") : "等待指令流调起...");

    const bar = document.getElementById("pipeline-progress-bar");
    if (bar) {
      bar.style.width = `${progress}%`;
      bar.className = isActive
        ? "h-full rounded-full bg-blue-500 transition-all duration-300"
        : "h-full rounded-full bg-emerald-500 transition-all duration-300";
    }
  }

  window.addEventListener("coreStatusUpdated", (event) => {
    renderPipeline(event.detail || {});
  });

  function candidateState(candidate) {
    if (candidate.pull_state === "active") {
      return { text: "处理中", className: "bg-blue-50 text-blue-600 border-blue-200 font-bold" };
    }
    if (candidate.pull_state === "done") {
      return { text: "已完成", className: "bg-emerald-50 text-emerald-700 border-emerald-200 font-bold" };
    }
    if (candidate.pull_state === "recent_failure") {
      return { text: "近期失败", className: "bg-red-50 text-red-600 border-red-200 font-bold" };
    }
    if (candidate.skip_reason) {
      return { text: candidate.pull_status_label || "已跳过", className: "bg-zinc-100 text-zinc-500 border-zinc-200" };
    }
    return { text: candidate.pull_status_label || "可拉取", className: "bg-emerald-50 text-emerald-700 border-emerald-200 font-bold" };
  }

  function candidateSize(candidate) {
    const size = Number(candidate.size || 0);
    if (!Number.isFinite(size) || size <= 0) return "--";
    if (size >= 1024 ** 4) return `${(size / 1024 ** 4).toFixed(2)} TB`;
    if (size >= 1024 ** 3) return `${(size / 1024 ** 3).toFixed(1)} GB`;
    if (size >= 1024 ** 2) return `${(size / 1024 ** 2).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }

  function renderStateCard(kind, title, body) {
    const tone = {
      loading: "border-zinc-200 bg-zinc-50 text-zinc-500",
      empty: "border-zinc-200 bg-white text-zinc-500",
      error: "border-red-200 bg-red-50 text-red-700"
    }[kind] || "border-zinc-200 bg-white text-zinc-500";

    return `
      <div class="p-6">
        <div class="rounded-xl border ${tone} p-5 text-center">
          <div class="font-mono text-[10px] font-black uppercase tracking-[0.18em]">${escapeHtml(title)}</div>
          <p class="mx-auto mt-2 max-w-xl text-xs font-medium leading-5">${escapeHtml(body)}</p>
        </div>
      </div>
    `;
  }

  function updateSelectedCount() {
    const selectedBoxes = Array.from(document.querySelectorAll('#workspace-candidates-container input[name="candidate_path"]:checked'));
    const selected = selectedBoxes.length;
    const pullable = selectedBoxes.filter((checkbox) => checkbox.dataset.canPull === "true").length;
    const clearable = selectedBoxes.filter((checkbox) => checkbox.dataset.canClear === "true").length;
    const selectedNode = document.getElementById("workspace-selected-count");
    const batchButton = document.querySelector("[data-batch-pull]");
    const batchButtonLabel = document.querySelector("[data-batch-pull-label]");
    const clearButton = document.querySelector("[data-batch-clear]");
    if (selectedNode) selectedNode.textContent = String(selected);
    if (batchButton) {
      batchButton.disabled = pullable === 0;
      batchButton.title = pullButtonTitle();
    }
    if (batchButtonLabel) batchButtonLabel.textContent = pullButtonText();
    if (clearButton) clearButton.disabled = clearable === 0;
  }

  function pullButtonText() {
    if (state.pullGuardEnabled) return "本地测试禁用拉取";
    if (!state.pullConfigured) return "拉取未启用";
    return "拉取选中";
  }

  function pullButtonTitle() {
    if (state.pullGuardEnabled) return "当前本地预览已禁用真实 CD2 拉取，只允许只读或 mock 验收";
    if (!state.pullConfigured) return "需要先在设置页开启手动拉取或自动拉取";
    return "提交已勾选的可拉取候选";
  }

  function updateCandidateSummary(payload, candidates) {
    const summary = payload.summary || {};
    const total = Number.isFinite(Number(summary.total)) ? Number(summary.total) : candidates.length;
    const pullable = Number.isFinite(Number(summary.pullable)) ? Number(summary.pullable) : candidates.filter((item) => !item.skip_reason).length;
    const skipped = Number.isFinite(Number(summary.skipped)) ? Number(summary.skipped) : candidates.filter((item) => item.skip_reason).length;

    setText("workspace-candidate-total", total);
    const summaryText = document.getElementById("candidate-summary-text");
    if (summaryText) {
      if (payload.message && !candidates.length) {
        summaryText.textContent = payload.message;
      } else {
        summaryText.textContent = `共 ${total} 个候选，${pullable} 个可拉取，${skipped} 个被策略跳过。`;
      }
    }
  }

  function renderCandidates(payload) {
    const container = document.getElementById("workspace-candidates-container");
    if (!container) return;

    const candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
    state.candidates = candidates;
    state.pullConfigured = payload.pull_configured === true || payload.manual_pull_enabled === true || payload.auto_pull_enabled === true;
    state.pullGuardEnabled = payload.pull_guard_enabled === true;
    state.pullEnabled = payload.pull_enabled === true && !state.pullGuardEnabled;
    updateCandidateSummary(payload, candidates);

    if (!candidates.length) {
      container.innerHTML = renderStateCard("empty", "无候选", payload.message || "没有扫描到待处理的 CD2 候选原盘。");
      updateSelectedCount();
      return;
    }

    container.innerHTML = candidates.map((candidate) => {
      const viewState = candidateState(candidate);
      const canPull = state.pullEnabled && !candidate.skip_reason;
      const canClear = Boolean(candidate.pull_state && candidate.pull_state !== "new" && candidate.pull_state !== "active");
      const disabled = canPull || canClear ? "" : " disabled";
      const rowTone = canPull || canClear ? "hover:bg-zinc-50" : "bg-zinc-50/60";
      const clearButton = canClear
        ? `<button type="button" data-clear-candidate-record="${escapeHtml(candidate.path)}" class="rounded-lg border border-zinc-200 bg-white px-2 py-1 font-mono text-[9px] font-black text-zinc-600 transition hover:bg-zinc-50 focus:outline-none focus:ring-2 focus:ring-zinc-900 focus:ring-offset-2">清除记录</button>`
        : "";
      return `
        <div class="flex items-center justify-between gap-4 p-3.5 transition ${rowTone}">
          <label class="flex min-w-0 cursor-pointer items-center gap-3">
            <input type="checkbox" name="candidate_path" value="${escapeHtml(candidate.path)}" data-can-pull="${canPull ? "true" : "false"}" data-can-clear="${canClear ? "true" : "false"}" class="h-4 w-4 shrink-0 rounded border-zinc-300 text-emerald-600 focus:ring-emerald-500"${disabled} aria-label="选择 ${escapeHtml(candidate.name || candidate.path || "候选原盘")}">
            <span class="min-w-0 space-y-1">
              <span class="block truncate font-mono text-xs font-bold text-zinc-800" title="${escapeHtml(candidate.name)}">${escapeHtml(candidate.name || "--")}</span>
              <span class="flex flex-wrap gap-x-2 gap-y-1 font-mono text-[10px] text-zinc-400">
                <span class="max-w-[420px] truncate" title="${escapeHtml(candidate.path)}">路径: ${escapeHtml(candidate.path || "--")}</span>
                <span>类型: ${escapeHtml(candidate.disc_type || "--")}</span>
                <span>大小: ${escapeHtml(candidateSize(candidate))}</span>
              </span>
            </span>
          </label>
          <span class="flex shrink-0 items-center gap-2">
            <span class="rounded-full border px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.14em] ${viewState.className}" title="${escapeHtml(candidate.skip_reason || candidate.pull_error || "")}">${escapeHtml(viewState.text)}</span>
            ${clearButton}
          </span>
        </div>
      `;
    }).join("");
    updateSelectedCount();
  }

  async function fetchCandidatesQueue(force = false) {
    const container = document.getElementById("workspace-candidates-container");
    const refreshButton = document.querySelector("[data-refresh-candidates]");
    if (!container) return;

    container.innerHTML = renderStateCard("loading", "读取中", "正在读取 CD2 远程候选目录。");
    setText("candidate-summary-text", force ? "正在强制刷新远程候选目录。" : "正在读取远程候选目录。");
    if (refreshButton) {
      refreshButton.disabled = true;
      refreshButton.classList.add("opacity-60");
    }

    try {
      const payload = await helper().fetchJson(`/api/cd2/remote-candidates?force=${force ? "1" : "0"}&_=${Date.now()}`);
      renderCandidates(payload);
    } catch (error) {
      setText("workspace-candidate-total", "--");
      setText("candidate-summary-text", "CD2 候选同步失败，请检查 CD2 登录信息和目录配置。");
      container.innerHTML = renderStateCard("error", "同步失败", error.message || "远程候选同步失败，请检查 CD2 API 与挂载配置。");
      updateSelectedCount();
    } finally {
      if (refreshButton) {
        refreshButton.disabled = false;
        refreshButton.classList.remove("opacity-60");
      }
    }
  }

  async function submitRemotePull(path) {
    const form = new FormData();
    form.set("path", path);
    return helper().fetchJson("/api/cd2/pull", { method: "POST", body: form });
  }

  async function clearRemoteRecord(path) {
    const form = new FormData();
    form.set("path", path);
    return helper().fetchJson("/api/cd2/pull-record", { method: "POST", body: form });
  }

  async function batchAction() {
    const batchButton = document.querySelector("[data-batch-pull]");
    const batchButtonLabel = document.querySelector("[data-batch-pull-label]");
    const checkedBoxes = document.querySelectorAll('#workspace-candidates-container input[name="candidate_path"]:checked');
    const paths = Array.from(checkedBoxes)
      .filter((checkbox) => checkbox.dataset.canPull === "true")
      .map((checkbox) => checkbox.value)
      .filter(Boolean);
    if (!paths.length) {
      showFeedback("请至少勾选一部可拉取的候选原盘。", true);
      return;
    }

    const originalText = batchButtonLabel ? batchButtonLabel.textContent : "";
    if (batchButton) {
      batchButton.disabled = true;
    }
    if (batchButtonLabel) batchButtonLabel.textContent = "提交中...";

    let okCount = 0;
    const errors = [];
    for (const path of paths) {
      try {
        await submitRemotePull(path);
        okCount += 1;
      } catch (error) {
        errors.push(`${path.split("/").pop() || path}: ${error.message || "拉取失败"}`);
      }
    }

    if (errors.length) {
      showFeedback(`已提交 ${okCount} 个，失败 ${errors.length} 个。${errors[0] || ""}`, true);
    } else {
      showFeedback(`已提交 ${okCount} 个 CD2 拉取任务。`);
    }

    if (batchButtonLabel) batchButtonLabel.textContent = originalText || pullButtonText();
    await fetchCandidatesQueue(true);
  }

  async function clearRecordsBatch() {
    const clearButton = document.querySelector("[data-batch-clear]");
    const checkedBoxes = document.querySelectorAll('#workspace-candidates-container input[name="candidate_path"]:checked');
    const paths = Array.from(checkedBoxes)
      .filter((checkbox) => checkbox.dataset.canClear === "true")
      .map((checkbox) => checkbox.value)
      .filter(Boolean);
    if (!paths.length) {
      showFeedback("请至少勾选一条可清除的候选记录。", true);
      return;
    }

    const originalText = clearButton ? clearButton.textContent : "";
    if (clearButton) {
      clearButton.disabled = true;
      clearButton.textContent = "清除中...";
    }

    let okCount = 0;
    const errors = [];
    for (const path of paths) {
      try {
        await clearRemoteRecord(path);
        okCount += 1;
      } catch (error) {
        errors.push(`${path.split("/").pop() || path}: ${error.message || "清除失败"}`);
      }
    }

    if (errors.length) {
      showFeedback(`已清除 ${okCount} 条，失败 ${errors.length} 条。${errors[0] || ""}`, true);
    } else {
      showFeedback(`已清除 ${okCount} 条候选记录。`);
    }

    if (clearButton) clearButton.textContent = originalText || "清除记录";
    await fetchCandidatesQueue(true);
  }

  async function clearSingleRecord(path, button) {
    if (!path) {
      showFeedback("缺少候选路径，无法清除记录。", true);
      return;
    }
    const originalText = button ? button.textContent : "";
    if (button) {
      button.disabled = true;
      button.textContent = "清除中...";
    }
    try {
      const payload = await clearRemoteRecord(path);
      showFeedback(payload.message || "候选记录已清除。");
      await fetchCandidatesQueue(true);
    } catch (error) {
      showFeedback(error.message || "清除记录失败", true);
      if (button) {
        button.disabled = false;
        button.textContent = originalText || "清除记录";
      }
    }
  }

  async function clearAndRerun(sourcePath, button) {
    try {
      if (button) {
        button.disabled = true;
        button.textContent = "正在重试...";
      }
      const form = new FormData();
      form.set("source", sourcePath || "");
      const payload = await helper().fetchJson("/rerun", { method: "POST", body: form });
      showFeedback(payload.message || "已开始重新封装");
      window.location.reload();
    } catch (error) {
      showFeedback(error.message || "重试失败", true);
      if (button) {
        button.disabled = false;
        button.textContent = "清理残留并重试";
      }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    renderPipeline({});
    if (document.getElementById("workspace-candidates-container")) fetchCandidatesQueue();

    const refreshButton = document.querySelector("[data-refresh-candidates]");
    if (refreshButton) refreshButton.addEventListener("click", () => fetchCandidatesQueue(true));

    const batchButton = document.querySelector("[data-batch-pull]");
    if (batchButton) batchButton.addEventListener("click", batchAction);

    const clearButton = document.querySelector("[data-batch-clear]");
    if (clearButton) clearButton.addEventListener("click", clearRecordsBatch);

    const container = document.getElementById("workspace-candidates-container");
    if (container) {
      container.addEventListener("change", updateSelectedCount);
      container.addEventListener("click", (event) => {
        const button = event.target.closest("[data-clear-candidate-record]");
        if (!button) return;
        clearSingleRecord(button.dataset.clearCandidateRecord || "", button);
      });
    }

    const rerunButton = document.querySelector("[data-rerun-source]");
    if (rerunButton) {
      rerunButton.addEventListener("click", () => clearAndRerun(rerunButton.dataset.rerunSource || "", rerunButton));
    }
  });
})();
