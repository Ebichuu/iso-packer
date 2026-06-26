// 首页展示页 - 实时状态更新
(function () {
    function updateGatewayStatus(cd2Status) {
        const gatewayText = document.getElementById('gateway-text');
        const gatewayDot = document.getElementById('gateway-dot');
        const gatewayStatus = document.getElementById('index-gateway-status');
        if (!gatewayText) return;

        if (cd2Status && cd2Status.connected) {
            gatewayText.textContent = 'CD2 ALIAS ALIVE';
            gatewayDot?.classList.remove('bg-zinc-400', 'bg-amber-500');
            gatewayDot?.classList.add('bg-emerald-500');
            gatewayStatus?.classList.remove('text-zinc-600', 'text-amber-700', 'border-amber-200', 'bg-amber-50');
            gatewayStatus?.classList.add('text-emerald-700', 'border-emerald-200', 'bg-emerald-50');
        } else {
            gatewayText.textContent = cd2Status?.human || 'CD2 未连接';
            gatewayDot?.classList.remove('bg-zinc-400', 'bg-emerald-500');
            gatewayDot?.classList.add('bg-amber-500');
            gatewayStatus?.classList.remove('text-zinc-600', 'text-emerald-700', 'border-emerald-200', 'bg-emerald-50');
            gatewayStatus?.classList.add('text-amber-700', 'border-amber-200', 'bg-amber-50');
        }
    }

    function updateWorkerSummary(status) {
        const activeCount = document.getElementById('index-active-count');
        const workerNote = document.getElementById('index-worker-note');
        const job = status && status.current_job;

        if (activeCount) {
            const count = Number(status?.stats?.active ?? status?.state?.active_count ?? (job ? 1 : 0));
            activeCount.textContent = Number.isFinite(count) ? String(count) : (job ? '1' : '0');
        }

        if (!workerNote) return;
        if (job) {
            const source = job.source_path || job.source || '当前任务';
            const progress = Number(job.progress || 0);
            workerNote.textContent = `${job.stage_text || '封装执行中'} · ${Math.round(progress)}% · ${source}`;
            workerNote.title = workerNote.textContent;
        } else {
            workerNote.textContent = '当前无执行中任务，封装操作请进入封装中心';
            workerNote.removeAttribute('title');
        }
    }

    function setupReleaseCalendarRefresh() {
        const button = document.getElementById('release-calendar-refresh');
        const status = document.getElementById('release-calendar-status');
        if (!button || !status) return;

        button.addEventListener('click', async () => {
            const originalText = button.textContent;
            button.disabled = true;
            button.textContent = '刷新中';
            status.textContent = '正在从 Blu-ray.com 更新本地缓存...';
            status.classList.remove('text-red-700');
            status.classList.add('text-emerald-800');
            try {
                const response = await fetch('/api/release-calendar/refresh', {
                    method: 'POST',
                    headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
                    body: JSON.stringify({ limit: 12 }),
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || !payload.ok) {
                    throw new Error(payload.error || `刷新失败 (${response.status})`);
                }
                const tmdb = payload.tmdb || {};
                const tmdbText = tmdb.enabled ? `，TMDB 匹配 ${tmdb.matched_count || 0} 条` : '，TMDB 未配置';
                status.textContent = `已刷新 ${payload.count || 0} 条${tmdbText}，正在更新页面...`;
                window.setTimeout(() => window.location.reload(), 700);
            } catch (error) {
                status.textContent = error.message || '外网刷新失败，已保留本地缓存';
                status.classList.remove('text-emerald-800');
                status.classList.add('text-red-700');
            } finally {
                button.disabled = false;
                button.textContent = originalText;
            }
        });
    }

    function setupReleaseCalendarFilters() {
        const rows = Array.from(document.querySelectorAll('[data-release-date]'));
        const filterButtons = Array.from(document.querySelectorAll('[data-release-filter]'));
        const label = document.getElementById('release-calendar-filter-label');
        const empty = document.getElementById('release-calendar-empty');
        if (!rows.length || !filterButtons.length) return;

        function setActiveButton(value) {
            filterButtons.forEach((button) => {
                const active = button.dataset.releaseFilter === value;
                button.toggleAttribute('aria-pressed', active);
                button.classList.toggle('ring-2', active);
                button.classList.toggle('ring-emerald-500', active);
                button.classList.toggle('ring-offset-2', active);
            });
        }

        function applyFilter(value) {
            const showAll = !value || value === 'all';
            let visibleCount = 0;
            const visibleTitles = [];
            rows.forEach((row) => {
                const visible = showAll || row.dataset.releaseDate === value;
                row.hidden = !visible;
                if (visible) {
                    visibleCount += 1;
                    if (visibleTitles.length < 2) {
                        visibleTitles.push(row.dataset.releaseTitle || '发行条目');
                    }
                }
            });
            if (label) {
                if (showAll) {
                    label.textContent = '当前显示全部发行条目';
                } else if (visibleCount) {
                    label.textContent = `${value} · ${visibleCount} 部 · ${visibleTitles.join(' / ')}`;
                } else {
                    label.textContent = `${value} 暂无发行条目`;
                }
            }
            if (empty) {
                empty.classList.toggle('hidden', visibleCount !== 0);
            }
            setActiveButton(showAll ? 'all' : value);
        }

        filterButtons.forEach((button) => {
            button.addEventListener('click', () => applyFilter(button.dataset.releaseFilter));
        });

        applyFilter('all');
    }

    function setupReleaseCardLinks() {
        function openExternal(href) {
            if (!href) return;
            const opened = window.open(href, '_blank');
            if (opened) {
                try {
                    opened.opener = null;
                } catch (_) {
                    // Some browsers disallow touching opener; the new tab is still opened.
                }
            }
        }

        document.querySelectorAll('.release-tmdb-link').forEach((link) => {
            link.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                openExternal(link.href);
            });
        });

        document.querySelectorAll('[data-release-link]').forEach((card) => {
            card.addEventListener('click', (event) => {
                if (event.target.closest('a, button')) return;
                openExternal(card.dataset.releaseLink);
            });
            card.addEventListener('keydown', (event) => {
                if (event.target.closest('a, button')) return;
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                openExternal(card.dataset.releaseLink);
            });
        });
    }

    window.addEventListener('coreStatusUpdated', (event) => {
        const status = event.detail;
        updateGatewayStatus(status.cd2_status);
        updateWorkerSummary(status);
    });

    document.addEventListener('DOMContentLoaded', () => {
        updateWorkerSummary({});
        setupReleaseCalendarRefresh();
        setupReleaseCalendarFilters();
        setupReleaseCardLinks();
    });
})();
