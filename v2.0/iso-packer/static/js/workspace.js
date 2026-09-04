(function () {
  const helper = () => window.IsoPacker;
  const state = {
    candidates: [],
    lastStatus: {},
    lastCandidatePayload: null,
    outputSortOrder: "desc",
    candidateSortOrder: "desc",
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

  function firstPresent(...values) {
    return values.find((value) => value !== undefined && value !== null && String(value).trim() !== "");
  }

  function normalizeSortOrder(value) {
    return value === "asc" ? "asc" : "desc";
  }

  function parseSortTime(value) {
    if (value === undefined || value === null || value === "") return 0;
    if (typeof value === "number") {
      if (!Number.isFinite(value) || value <= 0) return 0;
      return value < 1e12 ? value * 1000 : value;
    }
    const text = String(value).trim();
    if (!text) return 0;
    if (/^\d+(\.\d+)?$/.test(text)) {
      const numeric = Number(text);
      if (Number.isFinite(numeric) && numeric > 0) return numeric < 1e12 ? numeric * 1000 : numeric;
    }
    const parsed = Date.parse(text);
    if (Number.isFinite(parsed)) return parsed;
    const normalized = text.replace(" ", "T");
    const reparsed = Date.parse(normalized);
    return Number.isFinite(reparsed) ? reparsed : 0;
  }

  function compareSortTime(left, right, order) {
    const leftTime = Number(left || 0);
    const rightTime = Number(right || 0);
    if (!leftTime && rightTime) return 1;
    if (leftTime && !rightTime) return -1;
    if (leftTime !== rightTime) {
      return normalizeSortOrder(order) === "asc" ? leftTime - rightTime : rightTime - leftTime;
    }
    return 0;
  }

  function formatSortTime(value) {
    const timestamp = parseSortTime(value);
    if (!timestamp) return "--";
    const date = new Date(timestamp);
    const pad = (part) => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
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

  function formatPercent(value) {
    const progress = Math.max(0, Math.min(100, Number(value || 0)));
    return `${progress.toFixed(progress % 1 ? 1 : 0)}%`;
  }

  function formatByteProgress(job) {
    if (!job) return "--";
    const current = Number(job.current || 0);
    const total = Number(job.total || 0);
    if (!Number.isFinite(current) || current <= 0) {
      return total > 0 ? `0 B / ${helper().formatBytes(total)}` : "--";
    }
    if (!Number.isFinite(total) || total <= 0) {
      return helper().formatBytes(current);
    }
    return `${helper().formatBytes(current)} / ${helper().formatBytes(total)}`;
  }

  function jobStatusView(job) {
    if (!job) {
      return {
        tone: "emerald",
        kicker: "任务状态",
        title: "当前待命",
        detail: "等待新的 BDMV / VIDEO_TS 进入队列。",
        meta: "待命",
        next: "等待监控目录出现新的原盘目录"
      };
    }
    const phase = String(job.phase || job.status || "").toLowerCase();
    if (phase === "transfer" || phase === "transferring") {
      return {
        tone: "emerald",
        kicker: "转存阶段",
        title: "正在转存 ISO",
        detail: job.stage_text || "ISO 已封装完成，正在复制到输出目录或 CD2 挂载目录。",
        meta: "转存中",
        next: "转存完成后会校验目标文件并标记交付完成"
      };
    }
    if (phase === "transfer_verify") {
      return {
        tone: "emerald",
        kicker: "转存校验",
        title: "正在校验转存结果",
        detail: job.stage_text || "ISO 已写入目标目录，正在确认文件大小和收尾状态。",
        meta: "校验转存",
        next: "校验通过后会清理临时文件并完成归档"
      };
    }
    if (phase === "refresh_cd2_dir" || phase === "refreshing_cd2_dir") {
      return {
        tone: "emerald",
        kicker: "目录刷新",
        title: "正在刷新 CD2 目录",
        detail: job.stage_text || "转存已完成，正在通知 CloudDrive2 刷新目标目录。",
        meta: "刷新目录",
        next: "刷新完成后任务会进入已交付状态"
      };
    }
    if (phase === "waiting_cd2_pull") {
      return {
        tone: "amber",
        kicker: "CD2 拉取",
        title: "等待 CD2 拉取完成",
        detail: job.stage_text || "远端原盘还在拉取到本地监控目录，完成后才会开始封装。",
        meta: "等待拉取",
        next: "拉取完成后自动进入封装队列"
      };
    }
    if (phase === "waiting_cd2_upload") {
      return {
        tone: "emerald",
        kicker: "CD2 上传",
        title: "正在 CD2 上传云端",
        detail: job.stage_text || "ISO 已写入 CD2 挂载目录，CloudDrive2 正在上传到云端。",
        meta: "上传云端",
        next: "上传队列完成后会标记为已交付"
      };
    }
    if (phase === "waiting_partial" || phase === "receiving" || phase === "waiting_stable") {
      return {
        tone: "amber",
        kicker: "源目录检查",
        title: "等待源目录稳定",
        detail: job.stage_text || "检测到文件仍在写入或目录还未稳定，暂不开始封装。",
        meta: "等待稳定",
        next: "目录稳定后自动开始封装"
      };
    }
    if (phase === "ready") {
      return {
        tone: "blue",
        kicker: "封装队列",
        title: "准备启动封装",
        detail: job.stage_text || "源目录已满足条件，等待封装任务启动。",
        meta: "准备中",
        next: "封装引擎启动后开始写入 ISO"
      };
    }
    if (phase === "verify" || phase === "verifying" || phase === "validating" || phase === "checking") {
      return {
        tone: "amber",
        kicker: "ISO 校验",
        title: "正在校验 ISO",
        detail: job.stage_text || "ISO 文件已经生成，正在确认结构是否完整可读。",
        meta: "校验中",
        next: "校验通过后进入转存或完成归档"
      };
    }
    if (phase === "finalize" || phase === "finalizing") {
      return {
        tone: "amber",
        kicker: "封装收尾",
        title: "封装收尾中",
        detail: job.stage_text || "ISO 已写入，正在重命名、校验或准备转存。",
        meta: "收尾中",
        next: "收尾完成后会进入转存或已交付状态"
      };
    }
    return {
      tone: "blue",
      kicker: "封装写入",
      title: "正在生成 ISO",
      detail: job.stage_text || "正在读取源目录并写入 ISO 文件。",
      meta: "封装中",
      next: "写入完成后会进入 ISO 校验"
    };
  }

  function toneClass(tone, target) {
    const table = {
      blue: {
        dot: "bg-blue-500 shadow-[0_0_0_5px_rgba(59,130,246,0.12)]",
        state: "font-mono text-sm text-blue-700",
        card: "mt-4 rounded-2xl border border-blue-200 bg-gradient-to-br from-blue-50 via-white to-sky-50 p-4 shadow-sm",
        text: "font-mono text-4xl font-black tracking-tight text-blue-700",
        bar: "h-full rounded-full bg-blue-500 transition-all duration-300",
        meta: "shrink-0 font-mono font-black text-blue-700"
      },
      emerald: {
        dot: "bg-emerald-500 shadow-[0_0_0_5px_rgba(16,185,129,0.12)]",
        state: "font-mono text-sm text-emerald-700",
        card: "mt-4 rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 via-white to-teal-50 p-4 shadow-sm",
        text: "font-mono text-4xl font-black tracking-tight text-emerald-700",
        bar: "h-full rounded-full bg-emerald-500 transition-all duration-300",
        meta: "shrink-0 font-mono font-black text-emerald-700"
      },
      amber: {
        dot: "bg-amber-500 shadow-[0_0_0_5px_rgba(245,158,11,0.14)]",
        state: "font-mono text-sm text-amber-700",
        card: "mt-4 rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 via-white to-orange-50 p-4 shadow-sm",
        text: "font-mono text-4xl font-black tracking-tight text-amber-700",
        bar: "h-full rounded-full bg-amber-500 transition-all duration-300",
        meta: "shrink-0 font-mono font-black text-amber-700"
      }
    };
    return (table[tone] || table.blue)[target];
  }

  function setWorkerVisual(isActive, tone = "blue") {
    const dot = document.getElementById("workspace-worker-dot");
    const stateLabel = document.getElementById("workspace-worker-state");
    if (dot) {
      dot.className = isActive
        ? `h-2.5 w-2.5 rounded-full ${toneClass(tone, "dot")}`
        : "h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_0_5px_rgba(16,185,129,0.12)]";
    }
    if (stateLabel) {
      stateLabel.textContent = isActive ? "运行中" : "待命";
      stateLabel.className = isActive
        ? toneClass(tone, "state")
        : "font-mono text-sm text-emerald-700";
    }
  }

  function renderPipeline(status) {
    const widget = document.getElementById("workspace-pipeline-widget");
    const job = status && status.current_job;
    if (!widget) return;

    const isActive = Boolean(job);
    const progress = Math.max(0, Math.min(100, Number((job && job.progress) || 0)));
    const view = jobStatusView(job);
    setWorkerVisual(isActive, view.tone);
    setText("pipeline-status-kicker", view.kicker);
    setText("pipeline-primary-status", view.title);
    setText("pipeline-current-action", view.detail);
    setText("workspace-worker-detail", view.detail);
    setText("pipeline-src", isActive ? job.source_path : "--");
    setText("pipeline-out", isActive ? job.output_iso : "--");
    setText("pipeline-stream-elapsed", isActive ? `耗时：${job.elapsed || "--"}` : "耗时：--");
    setText("pipeline-progress-text", formatPercent(progress));
    setText("pipeline-byte-progress", isActive ? formatByteProgress(job) : "--");
    setText("pipeline-stage-log", view.detail);
    setText("pipeline-progress-meta", view.meta);
    setText("pipeline-next-step", view.next);

    const liveCard = document.getElementById("pipeline-live-card");
    if (liveCard) liveCard.className = toneClass(view.tone, "card");
    const progressText = document.getElementById("pipeline-progress-text");
    if (progressText) progressText.className = toneClass(view.tone, "text");
    const progressMeta = document.getElementById("pipeline-progress-meta");
    if (progressMeta) progressMeta.className = toneClass(view.tone, "meta");

    const bar = document.getElementById("pipeline-progress-bar");
    if (bar) {
      bar.style.width = `${progress}%`;
      bar.className = toneClass(view.tone, "bar");
    }
  }

  function outputQueueView(item) {
    const phase = String(item.phase || item.status || "").toLowerCase();
    if (phase === "file_copy") {
      const done = item.status === "done" || item.status === "partial";
      const failed = item.status === "failed";
      return {
        label: failed ? "复制失败" : done ? "本地复制完成" : "本地复制中",
        badge: failed ? "border-red-200 bg-red-50 text-red-700" : done ? "border-sky-200 bg-sky-50 text-sky-700" : "border-blue-200 bg-blue-50 text-blue-700",
        hint: item.stage_text || "正在从文件浏览选择的目录复制到本地监控目录或指定目录。"
      };
    }
    if (phase === "file_move") {
      const done = item.status === "done" || item.status === "partial";
      const failed = item.status === "failed";
      return {
        label: failed ? "移动失败" : done ? "本地移动完成" : "本地移动中",
        badge: failed ? "border-red-200 bg-red-50 text-red-700" : done ? "border-sky-200 bg-sky-50 text-sky-700" : "border-blue-200 bg-blue-50 text-blue-700",
        hint: item.stage_text || "正在移动文件浏览选择的目录。"
      };
    }
    if (phase === "file_delete") {
      const failed = item.status === "failed";
      return {
        label: failed ? "删除失败" : "本地删除",
        badge: failed ? "border-red-200 bg-red-50 text-red-700" : "border-zinc-200 bg-zinc-50 text-zinc-700",
        hint: item.stage_text || "正在删除文件浏览选择的条目。"
      };
    }
    if (phase === "file_rename") {
      const done = item.status === "done" || item.status === "partial";
      const failed = item.status === "failed";
      return {
        label: failed ? "重命名失败" : done ? "重命名完成" : "重命名中",
        badge: failed ? "border-red-200 bg-red-50 text-red-700" : done ? "border-sky-200 bg-sky-50 text-sky-700" : "border-blue-200 bg-blue-50 text-blue-700",
        hint: item.stage_text || "正在重命名文件浏览选择的条目。"
      };
    }
    if (phase === "transfer" || phase === "transferring") {
      return { label: "转存中", badge: "border-emerald-200 bg-emerald-50 text-emerald-700", hint: "ISO 已生成，正在复制到输出目录或 CD2 挂载目录。" };
    }
    if (phase === "transfer_verify") {
      return { label: "转存校验", badge: "border-amber-200 bg-amber-50 text-amber-700", hint: "目标文件已写入，正在确认大小和收尾状态。" };
    }
    if (phase === "waiting_cd2_upload") {
      return { label: "CD2 上传中", badge: "border-emerald-200 bg-emerald-50 text-emerald-700", hint: item.stage_text || "ISO 已写入 CD2 挂载目录，正在由 CloudDrive2 上传云端。" };
    }
    if (phase === "waiting_cd2_pull") {
      return { label: "等待 CD2 拉取", badge: "border-amber-200 bg-amber-50 text-amber-700", hint: item.stage_text || "远程原盘正在拉取到本地监控目录。" };
    }
    if (phase === "waiting_cd2_confirm") {
      return { label: "等待 CD2 确认", badge: "border-amber-200 bg-amber-50 text-amber-700", hint: item.stage_text || "等待 CD2 源目录确认完成。" };
    }
    if (phase === "receiving" || phase === "waiting_partial" || phase === "waiting_stable") {
      return { label: phase === "waiting_partial" ? "等待下载完成" : "等待源目录稳定", badge: "border-amber-200 bg-amber-50 text-amber-700", hint: item.stage_text || item.error || "源目录仍在写入，暂不开始封装。" };
    }
    if (phase === "verify" || phase === "verifying" || phase === "validating" || phase === "checking") {
      return { label: "ISO 校验", badge: "border-amber-200 bg-amber-50 text-amber-700", hint: "ISO 已写完，正在确认结构完整。" };
    }
    if (phase === "finalize" || phase === "finalizing" || phase === "refresh_cd2_dir" || phase === "refreshing_cd2_dir") {
      return { label: "收尾中", badge: "border-amber-200 bg-amber-50 text-amber-700", hint: "正在重命名、刷新 CD2 目录或完成归档。" };
    }
    if (phase === "done" || phase === "transfer_done") {
      return { label: item.issue_text ? "已交付（有提示）" : "已交付", badge: item.issue_text ? "border-amber-200 bg-amber-50 text-amber-700" : "border-emerald-200 bg-emerald-50 text-emerald-700", hint: item.issue_text || "ISO 已完成，可按输出路径查看。" };
    }
    if (phase === "failed" || phase === "verify_failed" || phase === "transfer_failed" || phase === "output_exists") {
      return { label: "需处理", badge: "border-red-200 bg-red-50 text-red-700", hint: item.error || item.issue_text || "任务失败或输出路径需要手动处理。" };
    }
    if (phase === "running" || phase === "packing") {
      return { label: "生成中", badge: "border-blue-200 bg-blue-50 text-blue-700", hint: "正在读取源目录并写入 ISO。" };
    }
    return { label: "待产出", badge: "border-zinc-200 bg-zinc-50 text-zinc-600", hint: item.stage_text || "等待生成 ISO。" };
  }

  function itemOutputPath(item) {
    return item.output_iso || item.target || item.output_target || item.original_target || "--";
  }

  function fileOperationName(operation) {
    const sources = Array.isArray(operation.sources) ? operation.sources : [];
    const first = sources[0] || "";
    const name = first.split(/[\\/]/).filter(Boolean).pop();
    if (name && sources.length > 1) return `${name} 等 ${sources.length} 项`;
    return name || `文件操作 ${operation.id || ""}`.trim();
  }

  function fileOperationTarget(operation) {
    const destination = operation.destination || "";
    if (operation.destination_kind === "watch") return `监控目录 · ${destination}`;
    if (operation.destination_kind === "output") return `输出目录 · ${destination}`;
    if (operation.destination_kind === "custom") return `其他目录 · ${destination}`;
    return destination || "--";
  }

  function fileOperationRows(status) {
    const operations = (status && status.file_operations && status.file_operations.items) || [];
    return operations.map((operation) => {
      const sortSource = firstPresent(
        operation.finished_at,
        operation.completed_at,
        operation.updated_at,
        operation.started_at,
        operation.created_at
      );
      return {
        name: fileOperationName(operation),
        source: (operation.sources || []).join(" / "),
        output_iso: fileOperationTarget(operation),
        phase: `file_${operation.action || "operation"}`,
        status: operation.status || "queued",
        progress: Number(operation.progress || 0),
        current: Number(operation.done || 0),
        total: Number(operation.total || 0),
        stage_text: operation.message || "文件操作进行中",
        sort_source: sortSource,
        sort_time: parseSortTime(sortSource),
        time_label: formatSortTime(sortSource),
        is_file_operation: true,
        is_current: ["queued", "running"].includes(operation.status)
      };
    });
  }

  function outputQueueItems(status) {
    const rows = [];
    const seen = new Set();
    fileOperationRows(status).forEach((row) => rows.push(row));
    const current = status && status.current_job;
    if (current) {
      const source = current.source_path || current.source || "";
      const sortSource = firstPresent(
        current.finished_at,
        current.done_at,
        current.updated_at,
        current.started_at,
        current.task_started_at
      );
      rows.push({
        name: source.split(/[\\/]/).filter(Boolean).pop() || "当前任务",
        source,
        output_iso: current.output_iso || current.target || "--",
        phase: current.phase || current.status || "running",
        progress: current.progress,
        current: current.current,
        total: current.total,
        stage_text: current.stage_text,
        can_recheck: current.can_recheck === true,
        can_confirm_upload: current.can_confirm_upload === true,
        cd2_control_kind: current.cd2_control_kind || "",
        cd2_control_paused: current.cd2_control_paused === true,
        sort_source: sortSource,
        sort_time: parseSortTime(sortSource),
        time_label: formatSortTime(sortSource),
        is_current: true
      });
      if (source) seen.add(source);
    }

    const items = (status && status.state && status.state.items) || {};
    Object.entries(items).forEach(([source, item]) => {
      if (!item || seen.has(source)) return;
      const phase = String(item.status || "").toLowerCase();
      const hasOutput = item.target || item.output_target || item.original_target || phase === "done" || phase === "transfer_done" || ["receiving", "waiting_partial", "waiting_stable", "waiting_cd2_pull", "waiting_cd2_confirm", "waiting_cd2_upload"].includes(phase) || phase.includes("transfer") || phase.includes("verify");
      if (!hasOutput) return;
      const delivered = phase === "done" || phase === "transfer_done";
      const upload = delivered ? {} : (item.cd2_upload || {});
      const uploadProgress = delivered ? 100 : Number(upload.percent ?? item.progress ?? 0);
      const sortSource = firstPresent(
        item.finished_at,
        item.done_at,
        item.cd2_upload_done_at,
        item.transfer_finished_at,
        item.updated_at,
        item.last_changed,
        item.first_seen
      );
      rows.push({
        name: source.split(/[\\/]/).filter(Boolean).pop() || item.name || "ISO 任务",
        source,
        output_iso: itemOutputPath(item),
        phase,
        progress: Number.isFinite(uploadProgress) ? uploadProgress : Number(item.progress || 0),
        progress_label: delivered ? "完成" : "",
        current: upload.current || upload.current_bytes || item.last_size || item.size || 0,
        total: upload.total || upload.total_bytes || item.size || item.last_size || 0,
        stage_text: delivered ? (item.status_label || "已交付") : (upload.human || upload.summary || item.status_label || item.error || ""),
        error: item.error || item.last_error || "",
        issue_text: item.issue_text || "",
        failure_code: item.failure_code || "",
        can_recheck: item.can_recheck === true,
        can_confirm_upload: item.can_confirm_upload === true,
        cd2_control_kind: item.cd2_control_kind || "",
        cd2_control_paused: item.cd2_control_paused === true,
        finished_at: item.finished_at || item.done_at || item.updated_at || item.first_seen || "",
        sort_source: sortSource,
        sort_time: parseSortTime(sortSource),
        time_label: formatSortTime(sortSource)
      });
    });
    return rows
      .sort((left, right) => {
        if (left.is_current !== right.is_current) return left.is_current ? -1 : 1;
        return compareSortTime(left.sort_time, right.sort_time, state.outputSortOrder)
          || String(left.name || "").localeCompare(String(right.name || ""), "zh-Hans");
      })
      .slice(0, 6);
  }

  function renderOutputQueue(status) {
    const container = document.getElementById("workspace-output-queue");
    if (!container) return;
    const rows = outputQueueItems(status || {});
    setText("workspace-output-total", rows.length);
    const summary = document.getElementById("output-queue-summary");
    if (summary) {
      summary.textContent = rows.length
        ? `共 ${rows.length} 条产出记录，优先显示当前任务和最近完成项。`
        : "暂无产出记录；开始封装后会显示 ISO 生成、校验和转存状态。";
    }
    if (!rows.length) {
      container.innerHTML = renderStateCard("empty", "暂无产出", "开始封装后，这里会显示生成中的 ISO、转存目标和最近交付结果。");
      return;
    }
    container.innerHTML = rows.map((item) => {
      const view = outputQueueView(item);
      const progress = item.progress_label || (Number.isFinite(Number(item.progress)) ? formatPercent(item.progress) : "--");
      const byteText = item.current || item.total ? formatByteProgress(item) : "--";
      const currentMark = item.is_current ? '<span class="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 font-mono text-[9px] font-black uppercase tracking-[0.14em] text-blue-700">当前</span>' : "";
      return `
        <div class="grid gap-3 p-3.5 transition hover:bg-zinc-50 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_150px] lg:items-center">
          <div class="min-w-0 space-y-1">
            <div class="flex items-center gap-2">
              <span class="rounded-full border px-2 py-0.5 font-mono text-[9px] font-black uppercase tracking-[0.14em] ${view.badge}">${escapeHtml(view.label)}</span>
              ${currentMark}
            </div>
            <div class="truncate font-mono text-xs font-bold text-zinc-800" title="${escapeHtml(item.name)}">${escapeHtml(item.name || "--")}</div>
            <div class="truncate text-[11px] font-medium text-zinc-500" title="${escapeHtml(view.hint)}">${escapeHtml(view.hint)}</div>
          </div>
          <div class="min-w-0 space-y-1 font-mono text-[10px] text-zinc-500">
            <div class="truncate" title="${escapeHtml(item.output_iso)}">输出: ${escapeHtml(item.output_iso || "--")}</div>
            <div class="truncate" title="${escapeHtml(item.source)}">源: ${escapeHtml(item.source || "--")}</div>
          </div>
          <div class="text-left lg:text-right">
            <div class="font-mono text-sm font-black text-zinc-900">${escapeHtml(progress)}</div>
            <div class="mt-0.5 truncate font-mono text-[10px] font-bold text-zinc-400" title="${escapeHtml(byteText)}">${escapeHtml(byteText)}</div>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderOutputQueueV2(status) {
    const container = document.getElementById("workspace-output-queue");
    if (!container) return;
    const rows = outputQueueItems(status || {});
    setText("workspace-output-total", rows.length);
    const summary = document.getElementById("output-queue-summary");
    if (summary) {
      summary.textContent = rows.length
        ? `共 ${rows.length} 条产出/文件操作记录，优先显示当前任务。`
        : "暂无产出或本地文件操作记录；开始封装、拉取或整理文件后会显示在这里。";
    }
    if (!rows.length) {
      container.innerHTML = renderStateCard("empty", "暂无任务", "封装、校验、转存和文件浏览的本地文件操作会显示在这里。");
      return;
    }
    if (summary && rows.length) {
      summary.textContent = `共 ${rows.length} 条产出 / 文件操作记录，当前任务置顶，其余按时间${state.outputSortOrder === "asc" ? "从旧到新" : "从新到旧"}排列。`;
    }
    container.innerHTML = rows.map((item) => {
      const view = outputQueueView(item);
      const progress = item.progress_label || (Number.isFinite(Number(item.progress)) ? formatPercent(item.progress) : "--");
      const byteText = item.current || item.total ? formatByteProgress(item) : "--";
      const currentMark = item.is_current ? '<span class="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[9px] font-black tracking-[0.08em] text-blue-700">当前</span>' : "";
      const metric = item.is_file_operation ? `${Number(item.current || 0)} / ${Number(item.total || 0)} 项` : byteText;
      const controlActions = !item.is_file_operation && item.source && item.cd2_control_kind && item.phase !== "transfer_done" && item.phase !== "done"
        ? `<div class="mt-2 flex flex-wrap justify-start gap-2">
            ${item.cd2_control_kind === "copy" && item.cd2_control_paused ? `<button type="button" data-task-action="resume_copy" data-task-source="${escapeHtml(item.source)}" class="min-h-8 rounded-lg border border-blue-200 bg-white px-2.5 py-1 text-[10px] font-black text-blue-700 transition hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">继续复制</button>` : ""}
            ${item.cd2_control_kind === "copy" && !item.cd2_control_paused ? `<button type="button" data-task-action="pause_copy" data-task-source="${escapeHtml(item.source)}" class="min-h-8 rounded-lg border border-amber-200 bg-white px-2.5 py-1 text-[10px] font-black text-amber-700 transition hover:bg-amber-50 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2">暂停复制</button>` : ""}
            ${item.cd2_control_kind === "upload" && item.cd2_control_paused ? `<button type="button" data-task-action="resume_upload" data-task-source="${escapeHtml(item.source)}" class="min-h-8 rounded-lg border border-blue-200 bg-white px-2.5 py-1 text-[10px] font-black text-blue-700 transition hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">继续上传</button>` : ""}
            ${item.cd2_control_kind === "upload" && !item.cd2_control_paused ? `<button type="button" data-task-action="pause_upload" data-task-source="${escapeHtml(item.source)}" class="min-h-8 rounded-lg border border-amber-200 bg-white px-2.5 py-1 text-[10px] font-black text-amber-700 transition hover:bg-amber-50 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2">暂停上传</button>` : ""}
            ${item.cd2_control_kind === "copy" ? `<button type="button" data-task-action="restart_copy" data-task-source="${escapeHtml(item.source)}" class="min-h-8 rounded-lg border border-zinc-200 bg-white px-2.5 py-1 text-[10px] font-black text-zinc-700 transition hover:bg-zinc-50 focus:outline-none focus:ring-2 focus:ring-zinc-900 focus:ring-offset-2">重启复制</button>` : ""}
            ${item.cd2_control_kind === "copy" || item.cd2_control_kind === "upload" ? `<button type="button" data-task-action="cancel_${item.cd2_control_kind}" data-task-source="${escapeHtml(item.source)}" class="min-h-8 rounded-lg border border-red-200 bg-white px-2.5 py-1 text-[10px] font-black text-red-700 transition hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2">取消${item.cd2_control_kind === "copy" ? "复制" : "上传"}</button>` : ""}
          </div>`
        : "";
      const taskActions = !item.is_file_operation && item.source && (item.can_recheck || item.can_confirm_upload)
        ? `<div class="mt-2 flex flex-wrap justify-start gap-2">
            ${item.can_recheck ? `<button type="button" data-task-action="recheck" data-task-source="${escapeHtml(item.source)}" class="min-h-8 rounded-lg border border-amber-200 bg-white px-2.5 py-1 text-[10px] font-black text-amber-700 transition hover:bg-amber-50 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2">重新检测</button>` : ""}
            ${item.can_confirm_upload ? `<button type="button" data-task-action="confirm_upload" data-task-source="${escapeHtml(item.source)}" class="min-h-8 rounded-lg border border-emerald-200 bg-white px-2.5 py-1 text-[10px] font-black text-emerald-700 transition hover:bg-emerald-50 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2">确认已上传</button>` : ""}
          </div>`
        : "";
      return `
        <div class="grid gap-3 p-3.5 transition hover:bg-zinc-50 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_150px] lg:items-center">
          <div class="min-w-0 space-y-1">
            <div class="flex items-center gap-2">
              <span class="rounded-full border px-2 py-0.5 text-[9px] font-black tracking-[0.08em] ${view.badge}">${escapeHtml(view.label)}</span>
              ${currentMark}
            </div>
            <div class="truncate text-sm font-black leading-5 text-zinc-900" title="${escapeHtml(item.name)}">${escapeHtml(item.name || "--")}</div>
            <div class="truncate text-[11px] font-medium text-zinc-500" title="${escapeHtml(view.hint)}">${escapeHtml(view.hint)}</div>
            ${controlActions}${taskActions}
          </div>
          <div class="min-w-0 space-y-1 font-mono text-[10px] text-zinc-500">
            <div class="truncate" title="${escapeHtml(item.output_iso)}">目标: ${escapeHtml(item.output_iso || "--")}</div>
            <div class="truncate" title="${escapeHtml(item.source)}">来源: ${escapeHtml(item.source || "--")}</div>
            <div class="truncate" title="${escapeHtml(item.sort_source || item.time_label || "")}">时间: ${escapeHtml(item.time_label || "--")}</div>
          </div>
          <div class="text-left lg:text-right">
            <div class="font-mono text-sm font-black text-zinc-900">${escapeHtml(progress)}</div>
            <div class="mt-0.5 truncate font-mono text-[10px] font-bold text-zinc-400" title="${escapeHtml(metric)}">${escapeHtml(metric)}</div>
          </div>
        </div>
      `;
    }).join("");
  }

  window.addEventListener("coreStatusUpdated", (event) => {
    const status = event.detail || {};
    state.lastStatus = status;
    renderPipeline(status);
    renderOutputQueueV2(status);
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

  function candidateSortSource(candidate) {
    return firstPresent(
      candidate.modified,
      candidate.updated_at,
      candidate.created_at,
      candidate.pull_created_at
    );
  }

  function sortedCandidates(candidates) {
    return candidates
      .map((candidate) => {
        const sortSource = candidateSortSource(candidate);
        return {
          ...candidate,
          sort_source: sortSource,
          sort_time: parseSortTime(sortSource),
          time_label: formatSortTime(sortSource)
        };
      })
      .sort((left, right) => (
        compareSortTime(left.sort_time, right.sort_time, state.candidateSortOrder)
        || String(left.name || left.path || "").localeCompare(String(right.name || right.path || ""), "zh-Hans")
      ));
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

    const rawCandidates = Array.isArray(payload.candidates) ? payload.candidates : [];
    const candidates = sortedCandidates(rawCandidates);
    state.lastCandidatePayload = payload;
    state.candidates = rawCandidates;
    state.pullConfigured = payload.pull_configured === true || payload.manual_pull_enabled === true || payload.auto_pull_enabled === true;
    state.pullGuardEnabled = payload.pull_guard_enabled === true;
    state.pullEnabled = payload.pull_enabled === true && !state.pullGuardEnabled;
    updateCandidateSummary(payload, candidates);
    if (candidates.length) {
      const summaryText = document.getElementById("candidate-summary-text");
      if (summaryText) {
        summaryText.textContent = `${summaryText.textContent} 当前按修改时间${state.candidateSortOrder === "asc" ? "从旧到新" : "从新到旧"}排列。`;
      }
    }

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
                <span>时间: ${escapeHtml(candidate.time_label || "--")}</span>
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
      const payload = await helper().fetchJson(`/api/cd2/remote-candidates?force=${force ? "1" : "0"}&_=${Date.now()}`, {
        signal: AbortSignal.timeout(20000)
      });
      renderCandidates(payload);
    } catch (error) {
      setText("workspace-candidate-total", "--");
      const timedOut = error && (error.name === "TimeoutError" || error.name === "AbortError");
      const message = timedOut
        ? "CD2 候选扫描超时，可以稍后重新点击刷新。"
        : (error.message || "远程候选同步失败，请检查 CD2 API 与挂载配置。");
      setText("candidate-summary-text", message);
      container.innerHTML = renderStateCard("error", timedOut ? "扫描超时" : "同步失败", message);
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

  async function taskAction(sourcePath, action, button) {
    if (!sourcePath || !action) return;
    if (action === "confirm_upload" && !window.confirm("确认 CD2 目标 ISO 已完整上传？系统会重新校验文件，不会删除文件。")) return;
    if (action.startsWith("cancel_") && !window.confirm("确认取消当前 CD2 任务？取消后需要重新提交。")) return;
    const originalText = button ? button.textContent : "";
    if (button) {
      button.disabled = true;
      button.textContent = "处理中...";
    }
    try {
      const form = new FormData();
      form.set("source", sourcePath);
      form.set("action", action);
      const payload = await helper().fetchJson("/api/tasks/action", { method: "POST", body: form });
      showFeedback(payload.message || "操作已提交");
    } catch (error) {
      showFeedback(error.message || "任务操作失败", true);
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
    }
  }

  async function loadCd2Diagnostics() {
    const output = document.querySelector("[data-cd2-diagnostics-output]");
    const button = document.querySelector("[data-cd2-diagnostics-refresh]");
    if (!output) return;
    if (button) button.disabled = true;
    output.textContent = "读取 CD2 诊断信息...";
    try {
      const payload = await helper().fetchJson("/api/cd2/diagnostics");
      const runtime = payload.runtime || {};
      const running = payload.running || {};
      const counts = payload.task_counts || {};
      const errors = Object.entries(payload.errors || {}).map(([key, value]) => `${key}: ${value}`);
      const lines = [
        `连接: ${payload.connected ? "正常" : "不可用"}`,
        `版本: ${runtime.product_version || "--"} / API ${runtime.cloud_api_version || "--"}`,
        `任务: 上传 ${counts.upload ?? "--"} · 复制 ${counts.copy ?? "--"} · 下载 ${counts.download ?? "--"}`,
        `资源: CPU ${running.cpu_usage ?? "--"}% · 内存 ${running.memory_usage_kb ?? "--"} KB · 句柄 ${running.file_handle_count ?? "--"}`,
        `句柄匹配: ${(payload.open_file_handles || []).length}`
      ];
      if (errors.length) lines.push(`不可用项: ${errors.join("；")}`);
      output.textContent = lines.join("\n");
    } catch (error) {
      output.textContent = error.message || "CD2 诊断读取失败";
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    renderPipeline({});
    renderOutputQueueV2({});
    if (document.getElementById("workspace-candidates-container")) fetchCandidatesQueue();

    const outputSort = document.getElementById("output-sort-order");
    if (outputSort) {
      state.outputSortOrder = normalizeSortOrder(outputSort.value);
      outputSort.addEventListener("change", () => {
        state.outputSortOrder = normalizeSortOrder(outputSort.value);
        renderOutputQueueV2(state.lastStatus || {});
      });
    }

    const candidateSort = document.getElementById("candidate-sort-order");
    if (candidateSort) {
      state.candidateSortOrder = normalizeSortOrder(candidateSort.value);
      candidateSort.addEventListener("change", () => {
        state.candidateSortOrder = normalizeSortOrder(candidateSort.value);
        if (state.lastCandidatePayload) renderCandidates(state.lastCandidatePayload);
      });
    }

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

    const outputContainer = document.getElementById("workspace-output-queue");
    if (outputContainer) {
      outputContainer.addEventListener("click", (event) => {
        const button = event.target.closest("[data-task-action]");
        if (!button) return;
        taskAction(button.dataset.taskSource || "", button.dataset.taskAction || "", button);
      });
    }

    const diagnosticsButton = document.querySelector("[data-cd2-diagnostics-refresh]");
    if (diagnosticsButton) diagnosticsButton.addEventListener("click", loadCd2Diagnostics);
    if (document.querySelector("[data-cd2-diagnostics-output]")) loadCd2Diagnostics();

    document.querySelectorAll("[data-task-recovery-action]").forEach((button) => {
      button.addEventListener("click", () => taskAction(
        button.dataset.taskSource || "",
        button.dataset.taskRecoveryAction || "",
        button
      ));
    });

    const rerunButton = document.querySelector("[data-rerun-source]");
    if (rerunButton) {
      rerunButton.addEventListener("click", () => clearAndRerun(rerunButton.dataset.rerunSource || "", rerunButton));
    }
  });
})();
