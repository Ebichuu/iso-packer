#!/usr/bin/env python3
import json
import os
import re
import shutil
import secrets
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from core import (
    DEFAULT_CONFIG,
    DISC_STRUCTURE_DIRS,
    PARTIAL_EXTENSIONS,
    TERMINAL_STATUSES,
    VIDEO_EXTENSIONS,
    apply_task_timings,
    badge_class,
    cd2_client_key_from_cfg,
    format_size,
    normalize_cd2_api_addr,
    now,
    path_in_root,
    safe_filename,
    safe_next_path,
    safe_volume_id,
    sanitize_config,
    seconds_between,
    status_label,
)

try:
    from clouddrive2_client import CloudDriveClient
except Exception:
    CloudDriveClient = None

# 数据目录：优先使用 /data（持久化挂载），否则使用当前目录
APP_DIR = Path(os.getenv("DATA_DIR", "/data"))
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
LOG_PATH = APP_DIR / "iso-packer.log"
LOG_LINE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
lock = threading.RLock()
cd2_lock = threading.RLock()
worker_lock = threading.Lock()
cd2_client_cache = {
    "key": None,
    "client": None,
    "auth_mode": None,
    "last_error": None,
    "checked_at": None,
    "last_success_at": None,
    "upload_map": {},
    "upload_status": None,
}
state = {"items": {}, "last_scan": None, "active": None, "events": [], "cd2": {}}
worker_started = False
last_log_prune = 0.0
BDMV_REQUIRED_FILES = ("index.bdmv", "MovieObject.bdmv")
BDMV_REQUIRED_DIRS = ("PLAYLIST", "STREAM", "CLIPINF")
COPY_TASK_DONE_STATUSES = {"3", "completed", "complete", "done", "finish", "finished"}
DIRECTORY_PICKER_ROOT = "@roots"
DIRECTORY_PICKER_SCOPES = {
    "watch_dir": ("watch_dir",),
    "output_dir": ("output_dir",),
    "cd2_mount_root": ("cd2_mount_root",),
    "cd2_target_dir": ("cd2_mount_root", "cd2_target_dir"),
}


def prune_log_file() -> None:
    global last_log_prune
    current = time.time()
    if current - last_log_prune < 3600:
        return
    last_log_prune = current
    if not LOG_PATH.exists():
        return
    cutoff = datetime.now() - timedelta(days=7)
    kept = []
    for line in LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = LOG_LINE_RE.match(line)
        if not match:
            kept.append(line)
            continue
        try:
            if datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") >= cutoff:
                kept.append(line)
        except ValueError:
            kept.append(line)
    tmp = LOG_PATH.with_suffix(".log.tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    tmp.replace(LOG_PATH)


def log(message: str) -> None:
    line = f"[{now()}] {message}"
    with lock:
        state.setdefault("events", []).append(line)
        state["events"] = state["events"][-200:]
        save_state_locked()
    prune_log_file()
    ensure_app_dir()
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_config() -> Dict:
    ensure_app_dir()
    if not CONFIG_PATH.exists():
        cfg = DEFAULT_CONFIG.copy()
        if not cfg.get("web_secret_key"):
            cfg["web_secret_key"] = secrets.token_urlsafe(32)
        save_config(cfg)
        return cfg
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    cfg = DEFAULT_CONFIG.copy()
    cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    if not cfg.get("web_secret_key"):
        cfg["web_secret_key"] = secrets.token_urlsafe(32)
        save_config(cfg)
    return cfg


def save_config(cfg: Dict) -> None:
    ensure_app_dir()
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def auth_enabled(cfg: Dict) -> bool:
    return True


def load_state() -> None:
    global state
    if STATE_PATH.exists():
        try:
            loaded = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass


def save_state_locked() -> None:
    ensure_app_dir()
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def set_app_secret(cfg: Dict) -> None:
    app.secret_key = cfg.get("web_secret_key") or secrets.token_urlsafe(32)


try:
    set_app_secret(load_config())
except Exception:
    app.secret_key = secrets.token_urlsafe(32)


def auth_password_set(cfg: Dict) -> bool:
    return bool((cfg or {}).get("web_password_hash"))


def is_logged_in() -> bool:
    return bool(session.get("logged_in"))


def wants_json_response() -> bool:
    return request.path.startswith("/api/") or request.path in {"/rerun", "/settings"}


def unauthorized_response(message: str = "请先登录"):
    if wants_json_response():
        return jsonify({"ok": False, "message": message}), 401
    return redirect(url_for("login", next=safe_next_path(request.path or "/")))


def verify_login_password(cfg: Dict, password: str) -> bool:
    stored = (cfg or {}).get("web_password_hash") or ""
    return bool(stored and check_password_hash(stored, password or ""))


def update_password(cfg: Dict, password: str) -> None:
    cfg["web_password_hash"] = generate_password_hash(password)
    if not cfg.get("web_secret_key"):
        cfg["web_secret_key"] = secrets.token_urlsafe(32)
    save_config(cfg)
    set_app_secret(cfg)


def resolve_absolute_path(value: str) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = Path("/") / path
    return path.resolve()


def path_in_any_root(path: Path, roots) -> bool:
    return any(path_in_root(path, root) for root in roots)


def directory_picker_roots(cfg: Dict, scope: str):
    fields = DIRECTORY_PICKER_SCOPES.get(scope, ())
    roots = []
    for field in fields:
        for raw in (cfg.get(field), DEFAULT_CONFIG.get(field)):
            if not raw:
                continue
            try:
                candidate = resolve_absolute_path(raw)
            except Exception:
                continue
            if candidate not in roots:
                roots.append(candidate)
    return roots


def directory_picker_payload_for_roots(roots):
    entries = []
    for root in roots:
        entries.append({
            "name": root.name or str(root),
            "path": str(root),
            "readable": root.exists() and os.access(root, os.R_OK | os.X_OK),
        })
    return {
        "ok": True,
        "path": DIRECTORY_PICKER_ROOT,
        "display_path": "可选目录",
        "parent": None,
        "entries": entries,
    }


def directory_picker_parent(path: Path, roots) -> Optional[str]:
    parent = path.parent
    if parent == path:
        return None
    if path_in_any_root(parent, roots):
        return str(parent)
    return DIRECTORY_PICKER_ROOT


def parse_int_form(name: str, fallback, minimum: Optional[int] = None) -> int:
    raw = request.form.get(name, fallback)
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是数字")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} 不能小于 {minimum}")
    return value


def normalize_upload_path(path: str) -> str:
    return str(Path(str(path or "")).expanduser()).replace("\\", "/").rstrip("/")


def normalize_match_path(path: str) -> str:
    return normalize_upload_path(path).lower()


def int_attr(obj, name: str, default: int = 0) -> int:
    try:
        return int(getattr(obj, name, default) or default)
    except (TypeError, ValueError, OverflowError):
        return default


def float_attr(obj, name: str, default: float = 0.0) -> float:
    try:
        return float(getattr(obj, name, default) or default)
    except (TypeError, ValueError, OverflowError):
        return default


def progress_percent(current: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return min(100.0, max(0.0, current * 100 / total))


def cd2_auth_mode_from_cfg(cfg: Dict) -> str:
    mode = str((cfg or {}).get("cd2_auth_mode") or "api_token").strip().lower()
    if mode not in {"api_token", "password"}:
        return "api_token"
    return mode


def cd2_error_message(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "unauthenticated" in lowered or "invalid login" in lowered:
        return "CD2 认证失败：请检查认证方式、API Token 或用户名密码"
    if "permission" in lowered or "denied" in lowered:
        return "CD2 权限不足：请检查 API Token 是否具备读取上传任务权限"
    if "unavailable" in lowered or "failed to connect" in lowered:
        return "CD2 API 地址不可达：请检查地址、端口和容器网络"
    return text


def get_cd2_client(cfg: Dict):
    if not CloudDriveClient:
        return None
    if not cfg.get("cd2_api_enabled"):
        return None
    addr = normalize_cd2_api_addr(cfg.get("cd2_api_addr"))
    auth_mode = cd2_auth_mode_from_cfg(cfg)
    username = str(cfg.get("cd2_api_username") or "").strip()
    secret = str(cfg.get("cd2_api_password") or "")
    if not addr or not secret:
        return None
    if auth_mode == "password" and not username:
        return None
    key = (addr, auth_mode, username, secret)
    with cd2_lock:
        cached = cd2_client_cache.get("client")
        if cached is not None and cd2_client_cache.get("key") == key:
            return cached
        if cached is not None:
            try:
                cached.close()
            except Exception:
                pass
        client = CloudDriveClient(addr)
        try:
            if auth_mode == "api_token":
                client.jwt_token = secret
            elif not client.authenticate(username, secret):
                client.close()
                cd2_client_cache.update({
                    "key": None,
                    "client": None,
                    "auth_mode": auth_mode,
                    "last_error": "CD2 认证失败：请检查用户名密码",
                    "checked_at": now(),
                })
                return None
        except Exception as exc:
            try:
                client.close()
            except Exception:
                pass
            cd2_client_cache.update({
                "key": None,
                "client": None,
                "auth_mode": auth_mode,
                "last_error": cd2_error_message(exc),
                "checked_at": now(),
            })
            return None
        cd2_client_cache.update({
            "key": key,
            "client": client,
            "auth_mode": auth_mode,
            "last_error": None,
            "checked_at": now(),
        })
        return client


def close_cd2_client() -> None:
    with cd2_lock:
        client = cd2_client_cache.get("client")
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        cd2_client_cache.update({
            "key": None,
            "client": None,
            "auth_mode": None,
            "last_error": None,
            "checked_at": None,
            "last_success_at": None,
            "upload_map": {},
            "upload_status": None,
        })


def extract_upload_status(upload) -> str:
    status = getattr(upload, "status", None)
    if status not in (None, ""):
        return str(status)
    enum_status = getattr(upload, "statusEnum", None)
    if enum_status not in (None, ""):
        return str(enum_status)
    return "unknown"


def extract_task_status(task) -> str:
    status = getattr(task, "status", None)
    if status not in (None, ""):
        return str(status)
    return "unknown"


def is_copy_task_done(info: Dict) -> bool:
    status = str(info.get("status") or "").strip().lower()
    return status in COPY_TASK_DONE_STATUSES


def cd2_path_matches_candidate(path: str, candidate: Path) -> bool:
    value = normalize_match_path(path)
    if not value:
        return False
    candidate_path = normalize_match_path(str(candidate))
    if value == candidate_path or value.startswith(candidate_path + "/"):
        return True
    name = candidate.name.strip().lower()
    if not name:
        return False
    return value.endswith("/" + name) or ("/" + name + "/") in value


def cd2_pending_source_task(candidate: Path, cd2_status: Optional[Dict]) -> Optional[Dict]:
    if not cd2_status or not cd2_status.get("connected"):
        return None
    for task in cd2_status.get("copy_tasks", []) or []:
        if task.get("done"):
            continue
        fields = (task.get("source"), task.get("target"), task.get("key"))
        if any(cd2_path_matches_candidate(value, candidate) for value in fields):
            return task
    for task in cd2_status.get("downloads", []) or []:
        fields = (task.get("path"), task.get("key"))
        if any(cd2_path_matches_candidate(value, candidate) for value in fields):
            return task
    return None


def cd2_pending_reason(task: Dict) -> str:
    kind = task.get("kind")
    if kind == "copy":
        return task.get("human") or "CD2 复制任务未完成"
    if kind == "download":
        return task.get("human") or "CD2 下载任务未完成"
    return task.get("human") or "CD2 任务未完成"


def source_readiness_blocker(source: Path, source_size: int, cd2_status: Optional[Dict] = None):
    if source_size < 0:
        return "receiving", "源目录仍在变化，文件暂不可读", None
    if source_size <= 0:
        return "receiving", "源目录为空或仍在接收中", None
    if has_partial_files(source):
        return "waiting_partial", "检测到未完成临时文件", None
    structure_ready, structure_reason = disc_structure_ready(source)
    if not structure_ready:
        return "waiting_partial", structure_reason, None
    pending_task = cd2_pending_source_task(source, cd2_status)
    if pending_task:
        return "waiting_partial", cd2_pending_reason(pending_task), pending_task
    return None, None, None


def mark_source_waiting(source: Path, status: str, reason: str, source_size: int = 0, pending_task: Optional[Dict] = None) -> None:
    changed_at = now()
    with lock:
        item = state.setdefault("items", {}).setdefault(str(source), {"first_seen": changed_at})
        item.update({
            "status": status,
            "pack_iso": True,
            "last_size": max(0, int(source_size or 0)),
            "last_changed": changed_at,
            "partial_files": status == "waiting_partial",
            "error": reason,
        })
        if pending_task:
            item["cd2_source_task"] = pending_task
        else:
            item.pop("cd2_source_task", None)
        state["active"] = None
        save_state_locked()


def fetch_cd2_downloads(client):
    if not hasattr(client, "get_download_file_list"):
        return []
    result = client.get_download_file_list()
    downloads = []
    for download in getattr(result, "downloadFiles", []) or []:
        total = int_attr(download, "fileLength")
        current = int_attr(download, "totalBufferUsed")
        percent = progress_percent(current, total)
        path = getattr(download, "filePath", "") or ""
        info = {
            "kind": "download",
            "key": path,
            "path": path,
            "status": "downloading",
            "current": current,
            "total": total,
            "percent": percent,
            "bytes_per_second": float_attr(download, "bytesPerSecond"),
            "detail": getattr(download, "detailDownloadInfo", "") or "",
            "error": getattr(download, "lastDownloadError", "") or "",
            "summary": f"{format_size(current)} / {format_size(total)}",
            "human": f"CD2 下载中 {percent:.1f}% ({format_size(current)} / {format_size(total)})" if total > 0 else "CD2 下载中",
        }
        downloads.append(info)
    return downloads


def fetch_cd2_copy_tasks(client):
    if not hasattr(client, "get_copy_tasks"):
        return []
    result = client.get_copy_tasks()
    tasks = []
    for task in getattr(result, "copyTasks", []) or []:
        total_bytes = int_attr(task, "totalBytes")
        current_bytes = int_attr(task, "uploadedBytes")
        total_files = int_attr(task, "totalFiles")
        done_files = int_attr(task, "uploadedFiles")
        percent = progress_percent(current_bytes, total_bytes)
        if total_bytes <= 0 and total_files > 0:
            percent = progress_percent(done_files, total_files)
        source = getattr(task, "sourcePath", "") or ""
        target = getattr(task, "destPath", "") or ""
        info = {
            "kind": "copy",
            "key": f"{source}->{target}",
            "source": source,
            "target": target,
            "status": extract_task_status(task),
            "current": current_bytes,
            "total": total_bytes,
            "done_files": done_files,
            "total_files": total_files,
            "failed_files": int_attr(task, "failedFiles"),
            "percent": percent,
            "paused": bool(getattr(task, "paused", False)),
            "summary": f"{done_files}/{total_files} 文件, {format_size(current_bytes)} / {format_size(total_bytes)}",
            "errors": [getattr(error, "message", "") for error in getattr(task, "errors", []) or [] if getattr(error, "message", "")],
        }
        info["done"] = is_copy_task_done(info)
        info["human"] = (
            f"CD2 复制{'完成' if info['done'] else '中'} {percent:.1f}% "
            f"({done_files}/{total_files} 文件, {format_size(current_bytes)} / {format_size(total_bytes)})"
        )
        tasks.append(info)
    return tasks


def fetch_cd2_uploads(cfg: Dict):
    poll_seconds = max(1, int(cfg.get("cd2_queue_poll_seconds", 10) or 10))
    with cd2_lock:
        cached_status = cd2_client_cache.get("upload_status")
        cached_map = cd2_client_cache.get("upload_map") or {}
        cached_checked_at = cd2_client_cache.get("checked_at")
        if cached_status and cached_checked_at and seconds_between(cached_checked_at) < poll_seconds:
            return dict(cached_map), dict(cached_status)
    status = {
        "enabled": bool(cfg.get("cd2_api_enabled")),
        "available": CloudDriveClient is not None,
        "connected": False,
        "auth_mode": cd2_client_cache.get("auth_mode"),
        "checked_at": cd2_client_cache.get("checked_at"),
        "last_success_at": cd2_client_cache.get("last_success_at"),
        "last_error": cd2_client_cache.get("last_error"),
        "uploads": [],
        "downloads": [],
        "copy_tasks": [],
    }
    if not status["enabled"]:
        status["last_error"] = "CD2 API 未启用"
        status["human"] = "CD2 API 未启用"
        return {}, status
    if not status["available"]:
        status["last_error"] = "缺少 clouddrive2-client 依赖"
        status["human"] = "缺少 clouddrive2-client 依赖"
        return {}, status
    client = get_cd2_client(cfg)
    if client is None:
        status["checked_at"] = cd2_client_cache.get("checked_at")
        status["auth_mode"] = cd2_client_cache.get("auth_mode")
        status["last_success_at"] = cd2_client_cache.get("last_success_at")
        status["last_error"] = cd2_client_cache.get("last_error") or "CD2 API 未连接"
        status["human"] = status["last_error"]
        return {}, status
    try:
        result = client.get_upload_file_list(get_all=True)
        downloads = fetch_cd2_downloads(client)
        copy_tasks = fetch_cd2_copy_tasks(client)
    except Exception as exc:
        message = cd2_error_message(exc)
        with cd2_lock:
            cd2_client_cache["last_error"] = message
            cd2_client_cache["checked_at"] = now()
            cd2_client_cache["upload_map"] = {}
            cd2_client_cache["upload_status"] = None
        status["checked_at"] = cd2_client_cache.get("checked_at")
        status["auth_mode"] = cd2_client_cache.get("auth_mode")
        status["last_success_at"] = cd2_client_cache.get("last_success_at")
        status["last_error"] = message
        status["human"] = message
        return {}, status

    checked_at = now()
    upload_map = {}
    status.update({
        "connected": True,
        "auth_mode": cd2_client_cache.get("auth_mode"),
        "checked_at": checked_at,
        "last_success_at": checked_at,
        "last_error": None,
        "upload_count": int(getattr(result, "totalCount", 0) or 0),
        "global_bytes_per_second": float(getattr(result, "globalBytesPerSecond", 0) or 0),
        "total_bytes": int(getattr(result, "totalBytes", 0) or 0),
        "finished_bytes": int(getattr(result, "finishedBytes", 0) or 0),
        "download_count": len(downloads),
        "copy_task_count": len(copy_tasks),
        "downloads": downloads,
        "copy_tasks": copy_tasks,
    })
    for upload in getattr(result, "uploadFiles", []) or []:
        current = int(getattr(upload, "transferedBytes", 0) or 0)
        total = int(getattr(upload, "size", 0) or 0)
        percent = 100.0 if total <= 0 else min(100.0, max(0.0, current * 100 / total))
        info = {
            "key": getattr(upload, "key", "") or "",
            "path": getattr(upload, "destPath", "") or "",
            "status": extract_upload_status(upload),
            "current": current,
            "total": total,
            "percent": percent,
            "summary": f"{format_size(current)} / {format_size(total)}",
            "human": f"{percent:.1f}% ({format_size(current)} / {format_size(total)})" if total > 0 else format_size(current),
            "error": getattr(upload, "errorMessage", "") or "",
        }
        upload_map[normalize_upload_path(info["path"])] = info
        status["uploads"].append(info)
    parts = []
    if status["upload_count"]:
        parts.append(f"{status['upload_count']} 项上传")
    if status["download_count"]:
        parts.append(f"{status['download_count']} 项下载")
    if status["copy_task_count"]:
        parts.append(f"{status['copy_task_count']} 项复制")
    status["human"] = " / ".join(parts) if parts else "未发现传输任务"
    with cd2_lock:
        cd2_client_cache["checked_at"] = status["checked_at"]
        cd2_client_cache["last_success_at"] = status["last_success_at"]
        cd2_client_cache["last_error"] = None
        cd2_client_cache["upload_map"] = dict(upload_map)
        cd2_client_cache["upload_status"] = dict(status)
    return upload_map, status


def attach_cd2_uploads(cfg: Dict, items: Dict, active: Optional[Dict] = None):
    upload_map, cd2_status = fetch_cd2_uploads(cfg)
    enriched = {}
    for key, item in (items or {}).items():
        copy = dict(item or {})
        upload = upload_map.get(normalize_upload_path(copy.get("target") or ""))
        if upload:
            copy["cd2_upload"] = upload
        enriched[key] = copy
    if active:
        upload = upload_map.get(normalize_upload_path(active.get("target") or ""))
        if upload:
            active = dict(active)
            active["cd2_upload"] = upload
    return enriched, active, cd2_status


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in {"@eaDir", ".Trash", ".DS_Store"}]
        for filename in files:
            fp = Path(root) / filename
            try:
                total += fp.stat().st_size
            except FileNotFoundError:
                return -1
    return total


def tree_signature(path: Path) -> Optional[Dict]:
    if path.is_file():
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return {"file_count": 1, "dir_count": 0, "latest_mtime": stat.st_mtime_ns}
    file_count = 0
    dir_count = 0
    latest_mtime = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in {"@eaDir", ".Trash", ".DS_Store"}]
        dir_count += len(dirs)
        try:
            latest_mtime = max(latest_mtime, Path(root).stat().st_mtime_ns)
        except FileNotFoundError:
            return None
        for filename in files:
            fp = Path(root) / filename
            try:
                latest_mtime = max(latest_mtime, fp.stat().st_mtime_ns)
            except FileNotFoundError:
                return None
            file_count += 1
    return {"file_count": file_count, "dir_count": dir_count, "latest_mtime": latest_mtime}


def has_partial_files(path: Path) -> bool:
    if path.is_file():
        return path.suffix.lower() in PARTIAL_EXTENSIONS
    for root, _, files in os.walk(path):
        for filename in files:
            if Path(filename).suffix.lower() in PARTIAL_EXTENSIONS:
                return True
    return False


def find_disc_dir(path: Path) -> Optional[Path]:
    if not path.is_dir():
        return None
    try:
        children = list(path.iterdir())
    except FileNotFoundError:
        return None
    for child in children:
        if child.is_dir() and child.name.lower() in DISC_STRUCTURE_DIRS:
            return child
    for child in children:
        if not child.is_dir():
            continue
        try:
            for grandchild in child.iterdir():
                if grandchild.is_dir() and grandchild.name.lower() in DISC_STRUCTURE_DIRS:
                    return grandchild
        except FileNotFoundError:
            continue
    return None


def has_disc_structure(path: Path) -> bool:
    return find_disc_dir(path) is not None


def disc_structure_ready(path: Path) -> tuple[bool, str]:
    disc_dir = find_disc_dir(path)
    if not disc_dir:
        return False, "未检测到 BDMV/VIDEO_TS 原盘结构"
    name = disc_dir.name.lower()
    if name == "bdmv":
        missing = []
        lower_children = {}
        try:
            for child in disc_dir.iterdir():
                lower_children[child.name.lower()] = child
        except FileNotFoundError:
            return False, "BDMV 目录仍在创建中"
        for filename in BDMV_REQUIRED_FILES:
            child = lower_children.get(filename.lower())
            if child is None or not child.is_file():
                missing.append(filename)
        for dirname in BDMV_REQUIRED_DIRS:
            child = lower_children.get(dirname.lower())
            if child is None or not child.is_dir():
                missing.append(dirname)
        if missing:
            return False, f"BDMV 结构未完整，缺少 {', '.join(missing[:5])}"
        return True, "BDMV 结构完整"
    if name == "video_ts":
        if not (disc_dir / "VIDEO_TS.IFO").is_file():
            return False, "VIDEO_TS 结构未完整，缺少 VIDEO_TS.IFO"
        return True, "VIDEO_TS 结构完整"
    return False, "未知原盘结构"


def should_pack_iso(source: Path) -> tuple[bool, str]:
    if source.is_file():
        if source.suffix.lower() in VIDEO_EXTENSIONS:
            return False, "单视频文件"
        return False, "非原盘单文件"
    if source.is_dir():
        if has_disc_structure(source):
            return True, "检测到 BDMV/VIDEO_TS 原盘结构"
        return False, "普通文件夹"
    return False, "未知路径类型"


def get_candidates(watch_dir: Path, output_dir: Path):
    if not watch_dir.exists():
        watch_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()
    for child in sorted(watch_dir.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith("."):
            continue
        try:
            resolved = child.resolve()
        except FileNotFoundError:
            continue
        if output_dir in resolved.parents or resolved == output_dir:
            continue
        if child.is_dir() or child.is_file():
            yield child


def enough_space(output_dir: Path, source_size: int, min_free_gb: float) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(output_dir)
    required = source_size + int(min_free_gb * 1024**3)
    return usage.free > required


def iso_path_for(source: Path, output_dir: Path) -> Path:
    base = safe_filename(source.name)
    target = output_dir / f"{base}.iso"
    if not target.exists():
        return target
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    return output_dir / f"{base}-{suffix}.iso"


def update_active_progress(phase: str, target: Path, progress: Dict) -> None:
    progress = dict(progress or {})
    progress = {
        **progress,
        "phase": phase,
        "percent": max(0.0, min(100.0, float(progress.get("percent") or 0))),
        "current": int(progress.get("current") or 0),
        "total": int(progress.get("total") or 0),
        "updated_at": now(),
    }
    with lock:
        active = state.get("active") or {}
        active["target"] = str(target)
        active["progress"] = progress
        state["active"] = active
        save_state_locked()


def run_iso(source: Path, target: Path, source_size: int) -> subprocess.CompletedProcess:
    volid = safe_volume_id(source.stem if source.is_file() else source.name)[:32].upper() or "DISC"
    # genisoimage supports UDF, which is important for Blu-ray folders and files over 4 GB.
    cmd = [
        "genisoimage",
        "-iso-level", "3",
        "-udf",
        "-allow-limited-size",
        "-full-iso9660-filenames",
        "-V", volid,
        "-o", str(target),
        str(source),
    ]
    stderr_path = target.with_suffix(target.suffix + ".stderr")
    stdout = ""
    with stderr_path.open("w+", encoding="utf-8", errors="ignore") as errfh:
        proc = subprocess.Popen(cmd, cwd=str(source.parent), text=True, stdout=subprocess.DEVNULL, stderr=errfh)
        last_update = 0.0
        while proc.poll() is None:
            current = target.stat().st_size if target.exists() else 0
            percent = 100.0 if source_size <= 0 else current * 100 / source_size
            current_time = time.time()
            if current_time - last_update >= 2:
                update_active_progress("packing", target, {"percent": min(percent, 99.9), "current": current, "total": source_size})
                last_update = current_time
            time.sleep(1)
        proc.wait()
        errfh.flush()
        errfh.seek(0)
        stderr = errfh.read()
    try:
        stderr_path.unlink()
    except FileNotFoundError:
        pass
    current = target.stat().st_size if target.exists() else 0
    update_active_progress("packing", target, {"percent": 100.0 if proc.returncode == 0 else min(current * 100 / max(source_size, 1), 99.9), "current": current, "total": source_size})
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def validate_iso(target: Path) -> bool:
    if not target.exists() or target.stat().st_size <= 0:
        return False
    result = subprocess.run(["xorriso", "-indev", str(target), "-toc"], text=True, capture_output=True)
    return result.returncode == 0



def unique_destination_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.stem}-{suffix}{path.suffix}")


def resolve_cd2_target_dir(cfg: Dict) -> Optional[Path]:
    mount_root = Path(str(cfg.get("cd2_mount_root") or "/CloudNAS")).expanduser()
    target_dir = Path(str(cfg.get("cd2_target_dir") or str(mount_root / "CloudDrive" / "00-未整理" / "00-mkiso"))).expanduser()
    if cfg.get("cd2_require_mount", True) and not mount_root.is_mount():
        log(f"CloudDrive2挂载目录未挂载，停止转移: {mount_root}")
        return None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log(f"创建CloudDrive2目标目录失败 {target_dir}: {exc}")
        return None
    return target_dir


def transfer_iso_to_mount(target: Path, cfg: Dict) -> Optional[Path]:
    if not cfg.get("cd2_transfer_enabled"):
        return target
    target_dir = resolve_cd2_target_dir(cfg)
    if not target_dir:
        return None
    if not target.exists():
        log(f"待转移ISO不存在: {target}")
        return None

    total = target.stat().st_size
    final_path = unique_destination_path(target_dir / target.name)
    tmp_path = final_path.with_name(final_path.name + ".partial")
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except Exception as exc:
            log(f"删除旧转移临时文件失败 {tmp_path}: {exc}")
            return None

    log(f"开始转移到CloudDrive2挂载目录: {target} -> {final_path}")
    copied = 0
    last_update = 0.0
    try:
        with target.open("rb") as src, tmp_path.open("wb") as dst:
            while True:
                chunk = src.read(16 * 1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                copied += len(chunk)
                current_time = time.time()
                if current_time - last_update >= 2:
                    percent = 100.0 if total <= 0 else copied * 100 / total
                    update_active_progress("transfer", final_path, {"percent": min(percent, 99.9), "current": copied, "total": total})
                    last_update = current_time
            dst.flush()
            os.fsync(dst.fileno())
        if tmp_path.stat().st_size != total:
            log(f"CloudDrive2转移大小校验失败: {tmp_path.stat().st_size} != {total}")
            return None
        tmp_path.replace(final_path)
        if final_path.stat().st_size != total:
            log(f"CloudDrive2最终文件大小校验失败: {final_path.stat().st_size} != {total}")
            return None
        update_active_progress("transfer", final_path, {"percent": 100.0, "current": total, "total": total, "verified": True})
        target.unlink()
        log(f"CloudDrive2转移完成并校验通过，已删除本地ISO: {final_path}")
        return final_path
    except Exception as exc:
        log(f"CloudDrive2转移失败: {exc}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return None


def process_item(source: Path, cfg: Dict) -> None:
    output_dir = Path(cfg["output_dir"]).expanduser().resolve()
    source_size = size_of(source)
    _, cd2_status = fetch_cd2_uploads(cfg)
    wait_status, wait_reason, pending_task = source_readiness_blocker(source, source_size, cd2_status)
    if wait_status:
        mark_source_waiting(source, wait_status, wait_reason, source_size, pending_task)
        log(f"等待源目录完成 {source}: {wait_reason}")
        return

    pack_iso, pack_reason = should_pack_iso(source)
    if not pack_iso:
        log(f"跳过ISO封装 {source}: {pack_reason}")
        log(f"普通媒体内容不加入任务列表，保留源路径: {source}")
        with lock:
            state.get("items", {}).pop(str(source), None)
            state["active"] = None
            save_state_locked()
        return

    if not enough_space(output_dir, source_size, float(cfg["min_free_space_gb"])):
        log(f"空间不足，暂停处理 {source}")
        return

    target = iso_path_for(source, output_dir)
    partial = target.with_suffix(target.suffix + ".partial")
    task_started_at = now()
    skip_message = None
    with lock:
        active_task = state.get("active")
        if active_task is not None:
            active_source = active_task.get("source") or "unknown"
            if active_source == str(source):
                skip_message = f"跳过重复启动任务: {source}"
            else:
                skip_message = f"已有任务执行中，跳过 {source}: {active_source}"
        else:
            item = state["items"].setdefault(str(source), {})
            item.update({
                "task_started_at": task_started_at,
                "pack_started_at": task_started_at,
                "status": "running",
                "target": str(target),
            })
            state["active"] = {
                "source": str(source),
                "target": str(target),
                "started_at": task_started_at,
                "task_started_at": task_started_at,
                "pack_started_at": task_started_at,
                "status": "running",
                "progress": {"phase": "packing", "percent": 0, "current": 0, "total": source_size, "updated_at": now()},
            }
            save_state_locked()
    if skip_message:
        log(skip_message)
        return
    log(f"开始生成 ISO: {source} -> {target}")
    try:
        if partial.exists():
            partial.unlink()
        result = run_iso(source, partial, source_size)
        if result.returncode != 0:
            error = result.stderr.strip()[-1000:] or "genisoimage 返回非 0"
            log(f"生成失败 {source}: {error}")
            try:
                partial.unlink()
            except FileNotFoundError:
                pass
            with lock:
                state["active"] = None
                item = state["items"].setdefault(str(source), {})
                item["status"] = "failed"
                item["error"] = error
                item["pack_finished_at"] = now()
                item["finished_at"] = now()
                item["last_changed"] = now()
                save_state_locked()
            return

        partial.replace(target)
        if not validate_iso(target):
            log(f"ISO 验证失败，保留源文件: {target}")
            with lock:
                state["active"] = None
                item = state["items"].setdefault(str(source), {})
                item["status"] = "verify_failed"
                item["error"] = "xorriso 校验失败"
                item["pack_finished_at"] = now()
                item["finished_at"] = now()
                item["last_changed"] = now()
                save_state_locked()
            return

        log(f"ISO 完成并验证通过: {target}")
        final_target = target
        if cfg.get("cd2_transfer_enabled"):
            transfer_started_at = now()
            with lock:
                item = state["items"].setdefault(str(source), {})
                item["status"] = "transferring"
                item["pack_finished_at"] = now()
                item["transfer_started_at"] = transfer_started_at
                state["active"] = {
                    "source": str(source),
                    "target": str(target),
                    "started_at": task_started_at,
                    "task_started_at": task_started_at,
                    "pack_started_at": task_started_at,
                    "pack_finished_at": item["pack_finished_at"],
                    "transfer_started_at": transfer_started_at,
                    "status": "transferring",
                    "progress": {"phase": "transfer", "percent": 0, "current": 0, "total": target.stat().st_size if target.exists() else 0, "updated_at": now()},
                }
                save_state_locked()
            moved_target = transfer_iso_to_mount(target, cfg)
            transfer_finished_at = now()
            if not moved_target:
                with lock:
                    item = state["items"].setdefault(str(source), {})
                    item.update({
                        "status": "transfer_failed",
                        "target": str(target),
                        "error": "移动到 CD2 挂载目录失败",
                        "done_at": transfer_finished_at,
                        "finished_at": transfer_finished_at,
                        "pack_finished_at": item.get("pack_finished_at") or transfer_finished_at,
                        "transfer_finished_at": transfer_finished_at,
                        "size": source_size,
                    })
                    item["last_changed"] = now()
                    state["active"] = None
                    save_state_locked()
                return
            final_target = moved_target
        else:
            transfer_started_at = None
            transfer_finished_at = None

        if cfg.get("delete_source_after_success"):
            try:
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
                log(f"已删除源文件: {source}")
            except Exception as exc:
                log(f"删除源文件失败 {source}: {exc}")

        with lock:
            item = state["items"].setdefault(str(source), {})
            if cfg.get("cd2_transfer_enabled"):
                status = "transfer_done"
            else:
                status = "done"
            finished_at = now()
            item.update({
                "status": status,
                "target": str(final_target),
                "done_at": finished_at,
                "finished_at": finished_at,
                "pack_finished_at": item.get("pack_finished_at") or finished_at,
                "transfer_started_at": transfer_started_at,
                "transfer_finished_at": transfer_finished_at,
                "size": source_size,
            })
            item.pop("error", None)
            state["active"] = None
            save_state_locked()
    except Exception as exc:
        log(f"处理任务异常 {source}: {exc}")
        try:
            if partial.exists():
                partial.unlink()
        except Exception:
            pass
        with lock:
            state["active"] = None
            item = state["items"].setdefault(str(source), {})
            if item.get("status") not in TERMINAL_STATUSES:
                failed_at = now()
                item["status"] = "failed"
                item["error"] = str(exc)
                item["pack_finished_at"] = item.get("pack_finished_at") or failed_at
                item["finished_at"] = failed_at
                item["last_changed"] = failed_at
            save_state_locked()


def scanner_loop() -> None:
    while True:
        cfg = load_config()
        interval = max(5, int(cfg.get("scan_interval_seconds", 20)))
        try:
            if cfg.get("enabled"):
                scan_once(cfg)
        except Exception as exc:
            log(f"扫描异常: {exc}")
        time.sleep(interval)


def scan_once(cfg: Dict) -> None:
    watch_dir = Path(cfg["watch_dir"]).expanduser().resolve()
    output_dir = Path(cfg["output_dir"]).expanduser().resolve()
    stable_seconds = max(30, int(cfg.get("stable_seconds", 180)))
    current = set()
    with lock:
        state["last_scan"] = now()
        active = state.get("active")
        save_state_locked()
    if active:
        return

    _, cd2_status = fetch_cd2_uploads(cfg)
    for candidate in get_candidates(watch_dir, output_dir):
        key = str(candidate.resolve())
        pack_iso, pack_reason = should_pack_iso(candidate)
        if not pack_iso:
            with lock:
                state.get("items", {}).pop(key, None)
                save_state_locked()
            continue
        current.add(key)
        size = size_of(candidate)
        signature = tree_signature(candidate)
        partial = has_partial_files(candidate)
        with lock:
            item = state["items"].setdefault(key, {"first_seen": now(), "status": "watching"})
            item["pack_iso"] = True
            active_statuses = {"running", "transferring"}
            if item.get("status") in TERMINAL_STATUSES | active_statuses:
                item.setdefault("last_size", size)
                item["partial_files"] = partial
                save_state_locked()
                continue
            last_size = item.get("last_size")
            last_signature = item.get("tree_signature")
            last_changed = item.get("last_changed", now())
            wait_status, wait_reason, pending_task = source_readiness_blocker(candidate, size, cd2_status)
            if wait_status:
                item["last_size"] = max(0, size)
                item["tree_signature"] = signature
                item["last_changed"] = now()
                item["status"] = wait_status
                item["partial_files"] = partial or wait_status == "waiting_partial"
                item["error"] = wait_reason
                if pending_task:
                    item["cd2_source_task"] = pending_task
                else:
                    item.pop("cd2_source_task", None)
                save_state_locked()
                continue
            if signature is None:
                item["last_size"] = max(0, size)
                item["last_changed"] = now()
                item["status"] = "receiving"
                item["error"] = "源目录仍在变化，文件暂不可读"
                save_state_locked()
                continue
            if last_size != size or last_signature != signature:
                item["last_size"] = size
                item["tree_signature"] = signature
                item["last_changed"] = now()
                item["status"] = "receiving"
                item["error"] = "源目录内容仍在变化"
                save_state_locked()
                continue
            item["last_size"] = size
            item["tree_signature"] = signature
            item["partial_files"] = partial
            item.pop("cd2_source_task", None)
            elapsed = seconds_between(last_changed)
            if partial:
                item["status"] = "waiting_partial"
                item["error"] = "检测到未完成临时文件"
            elif elapsed >= stable_seconds:
                item["status"] = "ready"
                item.pop("error", None)
                save_state_locked()
            else:
                item["status"] = "waiting_stable"
                item["error"] = f"等待源目录稳定 {stable_seconds} 秒"
            save_state_locked()

        with lock:
            ready = state["items"].get(key, {}).get("status") == "ready" and state.get("active") is None
        if ready:
            process_item(candidate, cfg)
            break

    with lock:
        for key, item in list(state.get("items", {}).items()):
            if key not in current and item.get("status") not in {"done", "transfer_done", "failed", "verify_failed", "transfer_failed"}:
                item["status"] = "removed"
        save_state_locked()


from page import PAGE, PAGE_LOGIN
def visible_iso_items(items: Dict) -> Dict:
    return {key: item for key, item in (items or {}).items() if item.get("pack_iso") is True}


def ordered_visible_items(items: Dict, active: Optional[Dict] = None):
    entries = sorted((items or {}).items(), key=lambda kv: kv[1].get("first_seen", ""), reverse=True)
    active = active or {}
    source = active.get("source")
    if not source:
        return entries
    for index, entry in enumerate(entries):
        if entry[0] == source:
            return [entry] + entries[:index] + entries[index + 1:]
    progress = active.get("progress") or {}
    active_item = {
        "status": active.get("status"),
        "target": active.get("target"),
        "first_seen": active.get("started_at", ""),
        "last_size": progress.get("total") or progress.get("current") or progress.get("uploaded") or 0,
        "size": progress.get("total") or 0,
        "pack_iso": True,
    }
    return [(source, active_item)] + entries


def recover_interrupted_task() -> None:
    with lock:
        active = state.get("active")
        if not active:
            return
        source = active.get("source")
        target = active.get("target")
        recovered = False
        if target:
            try:
                Path(str(target) + ".partial").unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
        if source and Path(source).exists():
            item = state.setdefault("items", {}).setdefault(source, {})
            if item.get("status") not in TERMINAL_STATUSES:
                item["status"] = "waiting_stable"
                item["last_changed"] = now()
                recovered = True
        if recovered:
            state["events"] = state.get("events", [])[-199:] + [f"[{now()}] 检测到上次任务中断，已恢复等待重新扫描"]
        state["active"] = None
        save_state_locked()


def start_worker_once():
    global worker_started
    if worker_started:
        return
    with worker_lock:
        if worker_started:
            return
        cfg = load_config()
        set_app_secret(cfg)
        load_state()
        recover_interrupted_task()
        t = threading.Thread(target=scanner_loop, daemon=True)
        t.start()
        worker_started = True


@app.before_request
def before_request():
    start_worker_once()
    cfg = load_config()
    if not auth_enabled(cfg):
        return None
    if request.path in {"/login", "/healthz"}:
        return None
    if not auth_password_set(cfg):
        return None if request.path == "/login" else unauthorized_response("请先设置登录密码")
    if is_logged_in():
        return None
    return unauthorized_response()


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.route("/login", methods=["GET", "POST"])
def login():
    cfg = load_config()
    set_app_secret(cfg)
    has_password = auth_password_set(cfg)
    error = ""
    next_path = safe_next_path(request.values.get("next"))
    if request.method == "POST":
        password = (request.form.get("web_password") or "").strip()
        confirm = (request.form.get("web_password_confirm") or "").strip()
        if not has_password:
            if not password:
                error = "请先设置密码"
            elif password != confirm:
                error = "两次密码不一致"
            else:
                update_password(cfg, password)
                session["logged_in"] = True
                session["login_at"] = now()
                session["login_user"] = "admin"
                return redirect(next_path)
        else:
            if verify_login_password(cfg, password):
                session["logged_in"] = True
                session["login_at"] = now()
                session["login_user"] = "admin"
                return redirect(next_path)
            error = "密码不正确"
    return render_template_string(
        PAGE_LOGIN,
        first_setup=not has_password,
        message=error,
        next_path=next_path,
        login_hint="首次进入请先设置 Web 密码" if not has_password else "输入 Web 密码后继续",
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    cfg = load_config()
    with lock:
        visible_items = visible_iso_items(state.get("items", {}))
        events = list(reversed(state.get("events", [])[-120:]))
        snapshot = json.loads(json.dumps(state, ensure_ascii=False))
        snapshot["items"] = visible_items
        ordered_items = ordered_visible_items(visible_items, snapshot.get("active"))
        items = ordered_items[:5]
        history_items = ordered_items
    safe_cfg = sanitize_config(cfg)
    return render_template_string(PAGE, cfg=safe_cfg, state=snapshot, items=items, history_items=history_items, events=events, status_label=status_label, badge_class=badge_class, format_size=format_size)


@app.route("/settings", methods=["POST"])
def settings():
    cfg = load_config()
    old_cd2_key = cd2_client_key_from_cfg(cfg)
    cfg["watch_dir"] = request.form.get("watch_dir", cfg["watch_dir"]).strip()
    cfg["output_dir"] = request.form.get("output_dir", cfg["output_dir"]).strip()
    try:
        cfg["scan_interval_seconds"] = parse_int_form("scan_interval_seconds", cfg["scan_interval_seconds"], minimum=5)
        cfg["stable_seconds"] = parse_int_form("stable_seconds", cfg["stable_seconds"], minimum=30)
        cfg["min_free_space_gb"] = parse_int_form("min_free_space_gb", cfg["min_free_space_gb"], minimum=0)
        cfg["cd2_queue_poll_seconds"] = parse_int_form("cd2_queue_poll_seconds", cfg.get("cd2_queue_poll_seconds", 10), minimum=1)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    cfg["enabled"] = "enabled" in request.form
    cfg["delete_source_after_success"] = "delete_source_after_success" in request.form
    cfg["cd2_transfer_enabled"] = "cd2_transfer_enabled" in request.form
    cfg["cd2_require_mount"] = "cd2_require_mount" in request.form
    cfg["cd2_mount_root"] = request.form.get("cd2_mount_root", cfg.get("cd2_mount_root", "/CloudNAS")).strip()
    cfg["cd2_target_dir"] = request.form.get("cd2_target_dir", cfg.get("cd2_target_dir", "/CloudNAS/CloudDrive/00-未整理/00-mkiso")).strip()
    cfg["cd2_api_enabled"] = "cd2_api_enabled" in request.form
    cfg["cd2_auth_mode"] = cd2_auth_mode_from_cfg({"cd2_auth_mode": request.form.get("cd2_auth_mode", cfg.get("cd2_auth_mode", "api_token"))})
    cfg["cd2_api_addr"] = normalize_cd2_api_addr(request.form.get("cd2_api_addr", cfg.get("cd2_api_addr", "host.docker.internal:19798")))
    cfg["cd2_api_username"] = request.form.get("cd2_api_username", cfg.get("cd2_api_username", "")).strip()
    new_password = (request.form.get("web_password") or "").strip()
    new_password_confirm = (request.form.get("web_password_confirm") or "").strip()
    if new_password:
        if new_password != new_password_confirm:
            return jsonify({"ok": False, "message": "登录密码两次输入不一致"}), 400
        cfg["web_password_hash"] = generate_password_hash(new_password)
        if not cfg.get("web_secret_key"):
            cfg["web_secret_key"] = secrets.token_urlsafe(32)
    new_cd2_password = (request.form.get("cd2_api_password") or "").strip()
    if new_cd2_password:
        cfg["cd2_api_password"] = new_cd2_password
    save_config(cfg)
    if old_cd2_key != cd2_client_key_from_cfg(cfg):
        close_cd2_client()
    Path(cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg["output_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_mount_root", "/CloudNAS")).expanduser().mkdir(parents=True, exist_ok=True)
    log("设置已保存")
    if request.form.get("scan"):
        threading.Thread(target=scan_once, args=(cfg,), daemon=True).start()
    return redirect(url_for("index"))


@app.route("/api/cd2/test", methods=["POST"])
def api_cd2_test():
    cfg = load_config()
    if request.form:
        cfg["cd2_api_enabled"] = True
        cfg["cd2_auth_mode"] = cd2_auth_mode_from_cfg({"cd2_auth_mode": request.form.get("cd2_auth_mode", cfg.get("cd2_auth_mode", "api_token"))})
        cfg["cd2_api_addr"] = normalize_cd2_api_addr(request.form.get("cd2_api_addr", cfg.get("cd2_api_addr", "host.docker.internal:19798")))
        cfg["cd2_api_username"] = request.form.get("cd2_api_username", cfg.get("cd2_api_username", "")).strip()
        new_cd2_password = (request.form.get("cd2_api_password") or "").strip()
        if new_cd2_password:
            cfg["cd2_api_password"] = new_cd2_password
    close_cd2_client()
    _, status = fetch_cd2_uploads(cfg)
    if status.get("connected"):
        return jsonify({
            "ok": True,
            "message": status.get("human") or "CD2 连接成功",
            "status": status,
        })
    return jsonify({
        "ok": False,
        "message": status.get("human") or status.get("last_error") or "CD2 连接失败",
        "status": status,
    }), 400



@app.route("/rerun", methods=["POST"])
def rerun_item():
    cfg = load_config()
    source_text = (request.form.get("source") or "").strip()
    if not source_text:
        return jsonify({"ok": False, "message": "\u7f3a\u5c11\u6e90\u8def\u5f84"}), 400
    try:
        source = Path(source_text).expanduser().resolve()
        watch_dir = Path(cfg["watch_dir"]).expanduser().resolve()
    except Exception as exc:
        return jsonify({"ok": False, "message": f"\u6e90\u8def\u5f84\u65e0\u6548: {exc}"}), 400
    if source.parent != watch_dir:
        return jsonify({"ok": False, "message": "\u53ea\u80fd\u624b\u52a8\u5c01\u88c5\u76d1\u63a7\u76ee\u5f55\u4e0b\u7684\u5355\u4e2a\u4efb\u52a1"}), 400
    if not source.exists():
        return jsonify({"ok": False, "message": "\u6e90\u8def\u5f84\u4e0d\u5b58\u5728"}), 404
    pack_iso, pack_reason = should_pack_iso(source)
    if not pack_iso:
        return jsonify({"ok": False, "message": f"\u8be5\u8def\u5f84\u4e0d\u9700\u8981\u5c01\u88c5: {pack_reason}"}), 400
    source_size = size_of(source)
    _, cd2_status = fetch_cd2_uploads(cfg)
    wait_status, wait_reason, pending_task = source_readiness_blocker(source, source_size, cd2_status)
    if wait_status:
        mark_source_waiting(source, wait_status, wait_reason, source_size, pending_task)
        return jsonify({"ok": False, "message": wait_reason}), 409
    with lock:
        if state.get("active") is not None:
            return jsonify({"ok": False, "message": "\u5f53\u524d\u6709\u4efb\u52a1\u6b63\u5728\u6267\u884c\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5"}), 409
        item = state.setdefault("items", {}).setdefault(str(source), {"first_seen": now()})
        item.update({
            "status": "ready",
            "pack_iso": True,
            "last_size": source_size,
            "last_changed": now(),
            "partial_files": False,
            "manual_requested_at": now(),
        })
        item.pop("done_at", None)
        item.pop("target", None)
        save_state_locked()
    log(f"\u624b\u52a8\u91cd\u65b0\u5c01\u88c5: {source}")
    threading.Thread(target=process_item, args=(source, cfg), daemon=True).start()
    return jsonify({"ok": True, "message": "\u5df2\u5f00\u59cb\u624b\u52a8\u5c01\u88c5", "source": str(source)})


@app.route("/api/status")
def api_status():
    cfg = load_config()
    with lock:
        snapshot = json.loads(json.dumps(state, ensure_ascii=False))
    snapshot["items"] = visible_iso_items(snapshot.get("items", {}))
    snapshot_items, snapshot_active, cd2_status = attach_cd2_uploads(cfg, snapshot.get("items", {}), snapshot.get("active"))
    snapshot["items"] = {key: apply_task_timings(item, snapshot_active if snapshot_active and snapshot_active.get("source") == key else None) for key, item in snapshot_items.items()}
    if snapshot_active:
        snapshot["active"] = apply_task_timings(dict(snapshot_active), snapshot_active)
    snapshot["cd2_status"] = cd2_status
    return jsonify({"config": sanitize_config(cfg), "state": snapshot, "cd2_status": cd2_status})


@app.route("/api/directories")
def api_directories():
    cfg = load_config()
    scope = (request.args.get("scope") or "").strip()
    roots = directory_picker_roots(cfg, scope)
    if not roots:
        return jsonify({"ok": False, "message": "无效的目录选择范围"}), 400
    raw_path = (request.args.get("path") or DIRECTORY_PICKER_ROOT).strip() or DIRECTORY_PICKER_ROOT
    if raw_path in {"/", DIRECTORY_PICKER_ROOT}:
        return jsonify(directory_picker_payload_for_roots(roots))
    try:
        path = resolve_absolute_path(raw_path)
    except Exception as exc:
        return jsonify({"ok": False, "message": f"路径无效: {exc}"}), 400
    if not path_in_any_root(path, roots):
        return jsonify({"ok": False, "message": "禁止访问允许范围外的路径"}), 403

    if not path.exists():
        return jsonify({"ok": False, "message": "目录不存在"}), 404
    if not path.is_dir():
        path = path.parent
    if not path_in_any_root(path, roots):
        return jsonify({"ok": False, "message": "禁止访问允许范围外的路径"}), 403

    try:
        children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        children = []
    except OSError as exc:
        return jsonify({"ok": False, "message": f"无法读取目录: {exc}"}), 400

    entries = []
    for child in children:
        try:
            if not child.is_dir():
                continue
            entries.append({
                "name": child.name,
                "path": str(child),
                "readable": os.access(child, os.R_OK | os.X_OK),
            })
        except OSError:
            continue

    return jsonify({
        "ok": True,
        "path": str(path),
        "display_path": str(path),
        "parent": directory_picker_parent(path, roots),
        "entries": entries,
    })


@app.route("/api/browse")
def api_browse():
    cfg = load_config()
    roots = {
        "watch": Path(cfg["watch_dir"]).expanduser(),
        "output": Path(cfg["output_dir"]).expanduser(),
        "cd2": Path(cfg["cd2_target_dir"]).expanduser(),
    }
    root_name = (request.args.get("root") or "watch").strip()
    root = roots.get(root_name)
    if not root:
        return jsonify({"ok": False, "message": "无效的根目录"}), 400
    raw_path = (request.args.get("path") or str(root)).strip() or str(root)
    try:
        path = Path(raw_path).expanduser().resolve()
        root = root.resolve()
    except Exception as exc:
        return jsonify({"ok": False, "message": f"路径无效: {exc}"}), 400
    if not path.exists():
        return jsonify({"ok": False, "message": "目录不存在"}), 404
    if not path.is_dir():
        path = path.parent
    if not path_in_root(path, root):
        return jsonify({"ok": False, "message": "禁止访问根目录外路径"}), 403
    try:
        children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        children = []
    except OSError as exc:
        return jsonify({"ok": False, "message": f"无法读取目录: {exc}"}), 400
    entries = []
    for child in children:
        try:
            stat = child.stat()
            entries.append({
                "name": child.name,
                "path": str(child),
                "type": "dir" if child.is_dir() else "file",
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "readable": os.access(child, os.R_OK | os.X_OK),
            })
        except OSError:
            continue
    parent = path.parent if path.parent != path and path_in_root(path.parent, root) else None
    return jsonify({
        "ok": True,
        "root": root_name,
        "path": str(path),
        "parent": str(parent) if parent else None,
        "entries": entries,
    })


if __name__ == "__main__":
    start_worker_once()
    cfg = load_config()
    Path(cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg["output_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_mount_root", "/CloudNAS")).expanduser().mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=15865, threaded=True)
