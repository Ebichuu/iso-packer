"""Local smoke test for the v2 Flask UI contract.

This script uses an isolated DATA_DIR and an in-process fake CD2 client.
It does not connect to a real CloudDrive2 instance, pull files, or touch
the user's normal runtime data.
"""

from __future__ import annotations

import argparse
import gc
import importlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]


class FakeCd2Client:
    def get_sub_files(self, path: str, force_refresh: bool = False):
        if path == "/":
            return [
                SimpleNamespace(
                    name="remote",
                    fullPathName="/remote",
                    isDirectory=True,
                )
            ]
        if path == "/remote":
            return [
                SimpleNamespace(
                    name="inbox",
                    fullPathName="/remote/inbox",
                    isDirectory=True,
                )
            ]
        if path == "/remote/inbox":
            return [
                SimpleNamespace(
                    name="Movie A",
                    fullPathName="/remote/inbox/Movie A",
                    isDirectory=True,
                    size=1024,
                    writeTime="2026-06-24 10:00:00",
                )
            ]
        if path == "/remote/inbox/Movie A":
            return [
                SimpleNamespace(
                    name="BDMV",
                    fullPathName="/remote/inbox/Movie A/BDMV",
                    isDirectory=True,
                )
            ]
        return []


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def verify_static_contracts() -> None:
    templates = ROOT / "templates"
    static_js = ROOT / "static" / "js"

    template_files = list(templates.glob("*.html"))
    for path in template_files:
        text = read_text(path)
        require(
            not re.search(r"\son[a-zA-Z]+\s*=|javascript:", text),
            f"{path.name} contains inline event handlers",
        )
        ids = re.findall(r'id="([^"]+)"', text)
        duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
        require(not duplicate_ids, f"{path.name} contains duplicate ids: {', '.join(duplicate_ids)}")

        for button in re.findall(r"<button\b[^>]*>", text):
            require("type=" in button, f"{path.name} button missing type: {button}")

        for control in re.findall(r"<(?:input|select|textarea)\b[^>]*>", text):
            if 'type="hidden"' in control:
                continue
            control_start = text.find(control)
            nearby_markup = text[max(0, control_start - 180):control_start]
            has_label = (
                "aria-label=" in control
                or "aria-labelledby=" in control
                or "<label" in nearby_markup
            )
            require(has_label, f"{path.name} control missing accessible label: {control}")

    base_html = read_text(templates / "base.html")
    require('id="app-toast"' in base_html, "base.html missing app-toast")
    require("data-mobile-menu-toggle" in base_html, "base.html missing mobile menu hook")

    login_html = read_text(templates / "login.html")
    require('name="next"' in login_html, "login.html missing next field")
    require("next_url" not in login_html, "login.html still references next_url")
    require("has_password" not in login_html, "login.html still references has_password")

    index_html = read_text(templates / "index.html")
    require("index-gateway-status" in index_html, "index.html missing gateway status hook")
    require("images.unsplash.com" not in index_html, "index.html contains external placeholder image")
    require(
        ("今日起发行" in index_html) or ("最近已发售" in index_html),
        "index.html missing today-aware release cache badge",
    )
    require("暂无封面" in index_html, "index.html missing release poster fallback")
    require("TMDB 缓存海报" in index_html, "index.html missing local asset poster cache copy")
    require("movie.poster_path" in index_html, "local asset cards should render poster artwork when available")
    require("movie.poster_status" in index_html, "local asset cards should expose poster cache status")
    require("radial-gradient" not in index_html, "index.html should not use decorative radial gradients")
    require("release-calendar-row" in index_html, "index.html release calendar should use compact media rows")
    require("release-calendar-poster" in index_html, "index.html release calendar should keep poster artwork visible")
    require("release-calendar-filter-label" in index_html, "index.html release calendar missing filter label")
    require("data-release-date" in index_html, "index.html release cards should expose release dates")
    require("data-release-link" in index_html, "index.html release cards should expose click fallback links")
    require('role="link"' in index_html, "index.html release cards should expose accessible link role")
    require('tabindex="0"' in index_html, "index.html release cards should be keyboard focusable")
    require("release-tmdb-link" in index_html, "index.html TMDB badge should have an explicit link hook")
    require("data-release-filter" in index_html, "index.html release calendar should expose date filters")
    require("https://www.themoviedb.org/movie/" in index_html, "index.html TMDB badge should link to TMDB movie pages")
    require("lg:grid-cols-2" in index_html, "index.html release calendar should extend as a single responsive grid")
    require("更多蓝光发行" not in index_html, "index.html should not split releases into a secondary titled column")
    require("release-calendar-secondary" not in index_html, "index.html should not use a secondary release list container")
    require("发行月历" not in index_html, "index.html should not use the right-side month calendar")
    require("calendar_month.cells" not in index_html, "index.html should not render right-side month cells")
    require("calendar_month.release_days" not in index_html, "index.html should not render right-side release-day calendar")
    require("发行日历数据台" not in index_html, "index.html should not use release data-panel copy")
    require("展示页和工程台分工明确" not in index_html, "index.html should not expose design-process copy")
    require("原盘封装" not in index_html, "index.html hero should not use oversized slogan copy")
    require("交付结果一眼可见" not in index_html, "index.html hero should use compact showcase copy")
    require("item.title_status" not in index_html, "release cards should not expose title-maintenance status")
    require("item.poster_status" not in index_html, "release cards should not expose poster-maintenance status")
    require("item.tmdb_status" not in index_html, "release cards should not expose TMDB-maintenance status")

    workspace_html = read_text(templates / "workspace.html")
    require("workspace-candidates-container" in workspace_html, "workspace missing candidate container")
    require("data-batch-pull" in workspace_html, "workspace missing batch pull hook")
    require("pipeline-live-card" in workspace_html, "workspace missing live status card")
    require("pipeline-primary-status" in workspace_html, "workspace missing primary status title")
    require("pipeline-current-action" in workspace_html, "workspace missing current action text")
    require("pipeline-byte-progress" in workspace_html, "workspace missing byte progress text")
    require("pipeline-next-step" in workspace_html, "workspace missing next-step text")
    require("pipeline-progress-meta" in workspace_html, "workspace missing progress meta label")
    require("workspace-output-queue" in workspace_html, "workspace missing output queue container")
    require("output-queue-summary" in workspace_html, "workspace missing output queue summary")
    require("output-queue-title" in workspace_html, "workspace missing output queue title")
    require("封装中心" in workspace_html, "workspace should use concise packing-center copy")
    require("工程体检台" not in workspace_html, "workspace should not use engineering-checkup copy")
    require("封装工作台" not in workspace_html, "workspace should not mix workbench copy with packing center")

    files_html = read_text(templates / "files.html")
    require("file-browser-list" in files_html, "files.html missing browser list")
    require("data-root=" in files_html, "files.html missing root switch hooks")
    require("data-root-path=" in files_html, "files.html missing visible root path hooks")
    require("file-operation-bar" in files_html, "files.html missing batch operation bar")
    require('data-file-action="copy"' in files_html, "files.html missing copy action")
    require("file-custom-destination" in files_html, "files.html missing custom destination input")
    require("file-context-menu" in files_html, "files.html missing context menu")
    require("file-destination-picker" in files_html, "files.html missing destination picker")
    require("file-destination-use" in files_html, "files.html missing destination picker submit")
    require("修改时间" in files_html, "files.html missing modified-time column")
    file_markers = [
        'id="file-select-all"',
        'id="file-operation-bar"',
        'data-file-action="copy"',
        "拉取到监控目录",
        "修改时间",
        'id="file-properties-panel"',
        'id="file-context-menu"',
        'id="file-destination-picker"',
    ]
    for marker in file_markers:
        require(marker in files_html, f"files.html missing {marker}")

    shared_js = read_text(ROOT / "static" / "js" / "shared.js")
    require("formatBytes" in shared_js, "shared.js missing file-size formatter")

    settings_html = read_text(templates / "settings.html")
    settings_markers = [
        'id="system-config-form"',
        'id="directory-picker"',
        'id="cd2-test-btn"',
        'data-dir-provider="cd2"',
        'id="cd2_remote_source_dirs_text"',
        "下载目录",
        "封装后转存到 CD2 目录",
        "监控 CloudDrive 上传队列",
        'name="cd2_path_aliases_text"',
        'name="cd2_upload_match_mode"',
        'name="cd2_refresh_after_source_event"',
        'name="cd2_refresh_after_transfer"',
        "data-settings-reset",
        "TMDB 元数据",
        'name="tmdb_api_enabled"',
        'name="tmdb_api_domain"',
        'name="tmdb_image_domain"',
        'name="tmdb_api_token"',
        "data-tmdb-test",
        "测试不会保存",
        "首页资产海报",
        "settings-group",
        "CD2 设置",
        "系统设置",
    ]
    for marker in settings_markers:
        require(marker in settings_html, f"settings.html missing {marker}")
    require(settings_html.count('<details class="settings-card') >= 7, "settings.html main cards are not consistently collapsible")
    require("settings-card-summary" in settings_html, "settings.html missing collapsible card summary style")
    require("settings-toggle" in settings_html, "settings.html missing collapsible card toggle")
    settings_order = [
        "本地目录",
        "CD2 登录信息",
        "CD2 转存目录",
        "高级同步参数",
        "远端候选与拉取",
        "Web 登录",
        "TMDB 元数据",
    ]
    settings_positions = [settings_html.index(label) for label in settings_order]
    require(settings_positions == sorted(settings_positions), "settings.html card order drifted")
    for stale_color in ("#ecfdf5", "#047857", "#a7f3d0"):
        require(stale_color not in settings_html, "settings.html open card toggle is still too green")
    stale_pull_label = "CD2 " + "拉取目标目录"
    require(stale_pull_label not in settings_html, "settings.html still uses stale pull target label")
    verify_settings_form_contract(settings_html)

    release_calendar_path = ROOT / "data" / "release_calendar.json"
    require(release_calendar_path.exists(), "release calendar source file missing")
    fetcher_path = ROOT / "release_calendar_fetcher.py"
    require(fetcher_path.exists(), "release calendar fetcher missing")
    update_release_script = ROOT / "scripts" / "update_release_calendar.py"
    require(update_release_script.exists(), "release calendar update script missing")
    release_calendar = json.loads(read_text(release_calendar_path))
    require(release_calendar.get("version") == 2, "release calendar should use v2 cache format")
    require(
        release_calendar.get("generated_by") == "scripts/update_release_calendar.py",
        "release calendar should record update script",
    )
    require(
        release_calendar.get("primary_source", {}).get("name") == "Blu-ray.com Release Calendar",
        "release calendar missing Blu-ray.com source",
    )
    require(
        any(item.get("name") == "碟影" for item in release_calendar.get("review_sources", [])),
        "release calendar missing Discfan review source",
    )
    require(len(release_calendar.get("items", [])) >= 6, "release calendar should keep multiple source items")
    require(
        any(item.get("poster_url") for item in release_calendar.get("items", [])),
        "release calendar should include external poster URLs",
    )
    require(
        any(item.get("title_status") in ("人工中文名", "TMDB 中文名", "显示原名") for item in release_calendar.get("items", [])),
        "release calendar should keep title enrichment status fields",
    )
    require(isinstance(release_calendar.get("tmdb"), dict), "release calendar missing TMDB metadata")
    first_release = release_calendar["items"][0]
    for field in (
        "date",
        "sort_date",
        "release_label",
        "studio",
        "title",
        "title_zh",
        "title_status",
        "specs",
        "region",
        "status",
        "source",
        "url",
        "source_url",
        "poster_url",
        "poster_status",
        "tmdb_id",
        "tmdb_status",
        "review",
    ):
        require(field in first_release, f"release calendar cache item missing {field}")
    fetcher_text = read_text(fetcher_path)
    require("Blu-ray.com" in fetcher_text, "release calendar fetcher should reference Blu-ray.com")
    require("TMDB_API_KEY" in fetcher_text, "release calendar fetcher should support TMDB enrichment")
    require("tmdb_api_domain" in fetcher_text, "release calendar fetcher should support configurable TMDB domain")

    script_files = ["shared.js", "index.js", "workspace.js", "files.js", "settings.js"]
    for name in script_files:
        text = read_text(static_js / name)
        require("alert(" not in text, f"{name} still uses alert()")
        require("confirm(" not in text, f"{name} still uses confirm()")

    workspace_js = read_text(static_js / "workspace.js")
    require("pull_guard_enabled" in workspace_js, "workspace.js should read pull guard status")
    require("正在生成 ISO" in workspace_js, "workspace.js missing iso generation status copy")
    require("正在校验 ISO" in workspace_js, "workspace.js missing verify status copy")
    require("正在校验转存结果" in workspace_js, "workspace.js missing transfer verify status copy")
    require("下一步" in workspace_html, "workspace should expose next-step copy")
    require("等待 CD2 拉取完成" in workspace_js, "workspace.js missing cd2 waiting status copy")
    require("正在 CD2 上传云端" in workspace_js, "workspace.js missing cd2 upload status copy")
    require("CD2 上传中" in workspace_js, "workspace.js missing cd2 upload output row copy")
    require("pipeline-primary-status" in workspace_js, "workspace.js should update the primary status title")
    require("renderOutputQueue" in workspace_js, "workspace.js missing output queue renderer")
    require("renderOutputQueueV2" in workspace_js, "workspace.js should use the readable output queue renderer")
    require("outputQueueItems" in workspace_js, "workspace.js missing output queue item builder")
    require("fileOperationRows" in workspace_js, "workspace.js should include file operations in the output queue")
    require("本地复制中" in workspace_js, "workspace.js missing local copy output state")
    require("workspace-output-queue" in workspace_js, "workspace.js should render the output queue container")
    require("转存中" in workspace_js, "workspace.js missing transfer output state")
    require("已交付" in workspace_js, "workspace.js missing delivered output state")
    require("本地测试禁用拉取" in workspace_js, "workspace.js missing local pull guard label")

    shared_js = read_text(static_js / "shared.js")
    require("waiting_cd2_upload" in shared_js, "shared.js should treat cd2 upload waits as active jobs")
    require("UPLOAD" in shared_js, "shared.js should expose an upload global badge")
    index_js = read_text(static_js / "index.js")
    require("CD2 上传云端中" in index_js, "index.js should show cloud upload status on home")
    files_js = read_text(static_js / "files.js")
    require("row.dataset.rowOpenPath" in files_js, "files.js should open directories from row clicks")
    require("open.textContent" not in files_js, "files.js should not render a separate enter button")
    require("data-open-path" not in files_html, "files.html should not require an enter button column")
    require("/api/file-properties" in files_js, "files.js should fetch live file properties")
    require("contextmenu" in files_js, "files.js missing row context menu binding")
    require("openDestinationPicker" in files_js, "files.js missing destination picker flow")
    require("file_destination" in files_js, "files.js should use scoped destination picker")
    app_py = read_text(ROOT / "app.py")
    require("/api/file-properties" in app_py, "app.py missing file properties endpoint")
    require('"file_destination"' in app_py, "app.py missing file operation destination picker scope")
    require("VERIFY" in shared_js, "shared.js should expose verify badge state")
    require('"phase": "verify"' in app_py or 'update_active_progress("verify"' in app_py,
            "app.py should mark ISO verify phase")
    require('update_active_progress("transfer_verify"' in app_py,
            "app.py should mark transfer verify phase")
    require("STATUS_POLL_ACTIVE_MS = 2000" in shared_js, "shared.js active poll interval drifted")
    require("STATUS_POLL_IDLE_MS = 6000" in shared_js, "shared.js idle poll interval drifted")
    require("STATUS_POLL_ERROR_MS = 8000" in shared_js, "shared.js error poll interval drifted")
    require("hasActiveFileOperation" in shared_js, "shared.js should keep fast polling for local file operations")
    require("COPYING" in shared_js, "shared.js should show local copy badge state")
    require("waitingJobFromItems" in shared_js, "shared.js should expose waiting tasks as current jobs")

    index_js = read_text(static_js / "index.js")
    require("/api/release-calendar/refresh" in index_js, "index.js missing release calendar refresh endpoint")
    require("Blu-ray.com" in index_js, "index.js missing release calendar external refresh copy")
    require("setupReleaseCalendarFilters" in index_js, "index.js missing release calendar date filters")
    require("setupReleaseCardLinks" in index_js, "index.js missing release card click fallback")
    require("updateWorkerSummaryV2" in index_js, "index.js should use the file-operation aware worker summary")
    require("activeFileOps" in index_js, "index.js should count active local file operations")
    require("window.open(href" in index_js, "index.js should open release card links in a new window")
    require("window.location.href = href" not in index_js, "release card clicks should not navigate away from the preview page")
    require("release-tmdb-link" in index_js, "index.js should handle TMDB badge clicks separately")
    require("event.key !== 'Enter'" in index_js, "index.js should support keyboard release card navigation")
    require("aria-pressed" in index_js, "index.js should expose active release calendar filter state")
    settings_js = read_text(static_js / "settings.js")
    require("/api/tmdb/test" in settings_js, "settings.js missing TMDB test endpoint")

    start_local = read_text(ROOT.parent / "start-local.bat")
    require("ISO_PACKER_DISABLE_CD2_PULL=1" in start_local, "start-local.bat should disable real CD2 pull")
    require("ISO_PACKER_DISABLE_CD2_STATUS_POLL=1" in start_local, "start-local.bat should disable CD2 status polling")


def verify_settings_form_contract(settings_html: str) -> None:
    app_py = read_text(ROOT / "app.py")
    try:
        settings_block = app_py.split("def settings():", 1)[1].split('@app.route("/api/cd2/test"', 1)[0]
    except IndexError as exc:
        raise AssertionError("Could not isolate app.py settings() block") from exc

    fields = set()
    patterns = [
        r'request\.form\.get\("([^"]+)"',
        r'"([^"]+)"\s+in\s+request\.form',
        r'parse_int_form\("([^"]+)"',
    ]
    for pattern in patterns:
        fields.update(re.findall(pattern, settings_block))

    missing = sorted(field for field in fields if f'name="{field}"' not in settings_html)
    require(not missing, f"settings.html missing form fields: {', '.join(missing)}")


def build_data_dir() -> Path:
    base = ROOT / "test-output"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"smoke-v2-{int(time.time() * 1000)}"
    path.mkdir(parents=True)
    return path


def cleanup_data_dir(path: Path) -> None:
    for _ in range(20):
        gc.collect()
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.2)
    shutil.rmtree(path, ignore_errors=True)


def unload_project_modules() -> None:
    root_text = str(ROOT).lower()
    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if module_file and str(Path(module_file).resolve()).lower().startswith(root_text):
            sys.modules.pop(name, None)
    try:
        sys.path.remove(str(ROOT))
    except ValueError:
        pass


def import_app(data_dir: Path):
    os.environ["DATA_DIR"] = str(data_dir)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module("app")


def verify_tmdb_enrichment_contract() -> None:
    previous_key = os.environ.get("TMDB_API_KEY")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    fetcher = importlib.import_module("release_calendar_fetcher")
    original_search = fetcher.tmdb_search_movie

    def fake_search(title: str, year: str = "", **_kwargs):
        return {
            "id": 12345,
            "title": "谜中谜",
            "original_title": "Charade",
            "poster_path": "/charade.jpg",
        }

    os.environ["TMDB_API_KEY"] = "smoke-test"
    fetcher.tmdb_search_movie = fake_search
    try:
        enriched, meta = fetcher.enrich_items_with_tmdb([
            {
                "title": "Charade 4K",
                "year": "1963",
                "poster_url": "",
                "poster_source": "",
            }
        ])
        item = enriched[0]
        require(meta.get("matched_count") == 1, "TMDB smoke should count matched item")
        require(item.get("title_zh") == "谜中谜", "TMDB smoke should fill Chinese title")
        require(item.get("poster_url", "").endswith("/charade.jpg"), "TMDB smoke should fill poster URL")
        require(item.get("poster_source") == "TMDB", "TMDB smoke should mark poster source")
    finally:
        fetcher.tmdb_search_movie = original_search
        if previous_key is None:
            os.environ.pop("TMDB_API_KEY", None)
        else:
            os.environ["TMDB_API_KEY"] = previous_key


def verify_local_media_poster_contract(appmod) -> None:
    original_search = appmod.tmdb_search_movie
    original_env_key = os.environ.get("TMDB_API_KEY")

    def fake_search(title: str, year: str = "", **_kwargs):
        require(title == "Charade", f"local media TMDB query drifted: {title}")
        require(year == "1963", f"local media TMDB year drifted: {year}")
        return {
            "id": 12345,
            "title": "谜中谜",
            "original_title": "Charade",
            "poster_path": "/charade.jpg",
        }

    appmod.tmdb_search_movie = fake_search
    try:
        with appmod.lock:
            appmod.state["local_media_posters"] = {}
        cfg = appmod.DEFAULT_CONFIG.copy()
        cfg.update({
            "tmdb_api_enabled": True,
            "tmdb_api_token": "smoke-test",
        })
        cards = appmod.local_media_cards([
            ("/watch/Charade.1963.2160p.UHD", {
                "status": "done",
                "last_size": 1024,
                "finished_at": "2026-06-26 10:00:00",
                "pack_iso": True,
            })
        ], cfg=cfg)
        require(cards and cards[0].get("poster_path", "").endswith("/charade.jpg"), "local asset poster was not filled")
        require(cards[0].get("title") == "谜中谜", "local asset Chinese title was not applied")
        require(cards[0].get("poster_status") == "TMDB 海报", "local asset poster status was not cached")

        with appmod.lock:
            appmod.state["local_media_posters"] = {}
        cfg_without_saved_token = appmod.DEFAULT_CONFIG.copy()
        cfg_without_saved_token.update({
            "tmdb_api_enabled": False,
            "tmdb_api_token": "",
        })
        os.environ["TMDB_API_KEY"] = "smoke-env-key"
        env_cards = appmod.local_media_cards([
            ("/watch/Charade.1963.2160p.UHD", {
                "status": "done",
                "last_size": 1024,
                "finished_at": "2026-06-26 10:00:00",
                "pack_iso": True,
            })
        ], cfg=cfg_without_saved_token)
        require(env_cards and env_cards[0].get("poster_path", "").endswith("/charade.jpg"), "local asset poster should use TMDB env fallback")
    finally:
        appmod.tmdb_search_movie = original_search
        if original_env_key is None:
            os.environ.pop("TMDB_API_KEY", None)
        else:
            os.environ["TMDB_API_KEY"] = original_env_key


def patch_cd2(appmod) -> None:
    appmod.get_cd2_client = lambda cfg: FakeCd2Client()
    appmod.fetch_cd2_uploads = lambda cfg: (
        {},
        {"connected": True, "human": "CD2 mock ok", "uploads": [], "last_error": ""},
    )

    def fake_create_cd2_pull_task(cfg, source_path, mode="manual", cd2_status=None):
        if not source_path:
            return {"ok": False, "message": "missing path"}, 400
        created_at = appmod.now()
        local_source = appmod.cd2_local_pull_path_for_source(cfg, source_path)
        with appmod.lock:
            item = appmod.state.setdefault("items", {}).setdefault(str(local_source), {"first_seen": created_at})
            item.update({
                "status": "waiting_cd2_pull",
                "pack_iso": True,
                "cd2_pull_source": source_path,
                "cd2_pull_dest": cfg.get("cd2_remote_pull_dest_dir") or cfg.get("cd2_local_pull_dir") or cfg.get("watch_dir"),
                "cd2_pull_created_at": created_at,
                "cd2_pull_mode": mode,
                "partial_files": True,
                "progress": 0,
            })
            appmod.save_state_locked()
        return {
            "ok": True,
            "message": "mock pull task created",
            "source_path": source_path,
            "dest_dir": cfg.get("cd2_local_pull_dir") or cfg.get("watch_dir"),
            "mode": mode,
        }, 200

    appmod.create_cd2_pull_task = fake_create_cd2_pull_task


def verify_legacy_config_migration(appmod, data_dir: Path) -> None:
    legacy_config = {
        "watch_dir": str(data_dir / "watch"),
        "output_dir": str(data_dir / "output"),
        "enabled": True,
        "cd2_transfer_enabled": False,
        "cd2_wait_upload_complete": False,
    }
    (data_dir / "config.json").write_text(json.dumps(legacy_config, ensure_ascii=False, indent=2), encoding="utf-8")
    migrated = appmod.load_config()
    require(migrated.get("config_schema_version") == appmod.DEFAULT_CONFIG["config_schema_version"], "legacy config version was not migrated")
    require(migrated.get("cd2_transfer_enabled") is True, "legacy cd2_transfer_enabled should migrate to true")
    require(migrated.get("cd2_wait_upload_complete") is True, "legacy cd2_wait_upload_complete should migrate to true")
    saved = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    require(saved.get("cd2_transfer_enabled") is True, "migrated cd2_transfer_enabled was not saved")
    require(saved.get("cd2_wait_upload_complete") is True, "migrated cd2_wait_upload_complete was not saved")


def save_test_settings(client, data_dir: Path) -> None:
    watch_dir = data_dir / "watch"
    output_dir = data_dir / "output"
    cd2_target_dir = data_dir / "cd2-target"
    cd2_mount_root = data_dir / "cloud-root"
    for path in (watch_dir, output_dir, cd2_target_dir, cd2_mount_root):
        path.mkdir(parents=True, exist_ok=True)

    response = client.post(
        "/settings",
        data={
            "watch_dir": str(watch_dir),
            "output_dir": str(output_dir),
            "web_password": "",
            "web_password_confirm": "",
            "cd2_api_enabled": "on",
            "cd2_auth_mode": "api_token",
            "cd2_api_addr": "127.0.0.1:19798",
            "cd2_api_username": "tester",
            "cd2_api_password": "token",
            "cd2_mount_root": str(cd2_mount_root),
            "cd2_target_dir": str(cd2_target_dir),
            "cd2_path_aliases_text": f"{cd2_mount_root}=/115",
            "cd2_manual_pull_enabled": "on",
            "cd2_remote_source_dirs_text": "/remote/inbox\n/115",
            "cd2_remote_scan_depth": "1",
            "cd2_remote_pull_dest_dir": str(watch_dir),
            "cd2_refresh_after_source_event": "on",
            "cd2_refresh_after_transfer": "on",
            "cd2_confirm_stable_checks": "1",
            "cd2_confirm_delay_seconds": "0",
            "cd2_queue_poll_seconds": "1",
        },
        follow_redirects=False,
    )
    require(response.status_code in {302, 303}, f"settings save failed: {response.status_code}")


def verify_status_payload(client) -> None:
    response = client.get("/api/status")
    require(response.status_code == 200, f"status returned {response.status_code}")
    payload = response.get_json()
    require(isinstance(payload, dict), f"status payload is not object: {payload}")
    for key in ("config", "state", "cd2_status"):
        require(isinstance(payload.get(key), dict), f"status missing object {key}: {payload}")
    require(isinstance(payload.get("file_operations"), dict), f"status missing file operation summary: {payload}")
    require(isinstance(payload.get("stats"), dict), f"status missing stats summary: {payload}")

    state = payload["state"]
    require("active" in state, "status state missing active")
    require(isinstance(state.get("events"), list), "status events is not list")
    require(isinstance(state.get("items"), dict), "status items is not object")

    config = payload["config"]
    for key in (
        "watch_dir",
        "output_dir",
        "cd2_api_enabled",
        "cd2_manual_pull_enabled",
        "cd2_pull_guard_enabled",
        "cd2_status_poll_guard_enabled",
    ):
        require(key in config, f"status config missing {key}")

    cd2_status = payload["cd2_status"]
    for key in ("connected", "human", "last_error", "upload_count", "download_count", "copy_task_count"):
        require(key in cd2_status, f"cd2 status missing {key}")
    for key in ("uploads", "downloads", "copy_tasks"):
        require(key not in cd2_status, f"status payload should not include heavy CD2 list {key}")
        require(key not in state.get("cd2_status", {}), f"state cd2_status should not include heavy CD2 list {key}")
    file_operations = payload["file_operations"]
    require("active_count" in file_operations, "file operation summary missing active_count")
    require(isinstance(file_operations.get("items"), list), "file operation summary items is not list")
    require("active" in payload["stats"], "status stats missing active count")
    require(response.content_length is None or response.content_length < 65536, "status payload is too large")


def verify_cd2_upload_wait_status(appmod, client, data_dir: Path) -> None:
    target = str(data_dir / "cd2-target" / "Smoke Movie.iso")
    source = str(data_dir / "watch" / "Smoke Movie")
    upload = {
        "path": target,
        "status": "传输中",
        "current": 25 * 1024 * 1024,
        "total": 100 * 1024 * 1024,
        "percent": 25.0,
        "human": "25.0 MB / 100.0 MB",
        "summary": "CD2 上传中",
    }
    original_fetch = appmod.fetch_cd2_uploads
    try:
        appmod.fetch_cd2_uploads = lambda cfg: (
            {appmod.normalize_upload_path(target): upload},
            {
                "connected": True,
                "human": "CD2 mock upload ok",
                "last_error": "",
                "upload_count": 1,
                "download_count": 0,
                "copy_task_count": 0,
                "uploads": [upload],
                "downloads": [],
                "copy_tasks": [],
            },
        )
        with appmod.lock:
            appmod.state["items"][source] = {
                "status": "waiting_cd2_upload",
                "target": target,
                "size": upload["total"],
                "last_size": upload["total"],
                "pack_iso": True,
                "first_seen": appmod.now(),
                "transfer_finished_at": appmod.now(),
            }
            appmod.save_state_locked()
        response = client.get("/api/status")
        require(response.status_code == 200, f"upload wait status returned {response.status_code}")
        payload = response.get_json()
        item = (payload.get("state", {}).get("items") or {}).get(source) or {}
        require(item.get("status") == "waiting_cd2_upload", f"upload wait item status mismatch: {item}")
        attached = item.get("cd2_upload") or {}
        require(attached.get("percent") == 25.0, f"upload progress was not attached: {attached}")
        require((payload.get("stats") or {}).get("active", 0) >= 1, "upload wait should count as active")
    finally:
        appmod.fetch_cd2_uploads = original_fetch
        with appmod.lock:
            appmod.state.get("items", {}).pop(source, None)
            appmod.save_state_locked()


def verify_status_poll_guard(client) -> None:
    previous = os.environ.get("ISO_PACKER_DISABLE_CD2_STATUS_POLL")
    try:
        os.environ["ISO_PACKER_DISABLE_CD2_STATUS_POLL"] = "1"
        response = client.get("/api/status")
        require(response.status_code == 200, f"guarded status returned {response.status_code}")
        payload = response.get_json()
        config = payload.get("config") or {}
        require(config.get("cd2_status_poll_guard_enabled") is True, "status poll guard flag missing")
        cd2_status = payload.get("cd2_status") or {}
        require("本地预览已暂停 CD2 状态轮询" in (cd2_status.get("human") or ""), "status poll guard message mismatch")
        for key in ("upload_count", "download_count", "copy_task_count"):
            require(cd2_status.get(key) == 0, f"guarded status should report zero {key}")
        for key in ("uploads", "downloads", "copy_tasks"):
            require(key not in cd2_status, f"guarded status leaked heavy list {key}")
    finally:
        if previous is None:
            os.environ.pop("ISO_PACKER_DISABLE_CD2_STATUS_POLL", None)
        else:
            os.environ["ISO_PACKER_DISABLE_CD2_STATUS_POLL"] = previous


def verify_release_calendar_refresh(appmod, client) -> None:
    original = appmod.refresh_release_calendar_cache

    def fake_refresh(path, limit=12, **_kwargs):
        return {
            "version": 2,
            "updated_at": "2026-06-26",
            "fetched_at": "2026-06-26T00:00:00",
            "mode": "external_cache_with_review_layer",
            "generated_by": "scripts/update_release_calendar.py",
            "primary_source": {"name": "Blu-ray.com Release Calendar", "url": "https://www.blu-ray.com/movies/releasedates.php"},
            "review_sources": [{"name": "碟影", "usage": "中文校对"}],
            "tmdb": {"enabled": False, "status": "not_configured", "message": "TMDB 未配置", "matched_count": 0},
            "items": [
                {
                    "title": "Mock Blu-ray",
                    "date": "06.26",
                    "studio": "Mock",
                    "specs": "4K UHD",
                    "poster_url": "https://example.invalid/poster.jpg",
                    "poster_status": "TMDB 海报",
                    "tmdb_status": "TMDB 已匹配",
                }
                for _ in range(limit)
            ],
        }

    appmod.refresh_release_calendar_cache = fake_refresh
    try:
        response = client.post("/api/release-calendar/refresh", json={"limit": 4})
        payload = response.get_json()
        require(response.status_code == 200, f"release calendar refresh returned {response.status_code}")
        require(payload and payload.get("ok") is True, f"release calendar refresh not ok: {payload}")
        require(payload.get("count") == 4, f"release calendar refresh count mismatch: {payload}")
    finally:
        appmod.refresh_release_calendar_cache = original


def run_smoke(keep: bool = False) -> Path:
    verify_static_contracts()
    verify_tmdb_enrichment_contract()
    data_dir = build_data_dir()
    client = None
    appmod = None
    try:
        appmod = import_app(data_dir)
        require(appmod.DEFAULT_CONFIG.get("cd2_transfer_enabled") is True, "cd2_transfer_enabled default should be true")
        require(appmod.DEFAULT_CONFIG.get("cd2_wait_upload_complete") is True, "cd2_wait_upload_complete default should be true")
        releases = appmod.release_calendar_items()
        require(isinstance(releases, list) and len(releases) >= 6, "home release calendar should expose cached items")
        for field in (
            "date",
            "sort_date",
            "release_label",
            "studio",
            "title",
            "title_zh",
            "title_status",
            "specs",
            "region",
            "status",
            "source",
            "url",
            "poster_url",
            "poster_status",
            "tmdb_status",
            "review",
        ):
            require(field in releases[0], f"release calendar item missing {field}")
        release_payload = appmod.release_calendar_payload()
        require(
            release_payload.get("primary_source", {}).get("name") == "Blu-ray.com Release Calendar",
            "release calendar payload missing primary source",
        )
        release_window = release_payload.get("window") or {}
        require(
            release_window.get("mode") in {"upcoming", "recent"},
            f"release calendar should expose a today-aware display window: {release_window}",
        )
        if release_window.get("mode") == "upcoming":
            require(
                all(str(item.get("sort_date") or "9999-12-31")[:10] >= release_window["today"] for item in releases if item.get("sort_date")),
                "upcoming release calendar should not show past releases",
            )
        else:
            require(
                release_window.get("label") == "最近已发售",
                "past-only release cache should be labelled as recent releases",
            )
        alias_cfg = {
            "cd2_remote_source_dirs": ["/CloudNAS/CloudDrive/00-未整理/01-BDMV"],
            "cd2_path_aliases": [{"local": "/CloudNAS/CloudDrive", "remote": "/115"}],
        }
        require(
            appmod.cd2_remote_source_allowed("/115/00-未整理/01-BDMV/Movie A", alias_cfg),
            "cd2 remote source alias should allow scanned /115 candidate",
        )
        verify_legacy_config_migration(appmod, data_dir)
        patch_cd2(appmod)
        verify_local_media_poster_contract(appmod)
        client = appmod.app.test_client()

        previous_disable_auth = os.environ.get("ISO_PACKER_DISABLE_AUTH")
        os.environ["ISO_PACKER_DISABLE_AUTH"] = "1"
        response = client.get("/settings")
        require(response.status_code == 200, f"disable auth mode returned {response.status_code}")
        if previous_disable_auth is None:
            os.environ.pop("ISO_PACKER_DISABLE_AUTH", None)
        else:
            os.environ["ISO_PACKER_DISABLE_AUTH"] = previous_disable_auth

        response = client.post(
            "/login",
            data={"web_password": "pw", "web_password_confirm": "pw", "next": "/"},
            follow_redirects=True,
        )
        require(response.status_code == 200, f"first setup failed: {response.status_code}")

        save_test_settings(client, data_dir)
        verify_status_payload(client)
        verify_cd2_upload_wait_status(appmod, client, data_dir)
        verify_status_poll_guard(client)
        verify_release_calendar_refresh(appmod, client)

        page_checks = {
            "/": "index-gateway-status",
            "/workspace": "workspace-candidates-container",
            "/files": "file-browser-list",
            "/settings": "cd2-test-btn",
        }
        for path, marker in page_checks.items():
            response = client.get(path)
            body = response.get_data(as_text=True)
            require(response.status_code == 200, f"{path} returned {response.status_code}")
            require(marker in body, f"{path} missing marker {marker}")
            if path == "/":
                require("蓝光发行日历" in body, "home page missing Blu-ray calendar title")
                require(
                    ("今日起发行" in body) or ("最近已发售" in body),
                    "home page missing today-aware release calendar window label",
                )
                require("Blu-ray.com" in body, "home page missing Blu-ray.com calendar source")
                require("发售" in body, "home page missing visible release date label")
                require("碟影" not in body, "home page should not expose manual review source labels")
                require("贴吧" not in body, "home page should not expose manual review source labels")
                require("豆瓣" not in body, "home page should not expose manual review source labels")
                require("Blu-ray.com" in body, "home page missing release title source")
                require("TMDB #" in body, "home page missing TMDB id badge")
                require("blu-ray.com/movies/" in body, "home page release cards should link to Blu-ray.com movie pages")
                require("themoviedb.org/movie/" in body, "home page TMDB badge should link to TMDB movie page")
                stale_title_placeholder = "待补" + "中文名"
                require(stale_title_placeholder not in body, "home page should not expose missing Chinese title as primary copy")
                require("原名：" not in body, "home page should not show English original-title rows in release cards")
                stale_poster_placeholder = "No " + "poster"
                require(stale_poster_placeholder not in body, "home page should not show English poster placeholder")
                require("TMDB" in body, "home page missing TMDB enrichment status")
                require("scripts/update_release_calendar.py" in body, "home page missing calendar update script marker")

        for root_name in ("watch", "output", "cd2"):
            response = client.get(f"/api/browse?root={root_name}")
            require(response.status_code == 200, f"browse {root_name} returned {response.status_code}")
            payload = response.get_json()
            require(payload and payload.get("ok") is True, f"browse {root_name} not ok: {payload}")
            if root_name == "cd2":
                require(
                    Path(payload.get("root_path") or "").resolve() == (data_dir / "cloud-root").resolve(),
                    f"browse cd2 should use cd2_mount_root, got {payload}",
                )

        source_dir = data_dir / "cloud-root" / "SmokeMovie"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "BDMV").mkdir(exist_ok=True)
        (source_dir / "BDMV" / "index.bdmv").write_text("smoke", encoding="utf-8")
        response = client.get(f"/api/file-properties?root=cd2&path={quote(str(source_dir))}")
        require(response.status_code == 200, f"file properties returned {response.status_code}: {response.get_data(as_text=True)}")
        prop_payload = response.get_json()
        require(prop_payload and prop_payload.get("ok") is True, f"file properties not ok: {prop_payload}")
        require(prop_payload.get("type") == "dir", f"file properties should describe folder: {prop_payload}")
        require((prop_payload.get("size") or 0) >= 5, f"file properties should include folder size: {prop_payload}")
        require((prop_payload.get("file_count") or 0) >= 1, f"file properties should include file count: {prop_payload}")
        response = client.post(
            "/api/file-actions",
            json={
                "action": "copy",
                "root": "cd2",
                "paths": [str(source_dir)],
                "destination": "watch",
            },
        )
        require(response.status_code == 200, f"file remote pull action returned {response.status_code}: {response.get_data(as_text=True)}")
        file_action_payload = response.get_json()
        require(file_action_payload and file_action_payload.get("ok") is True, f"file remote pull action not ok: {file_action_payload}")
        require(file_action_payload.get("remote_pull") is True, f"file action should submit cd2 remote pull: {file_action_payload}")
        require(file_action_payload.get("created_count") == 1, f"file action should create one cd2 pull task: {file_action_payload}")
        response = client.get("/api/status")
        require(response.status_code == 200, f"status after file action returned {response.status_code}")
        status_payload = response.get_json() or {}
        state_items = (status_payload.get("state") or {}).get("items") or {}
        require(
            any(
                item.get("status") == "waiting_cd2_pull"
                and item.get("cd2_pull_source") == "/115/SmokeMovie"
                for item in state_items.values()
            ),
            f"file action should create waiting_cd2_pull item, got {state_items}",
        )
        require(not (data_dir / "watch" / "SmokeMovie").exists(), "file action should not use local copy for monitor pull")

        directory_scopes = (
            "watch_dir",
            "output_dir",
            "cd2_mount_root",
            "cd2_target_dir",
            "cd2_local_pull_dir",
            "cd2_remote_pull_dest_dir",
        )
        for scope in directory_scopes:
            response = client.get(f"/api/directories?scope={scope}")
            require(response.status_code == 200, f"directories {scope} returned {response.status_code}")
            payload = response.get_json()
            require(payload and payload.get("ok") is True, f"directories {scope} not ok: {payload}")
            require(isinstance(payload.get("entries"), list), f"directories {scope} entries is not list")

        response = client.post(
            "/api/cd2/test",
            data={
                "cd2_auth_mode": "api_token",
                "cd2_api_addr": "127.0.0.1:19798",
                "cd2_api_username": "tester",
                "cd2_api_password": "token",
            },
        )
        require(response.status_code == 200, f"cd2 test returned {response.status_code}")
        require(response.get_json().get("ok") is True, "cd2 test did not return ok")

        response = client.post(
            "/api/cd2/directories?path=/",
            data={
                "cd2_auth_mode": "api_token",
                "cd2_api_addr": "127.0.0.1:19798",
                "cd2_api_username": "tester",
                "cd2_api_password": "token",
            },
        )
        require(response.status_code == 200, f"cd2 directories root returned {response.status_code}")
        payload = response.get_json()
        require(payload.get("ok") is True, f"cd2 directories root not ok: {payload}")
        require(payload.get("entries") and payload["entries"][0].get("path") == "/remote", f"bad cd2 root entries: {payload}")

        response = client.post(
            "/api/cd2/directories?path=/remote",
            data={
                "cd2_auth_mode": "api_token",
                "cd2_api_addr": "127.0.0.1:19798",
                "cd2_api_username": "tester",
                "cd2_api_password": "token",
            },
        )
        require(response.status_code == 200, f"cd2 directories child returned {response.status_code}")
        payload = response.get_json()
        require(payload.get("parent") == "/", f"cd2 directories child bad parent: {payload}")
        require(payload.get("entries") and payload["entries"][0].get("path") == "/remote/inbox", f"bad cd2 child entries: {payload}")

        response = client.get("/api/cd2/remote-candidates?force=1")
        require(response.status_code == 200, f"remote candidates returned {response.status_code}")
        payload = response.get_json()
        require(payload.get("ok") is True, f"remote candidates not ok: {payload}")
        require(payload.get("pull_configured") is True, f"remote candidates should expose configured pull state: {payload}")
        require(payload.get("pull_guard_enabled") is False, f"remote candidates guard should be false by default: {payload}")
        require(payload.get("pull_enabled") is True, f"remote candidates should be effectively pullable in mock mode: {payload}")
        require(payload.get("candidate_count") == 1, f"unexpected candidate count: {payload}")
        candidate = payload["candidates"][0]
        require(candidate.get("path") == "/remote/inbox/Movie A", f"bad candidate path: {candidate}")
        require(candidate.get("disc_type") == "BDMV", f"bad candidate type: {candidate}")

        previous_disable_cd2_pull = os.environ.get("ISO_PACKER_DISABLE_CD2_PULL")
        try:
            os.environ["ISO_PACKER_DISABLE_CD2_PULL"] = "1"
            guarded_candidates = client.get("/api/cd2/remote-candidates?force=1").get_json()
            require(guarded_candidates.get("pull_configured") is True, f"guarded candidates should keep configured state: {guarded_candidates}")
            require(guarded_candidates.get("pull_guard_enabled") is True, f"guarded candidates missing pull guard: {guarded_candidates}")
            require(guarded_candidates.get("pull_enabled") is False, f"guarded candidates should not be effectively pullable: {guarded_candidates}")
            response = client.post("/api/cd2/pull", data={"path": candidate["path"]})
            require(response.status_code == 400, f"disabled cd2 pull returned {response.status_code}")
            require("禁用真实 CD2 拉取" in response.get_json().get("message", ""), "disabled cd2 pull message mismatch")

            os.environ.pop("ISO_PACKER_DISABLE_CD2_PULL", None)
            response = client.post("/api/cd2/pull", data={"path": candidate["path"]})
            require(response.status_code == 200, f"cd2 pull returned {response.status_code}")
            require(response.get_json().get("ok") is True, "cd2 pull did not return ok")
        finally:
            if previous_disable_cd2_pull is None:
                os.environ.pop("ISO_PACKER_DISABLE_CD2_PULL", None)
            else:
                os.environ["ISO_PACKER_DISABLE_CD2_PULL"] = previous_disable_cd2_pull

        print("smoke_v2_ok")
        return data_dir
    finally:
        if not keep:
            client = None
            appmod = None
            unload_project_modules()
            cleanup_data_dir(data_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated v2 UI/API smoke checks.")
    parser.add_argument("--keep", action="store_true", help="Keep the temporary DATA_DIR for debugging.")
    args = parser.parse_args()
    data_dir = run_smoke(keep=args.keep)
    if args.keep:
        print(f"kept_data_dir={data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
