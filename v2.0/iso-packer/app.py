#!/usr/bin/env python3
import hashlib
import json
import os
import re
import shutil
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from core import (
    DEFAULT_CONFIG,
    DISC_STRUCTURE_DIRS,
    PARTIAL_EXTENSIONS,
    TERMINAL_STATUSES,
    VIDEO_EXTENSIONS,
    alias_variants_for_path,
    apply_task_timings,
    badge_class,
    cd2_client_key_from_cfg,
    cd2_path_aliases_from_cfg,
    cd2_path_aliases_to_text,
    cd2_remote_source_dirs_to_text,
    format_size,
    normalize_cd2_api_addr,
    normalize_path_text,
    now,
    parse_time,
    parse_cd2_path_alias_lines,
    parse_cd2_remote_source_dirs,
    path_in_root,
    safe_filename,
    safe_next_path,
    safe_volume_id,
    sanitize_config,
    seconds_between,
    status_label,
)
from release_calendar_fetcher import apply_tmdb_result, refresh_release_calendar_cache, tmdb_get_json, tmdb_search_movie, tmdb_settings

try:
    from clouddrive2_client import CloudDriveClient
except Exception:
    CloudDriveClient = None

# 数据目录：优先使用 /data（持久化挂载），否则使用当前目录
APP_DIR = Path(os.getenv("DATA_DIR", "/data"))
PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
LOG_PATH = APP_DIR / "iso-packer.log"
RELEASE_CALENDAR_PATH = PROJECT_DIR / "data" / "release_calendar.json"
LOG_LINE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
LOCAL_MEDIA_POSTER_CACHE_LIMIT = 300
LOG_ERROR_TOKENS = ("失败", "异常", "错误", "报错", "failed", "error", "exception", "traceback")
LOG_CD2_TOKENS = ("cd2", "clouddrive", "网盘", "远程候选", "拉取", "上传")
LOG_FILE_TOKENS = ("文件浏览", "复制", "移动", "删除", "重命名", "file_", "copy", "move", "delete", "rename")
LOG_PACK_TOKENS = ("iso", "封装", "校验", "转存", "转移", "genisoimage", "xorriso")
MEDIA_FILE_EXTENSIONS = VIDEO_EXTENSIONS | {".iso"}
MEDIA_SCAN_MAX_ITEMS = 500


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
lock = threading.RLock()
cd2_lock = threading.RLock()
worker_lock = threading.Lock()
file_operation_lock = threading.RLock()
file_operation_tasks = {}
cd2_candidate_scan_lock = threading.RLock()
cd2_candidate_scan_state = {
    "thread": None,
    "event": None,
    "client": None,
    "config_key": None,
    "started_at": None,
    "started_monotonic": 0.0,
    "timed_out": False,
    "payload": None,
    "last_success": None,
}
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
CD2_GRPC_CHANNEL_OPTIONS = (
    ("grpc.enable_http_proxy", 0),
    ("grpc.keepalive_time_ms", 30000),
    ("grpc.keepalive_timeout_ms", 10000),
    ("grpc.keepalive_permit_without_calls", True),
    ("grpc.http2.max_pings_without_data", 0),
)
state = {"items": {}, "last_scan": None, "active": None, "events": [], "cd2": {}}
worker_started = False
last_log_prune = 0.0
BDMV_REQUIRED_FILES = ("index.bdmv", "MovieObject.bdmv")
BDMV_REQUIRED_DIRS = ("PLAYLIST", "STREAM", "CLIPINF")
COPY_TASK_DONE_STATUSES = {"3", "completed", "complete", "done", "finish", "finished", "success", "succeeded", "已完成"}
CD2_UPLOAD_QUEUE_GRACE_POLLS = 3
CD2_UPLOAD_QUEUE_GRACE_MIN_SECONDS = 30
CD2_UPLOAD_STALL_SECONDS = 30 * 60
CD2_CANDIDATE_SCAN_TIMEOUT_SECONDS = 15
CD2_CANDIDATE_SCAN_CACHE_SECONDS = 30
CD2_WEBHOOK_EVENT_LIMIT = 50
CD2_AUTO_PULL_FAILURE_COOLDOWN_SECONDS = 600
CD2_AUTO_PULL_CREATING_TIMEOUT_SECONDS = 300
CD2_UPLOAD_MATCH_MODES = {"alias_then_suffix", "alias_only"}
FAILURE_LABELS = {
    "insufficient_space": "空间不足",
    "output_exists": "输出ISO已存在",
    "pack_failed": "封装失败",
    "verify_failed": "校验失败",
    "transfer_failed": "CD2 转移失败",
    "target_exists": "上传目录已有同名ISO",
    "cd2_upload_stalled": "CD2 上传停滞",
    "cd2_upload_missing": "CD2 上传任务未出现",
    "unexpected_error": "任务异常",
}
FAILURE_SUGGESTIONS = {
    "insufficient_space": "清理输出目录或降低最小空间阈值后等待下轮扫描。",
    "output_exists": "输出目录已经有同名 ISO，但无法确认它是可复用的完整文件；请手动删除、移动或改名后再重新封装。",
    "pack_failed": "查看系统日志里的 genisoimage 错误，确认原盘结构完整且路径可读。",
    "verify_failed": "保留源目录和 ISO，优先检查 xorriso 是否可用以及输出文件是否完整。",
    "transfer_failed": "检查 CD2 挂载目录、目标路径权限和磁盘空间后重新封装。",
    "target_exists": "上传目录已经有同名 ISO，但无法确认它是同一份完整文件；请手动删除、移动或改名后再重新封装。",
    "cd2_upload_stalled": "点击“重新检测”继续观察；若已在云端确认完整，可使用“确认已上传”。",
    "cd2_upload_missing": "点击“重新检测”重新读取队列；若已在云端确认完整，可使用“确认已上传”。",
    "unexpected_error": "查看系统日志里的异常堆栈，确认后可手动重新封装。",
}
WARNING_LABELS = {
    "delete_source_failed": "源文件删除失败",
    "replaced_iso_cleanup_failed": "旧版本 ISO 清理失败",
}
WARNING_SUGGESTIONS = {
    "delete_source_failed": "ISO 已完成，手动检查源目录占用或权限后再删除。",
    "replaced_iso_cleanup_failed": "新版本 ISO 已完成；请手动删除输出目录或 CD2 成品目录中的旧版本文件。",
}
DIRECTORY_PICKER_ROOT = "@roots"
DIRECTORY_PICKER_SCOPES = {
    "watch_dir": ("watch_dir",),
    "output_dir": ("output_dir",),
    "file_destination": ("watch_dir", "output_dir", "cd2_mount_root"),
    "media_compare": ("output_dir", "cd2_target_dir", "cd2_mount_root"),
    "cd2_mount_root": ("cd2_mount_root",),
    "cd2_target_dir": ("cd2_mount_root", "cd2_target_dir"),
    "cd2_local_pull_dir": ("watch_dir", "cd2_local_pull_dir"),
    "cd2_remote_pull_dest_dir": ("watch_dir", "cd2_local_pull_dir", "cd2_remote_pull_dest_dir"),
}


def resolve_cd2_browser_root(cfg: Dict) -> Path:
    mount_root = normalize_path_text((cfg or {}).get("cd2_mount_root"))
    if mount_root:
        return Path(mount_root).expanduser()
    return Path("/CloudNAS/CloudDrive").expanduser()


def file_browser_roots_from_config(cfg: Dict) -> Dict[str, Path]:
    return {
        "watch": Path(cfg["watch_dir"]).expanduser(),
        "output": Path(cfg["output_dir"]).expanduser(),
        "cd2": resolve_cd2_browser_root(cfg),
    }


def looks_like_disc_structure_dir(path: Path) -> bool:
    if not path.is_dir() or path.name.lower() not in DISC_STRUCTURE_DIRS:
        return False
    try:
        child_names = {child.name.lower() for child in path.iterdir()}
    except (FileNotFoundError, PermissionError, OSError):
        return False
    if path.name.lower() == "bdmv":
        return bool(child_names & {"index.bdmv", "movieobject.bdmv", "stream", "playlist", "clipinf"})
    if path.name.lower() == "video_ts":
        return any(name.endswith(".ifo") for name in child_names)
    return False


def file_browser_disc_type(path: Path) -> str:
    if not path.is_dir():
        return ""
    if looks_like_disc_structure_dir(path):
        return path.name.upper()
    if path.name.lower() in DISC_STRUCTURE_DIRS:
        return ""
    try:
        children = [child for child in path.iterdir() if child.is_dir()]
    except (FileNotFoundError, PermissionError, OSError):
        return ""
    for child in children:
        if looks_like_disc_structure_dir(child):
            return child.name.upper()
    if len(children) == 1:
        try:
            for grandchild in children[0].iterdir():
                if grandchild.is_dir() and looks_like_disc_structure_dir(grandchild):
                    return grandchild.name.upper()
        except (FileNotFoundError, PermissionError, OSError):
            return ""
    return ""


def file_browser_listing_disc_type(path: Path, parent: Path, root_name: str, is_dir: bool) -> str:
    if not is_dir:
        return ""
    if root_name == "cd2":
        name = path.name.lower()
        parent_name = parent.name.lower()
        if name in DISC_STRUCTURE_DIRS:
            return path.name.upper()
        if parent_name in DISC_STRUCTURE_DIRS:
            return parent.name.upper()
        return ""
    return file_browser_disc_type(path)


def file_browser_name_keys(value: str) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    name = text.replace("\\", "/").rsplit("/", 1)[-1]
    stem = name[:-4] if name.lower().endswith(".iso") else name
    keys = {
        name.lower(),
        stem.lower(),
        safe_filename(name).lower(),
        safe_filename(stem).lower(),
    }
    return {key for key in keys if key}


def file_browser_pack_lookup(cfg: Dict, resolve_paths: bool = True, include_names: bool = False) -> Dict[str, Dict]:
    aliases = cd2_path_aliases_from_cfg(cfg or {})

    def variants_for(value: str) -> list[str]:
        variants = list(alias_variants_for_path(value, aliases))
        text = str(value or "")
        should_resolve = (
            resolve_paths
            and (
                bool(re.match(r"^[A-Za-z]:[\\/]", text))
                or "\\" in text
                or (os.name != "nt" and text.startswith("/"))
            )
        )
        if should_resolve:
            try:
                variants.extend(alias_variants_for_path(str(Path(text).expanduser().resolve()), aliases))
            except (OSError, RuntimeError, ValueError):
                pass
        result = []
        seen = set()
        for variant in variants:
            normalized = normalize_path_text(variant)
            key = normalized.lower()
            if normalized and key not in seen:
                seen.add(key)
                result.append(normalized)
        return result

    with lock:
        items = {str(key): dict(value or {}) for key, value in (state.get("items") or {}).items()}
    lookup: Dict[str, Dict] = {}
    for key, item in items.items():
        candidates = [
            key,
            str(item.get("source") or ""),
            str(item.get("cd2_pull_source") or ""),
        ]
        for candidate in candidates:
            for variant in variants_for(candidate):
                normalized = variant.lower()
                if normalized not in lookup:
                    lookup[normalized] = item
        if include_names:
            for candidate in candidates + [str(item.get("target") or "")]:
                for name_key in file_browser_name_keys(candidate):
                    lookup.setdefault(f"name:{name_key}", item)
    return lookup


def file_browser_item_for_path(path: Path, lookup: Dict[str, Dict], cfg: Dict, resolve_path: bool = True, match_name: bool = False) -> Optional[Dict]:
    aliases = cd2_path_aliases_from_cfg(cfg or {})
    variants = list(alias_variants_for_path(str(path), aliases))
    if resolve_path:
        try:
            variants.extend(alias_variants_for_path(str(path.expanduser().resolve()), aliases))
        except (OSError, RuntimeError, ValueError):
            pass
    for variant in variants:
        item = lookup.get(normalize_path_text(variant).lower())
        if item:
            return dict(item)
    if match_name:
        for name_key in file_browser_name_keys(path.name):
            item = lookup.get(f"name:{name_key}")
            if item:
                return dict(item)
    return None


def file_browser_existing_iso_target(path: Path, cfg: Dict) -> str:
    targets: list[Path] = []
    output_dir = Path(str((cfg or {}).get("output_dir") or DEFAULT_CONFIG["output_dir"])).expanduser()
    targets.append(iso_path_for(path, output_dir))
    cd2_target = normalize_path_text((cfg or {}).get("cd2_target_dir") or "")
    if cd2_target:
        targets.append(Path(cd2_target).expanduser() / f"{safe_filename(path.name)}.iso")
    seen = set()
    for target in targets:
        key = normalize_path_text(str(target)).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            if target.exists() and target.is_file():
                return str(target)
        except OSError:
            continue
    return ""


def file_browser_pack_payload(
    path: Path,
    disc_type: str,
    lookup: Dict[str, Dict],
    cfg: Dict,
    check_existing: bool = True,
    match_name: bool = False,
) -> Dict:
    if not disc_type:
        return {}
    if path.name.lower() in DISC_STRUCTURE_DIRS:
        source_path = path.parent
    elif check_existing and looks_like_disc_structure_dir(path):
        source_path = path.parent
    else:
        source_path = path
    item = file_browser_item_for_path(source_path, lookup, cfg, resolve_path=check_existing, match_name=match_name)
    status = str((item or {}).get("status") or "")
    target = str((item or {}).get("target") or "")
    packed_statuses = {"done", "transfer_done", "waiting_cd2_upload"}
    if status in packed_statuses:
        packed = True
    else:
        existing_target = file_browser_existing_iso_target(source_path, cfg) if check_existing else ""
        packed = bool(existing_target)
        if existing_target and not target:
            target = existing_target
    return {
        "pack_state": "packed" if packed else "unpacked",
        "pack_label": "已封装" if packed else "未封装",
        "pack_target": target,
        "pack_task_status": status,
        "pack_task_label": status_label(status) if status else "",
    }


def resolve_file_browser_path(cfg: Dict, root_name: str, raw_path: str) -> tuple[Path, Path]:
    roots = file_browser_roots_from_config(cfg)
    root = roots.get(root_name)
    if not root:
        raise ValueError("无效的根目录")
    target = (raw_path or str(root)).strip() or str(root)
    if target == "/":
        target = str(root)
    path = Path(target).expanduser().resolve()
    root = root.resolve()
    if not path_in_root(path, root):
        raise ValueError("禁止访问根目录外路径")
    return path, root


def file_operation_snapshot(task_id: str) -> Dict:
    with file_operation_lock:
        return dict(file_operation_tasks.get(task_id) or {})


def file_operation_status_payload(limit: int = 6) -> Dict:
    active_statuses = {"queued", "running"}
    with file_operation_lock:
        tasks = [dict(task) for task in file_operation_tasks.values()]
    tasks.sort(key=lambda task: str(task.get("updated_at") or task.get("created_at") or ""), reverse=True)
    items = []
    active_count = 0
    for task in tasks[:limit]:
        status = str(task.get("status") or "queued")
        total = int(task.get("total") or 0)
        done = int(task.get("done") or 0)
        if status in active_statuses:
            active_count += 1
        progress = 0
        if total > 0:
            progress = max(0, min(100, round(done / total * 100, 1)))
        items.append({
            "id": task.get("id"),
            "action": task.get("action"),
            "status": status,
            "phase": f"file_{task.get('action') or 'operation'}",
            "message": task.get("message") or "",
            "total": total,
            "done": done,
            "progress": progress,
            "sources": task.get("sources") or [],
            "destination": task.get("destination") or "",
            "destination_kind": task.get("destination_kind") or "",
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "results": task.get("results") or [],
        })
    return {
        "active_count": active_count,
        "items": items,
    }


def update_file_operation_task(task_id: str, **updates) -> None:
    with file_operation_lock:
        task = file_operation_tasks.setdefault(task_id, {"id": task_id})
        task.update(updates)
        task["updated_at"] = now()


def copy_file_operation_source(source: Path, target: Path) -> None:
    if source.is_dir():
        if path_in_root(target.parent, source):
            raise ValueError("目标目录不能位于源目录内部")
        shutil.copytree(source, target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def directory_size_summary(path: Path) -> Dict:
    total = 0
    file_count = 0
    dir_count = 0
    partial = False
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        stat = entry.stat(follow_symlinks=False)
                        if entry.is_dir(follow_symlinks=False):
                            dir_count += 1
                            stack.append(Path(entry.path))
                        else:
                            file_count += 1
                            total += stat.st_size
                    except OSError:
                        partial = True
        except OSError:
            partial = True
    return {
        "size": total,
        "file_count": file_count,
        "dir_count": dir_count,
        "partial": partial,
    }


def file_property_payload(path: Path, root_name: str, root: Path, cfg: Optional[Dict] = None) -> Dict:
    cfg = cfg or load_config()
    stat = path.stat()
    is_dir = path.is_dir()
    summary = directory_size_summary(path) if is_dir else {
        "size": stat.st_size,
        "file_count": 1,
        "dir_count": 0,
        "partial": False,
    }
    try:
        usage = shutil.disk_usage(path if is_dir else path.parent)
        disk = {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
        }
    except OSError:
        disk = None
    disc_type = file_browser_disc_type(path) if is_dir else ""
    payload = {
        "ok": True,
        "root": root_name,
        "root_path": str(root),
        "name": path.name or str(path),
        "path": str(path),
        "type": "dir" if is_dir else "file",
        "size": summary["size"],
        "file_count": summary["file_count"],
        "dir_count": summary["dir_count"],
        "partial": summary["partial"],
        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "ctime": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
        "atime": datetime.fromtimestamp(stat.st_atime).strftime("%Y-%m-%d %H:%M:%S"),
        "readable": os.access(path, os.R_OK | (os.X_OK if is_dir else 0)),
        "writable": os.access(path, os.W_OK),
        "disk": disk,
    }
    if disc_type:
        payload["disc_type"] = disc_type
        payload.update(file_browser_pack_payload(path, disc_type, file_browser_pack_lookup(cfg), cfg))
    return payload


def run_file_operation_task(task_id: str, action: str, sources: list[Path], destination: Optional[Path]) -> None:
    update_file_operation_task(task_id, status="running", message="正在处理", done=0)
    results = []
    try:
        if destination and action in {"copy", "move"}:
            destination.mkdir(parents=True, exist_ok=True)
        for index, source in enumerate(sources, start=1):
            item = {"source": str(source), "ok": False}
            try:
                if not source.exists():
                    raise FileNotFoundError("源路径不存在")
                if action == "copy":
                    target = (destination / source.name).resolve()
                    if target.exists():
                        raise FileExistsError(f"目标已存在: {target}")
                    copy_file_operation_source(source, target)
                    item.update({"ok": True, "target": str(target)})
                elif action == "move":
                    target = (destination / source.name).resolve()
                    if target.exists():
                        raise FileExistsError(f"目标已存在: {target}")
                    if source.is_dir() and path_in_root(target.parent, source):
                        raise ValueError("目标目录不能位于源目录内部")
                    shutil.move(str(source), str(target))
                    item.update({"ok": True, "target": str(target)})
                elif action == "rename":
                    if len(sources) != 1 or destination is None:
                        raise ValueError("重命名只能处理单个条目")
                    if destination.exists():
                        raise FileExistsError(f"目标已存在: {destination}")
                    source.rename(destination)
                    item.update({"ok": True, "target": str(destination)})
                elif action == "delete":
                    if source.is_dir():
                        shutil.rmtree(source)
                    else:
                        source.unlink()
                    item.update({"ok": True})
                else:
                    raise ValueError("不支持的操作")
            except Exception as exc:
                item["message"] = str(exc)
            results.append(item)
            update_file_operation_task(task_id, done=index, results=results)
        failed = [item for item in results if not item.get("ok")]
        status = "failed" if len(failed) == len(results) else ("partial" if failed else "done")
        message = "操作完成" if status == "done" else f"{len(failed)} 项处理失败"
        update_file_operation_task(task_id, status=status, message=message, done=len(results), results=results)
        log(f"文件浏览{action}操作完成: {len(results) - len(failed)}/{len(results)}")
    except Exception as exc:
        update_file_operation_task(task_id, status="failed", message=str(exc), results=results)


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


def clamp_int_arg(name: str, fallback: int, minimum: int = 1, maximum: int = 500) -> int:
    try:
        value = int(request.args.get(name) or fallback)
    except (TypeError, ValueError):
        value = fallback
    return max(minimum, min(maximum, value))


def token_in_text(tokens, text: str, lowered: str) -> bool:
    for token in tokens:
        raw = str(token or "")
        if not raw:
            continue
        if raw.lower() in lowered or raw in text:
            return True
    return False


def classify_log_message(message: str) -> str:
    text = str(message or "")
    lowered = text.lower()
    if token_in_text(LOG_ERROR_TOKENS, text, lowered):
        return "error"
    if token_in_text(LOG_CD2_TOKENS, text, lowered):
        return "cd2"
    if token_in_text(LOG_FILE_TOKENS, text, lowered):
        return "file"
    if token_in_text(LOG_PACK_TOKENS, text, lowered):
        return "pack"
    return "system"


def log_category_label(category: str) -> str:
    return {
        "error": "异常",
        "duplicate": "重复",
        "pack": "封装",
        "cd2": "CD2",
        "file": "文件",
        "system": "系统",
    }.get(category or "system", "系统")


def log_event_level(category: str, status: str = "") -> str:
    if category == "error" or status in {"failed", "verify_failed", "transfer_failed", "partial"}:
        return "error"
    if status in {"done", "transfer_done", "completed", "complete", "success", "succeeded"}:
        return "success"
    if status in {"running", "queued", "waiting_cd2_pull", "waiting_cd2_upload", "transferring", "refreshing_cd2_dir"}:
        return "active"
    return "info"


def extract_log_path_hint(message: str) -> str:
    text = str(message or "")
    pattern = r"([A-Za-z]:[\\/][^\s，,；;]+|/[^\s，,；;]+(?:/[^\s，,；;]+)*)"
    for match in re.finditer(pattern, text):
        value = match.group(1).strip().strip("。.,，；;")
        if len(value) > 2:
            return value
    return ""


def log_event_id(source: str, timestamp: str, message: str, path: str = "") -> str:
    raw = f"{source}|{timestamp}|{message}|{path}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:16]


def parse_log_line_event(line: str, source: str = "log_file") -> Dict:
    raw = str(line or "").strip()
    match = LOG_LINE_RE.match(raw)
    timestamp = match.group(1) if match else ""
    message = raw[match.end():].strip() if match else raw
    category = classify_log_message(message)
    path = extract_log_path_hint(message)
    return {
        "id": log_event_id(source, timestamp, message, path),
        "time": timestamp,
        "category": category,
        "category_label": log_category_label(category),
        "level": log_event_level(category),
        "message": message,
        "path": path,
        "source": source,
    }


def append_unique_log_event(events: list[Dict], seen: set[str], event: Dict) -> None:
    message = str(event.get("message") or "").strip()
    if not message:
        return
    key = f"{event.get('time') or ''}|{message}|{event.get('path') or ''}"
    if key in seen:
        return
    seen.add(key)
    events.append(event)


def recent_log_file_lines(limit: int) -> list[str]:
    if not LOG_PATH.exists():
        return []
    try:
        return LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
    except OSError:
        return []


def task_log_event(source: str, item: Dict) -> Dict:
    status = str((item or {}).get("status") or "")
    category = "error" if status in {"failed", "verify_failed", "transfer_failed"} else "pack"
    timestamp = ""
    parsed = item_timestamp(item)
    if parsed:
        timestamp = parsed.strftime("%Y-%m-%d %H:%M:%S")
    elif (item or {}).get("first_seen"):
        timestamp = str(item.get("first_seen"))
    name = item_display_name(source)
    message = f"{status_label(status)} · {name}" if status else name
    detail = (item or {}).get("error") or (item or {}).get("failure_message") or (item or {}).get("warning") or ""
    if detail:
        message = f"{message}：{detail}"
    return {
        "id": log_event_id("task", timestamp, message, source),
        "time": timestamp,
        "category": category,
        "category_label": log_category_label(category),
        "level": log_event_level(category, status),
        "message": message,
        "path": source,
        "source": "task",
        "status": status,
        "target": (item or {}).get("target") or "",
        "size": (item or {}).get("last_size") or (item or {}).get("size") or 0,
        "size_human": format_size((item or {}).get("last_size") or (item or {}).get("size") or 0),
    }


def file_operation_log_events(limit: int = 20) -> list[Dict]:
    action_labels = {"copy": "复制", "move": "移动", "delete": "删除", "rename": "重命名"}
    events = []
    for task in file_operation_status_payload(limit=limit).get("items") or []:
        timestamp = str(task.get("updated_at") or task.get("created_at") or "")
        status = str(task.get("status") or "")
        action = str(task.get("action") or "")
        label = action_labels.get(action, action or "操作")
        message = f"文件{label} · {task.get('message') or status or '进行中'}"
        if task.get("total"):
            message = f"{message}（{task.get('done') or 0}/{task.get('total')}）"
        path = ""
        sources = task.get("sources") or []
        if sources:
            path = str(sources[0] or "")
        elif task.get("destination"):
            path = str(task.get("destination"))
        category = "error" if status in {"failed", "partial"} else "file"
        events.append({
            "id": log_event_id("file_operation", timestamp, message, path),
            "time": timestamp,
            "category": category,
            "category_label": log_category_label(category),
            "level": log_event_level(category, status),
            "message": message,
            "path": path,
            "source": "file_operation",
            "status": status,
            "progress": task.get("progress") or 0,
        })
    return events


def cd2_state_log_events(snapshot: Dict) -> list[Dict]:
    cd2_state = (snapshot or {}).get("cd2") or {}
    events = []
    sources = [
        ("pull", "recent_results", "CD2 拉取", "created_at"),
        ("monitor_copy", "recent_results", "CD2 转存到监控", "checked_at"),
        ("refresh", "recent_results", "CD2 目录刷新", "checked_at"),
    ]
    for section, list_key, label, time_key in sources:
        for item in ((cd2_state.get(section) or {}).get(list_key) or [])[-20:]:
            timestamp = str((item or {}).get(time_key) or (item or {}).get("created_at") or "")
            ok = bool((item or {}).get("ok", True))
            raw_message = str((item or {}).get("message") or "")
            status = str((item or {}).get("status") or "")
            is_duplicate = status == "duplicate" or cd2_already_exists_message(raw_message)
            if is_duplicate:
                message = f"{label} · 目标已存在，跳过转存"
            else:
                message = f"{label} · {raw_message or ('完成' if ok else '失败')}"
            path = str((item or {}).get("source_path") or (item or {}).get("source") or (item or {}).get("dest_dir") or "")
            category = "duplicate" if is_duplicate else ("cd2" if ok else "error")
            events.append({
                "id": log_event_id(f"cd2_{section}", timestamp, message, path),
                "time": timestamp,
                "category": category,
                "category_label": log_category_label(category),
                "level": log_event_level(category, "done" if ok or is_duplicate else "failed"),
                "message": message,
                "path": path,
                "source": f"cd2_{section}",
                "status": "duplicate" if is_duplicate else ("done" if ok else "failed"),
            })
    for item in ((cd2_state.get("webhook") or {}).get("recent_events") or [])[-30:]:
        timestamp = str((item or {}).get("received_at") or "")
        path = str((item or {}).get("path") or "")
        message = f"CD2 事件 · {(item or {}).get('event') or 'unknown'}"
        if path:
            message = f"{message}：{path}"
        events.append({
            "id": log_event_id("cd2_webhook", timestamp, message, path),
            "time": timestamp,
            "category": "cd2",
            "category_label": log_category_label("cd2"),
            "level": "info",
            "message": message,
            "path": path,
            "source": "cd2_webhook",
        })
    return events


def log_event_sort_value(event: Dict) -> datetime:
    return parse_time((event or {}).get("time")) or datetime.min


def logs_payload() -> Dict:
    limit = clamp_int_arg("limit", 200, minimum=50, maximum=500)
    type_filter = str(request.args.get("type") or "all").strip().lower()
    query = str(request.args.get("q") or "").strip().lower()
    with lock:
        snapshot = json.loads(json.dumps(state, ensure_ascii=False))
    events = []
    seen = set()
    for line in recent_log_file_lines(max(limit * 3, 300)):
        append_unique_log_event(events, seen, parse_log_line_event(line, "log_file"))
    for line in (snapshot.get("events") or [])[-200:]:
        append_unique_log_event(events, seen, parse_log_line_event(line, "memory"))
    for source, item in visible_iso_items(snapshot.get("items", {})).items():
        append_unique_log_event(events, seen, task_log_event(source, item))
    for event in file_operation_log_events():
        append_unique_log_event(events, seen, event)
    for event in cd2_state_log_events(snapshot):
        append_unique_log_event(events, seen, event)

    events.sort(key=log_event_sort_value, reverse=True)
    summary = {
        "total": len(events),
        "error": sum(1 for event in events if event.get("category") == "error"),
        "duplicate": sum(1 for event in events if event.get("category") == "duplicate"),
        "pack": sum(1 for event in events if event.get("category") == "pack"),
        "cd2": sum(1 for event in events if event.get("category") == "cd2"),
        "file": sum(1 for event in events if event.get("category") == "file"),
        "system": sum(1 for event in events if event.get("category") == "system"),
    }

    filtered = events
    if type_filter != "all":
        filtered = [event for event in filtered if event.get("category") == type_filter]
    if query:
        filtered = [
            event for event in filtered
            if query in str(event.get("message") or "").lower()
            or query in str(event.get("path") or "").lower()
            or query in str(event.get("status") or "").lower()
        ]
    with cd2_lock:
        cached_cd2_status = dict(cd2_client_cache.get("upload_status") or {})
    return {
        "ok": True,
        "events": filtered[:limit],
        "summary": summary,
        "filters": {"type": type_filter, "q": query, "limit": limit},
        "file_operations": file_operation_status_payload(limit=8),
        "cd2_status": ui_safe_cd2_status(cached_cd2_status),
    }


def load_config() -> Dict:
    ensure_app_dir()
    if not CONFIG_PATH.exists():
        cfg = DEFAULT_CONFIG.copy()
        cfg["cd2_path_aliases_text"] = cd2_path_aliases_to_text(cfg)
        cfg["cd2_remote_source_dirs_text"] = cd2_remote_source_dirs_to_text(cfg)
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
    migrated = migrate_config_schema(cfg, data)
    migrate_legacy_cd2_pull_config(cfg, data)
    cfg["cd2_path_aliases"] = cd2_path_aliases_from_cfg(cfg)
    cfg["cd2_path_aliases_text"] = cd2_path_aliases_to_text(cfg)
    cfg["cd2_remote_source_dirs"] = parse_cd2_remote_source_dirs(cfg.get("cd2_remote_source_dirs"))
    cfg["cd2_remote_source_dirs_text"] = cd2_remote_source_dirs_to_text(cfg)
    if not cfg.get("web_secret_key"):
        cfg["web_secret_key"] = secrets.token_urlsafe(32)
        migrated = True
    if migrated:
        save_config(cfg)
    return cfg


def migrate_config_schema(cfg: Dict, raw: Dict) -> bool:
    try:
        raw_version = int(raw.get("config_schema_version") or 0)
    except (TypeError, ValueError):
        raw_version = 0
    target_version = int(DEFAULT_CONFIG.get("config_schema_version") or 0)
    changed = False
    if raw_version < 2:
        cfg["cd2_transfer_enabled"] = True
        cfg["cd2_wait_upload_complete"] = True
        changed = True
    if cfg.get("config_schema_version") != target_version:
        cfg["config_schema_version"] = target_version
        changed = True
    return changed


def migrate_legacy_cd2_pull_config(cfg: Dict, raw: Dict) -> None:
    if parse_cd2_remote_source_dirs(cfg.get("cd2_remote_source_dirs")):
        return
    legacy_sources = parse_cd2_remote_source_dirs(
        raw.get("cd2_remote_source_dir") or raw.get("cd2_remote_scan_dir") or raw.get("cd2_remote_source_dirs_text")
    )
    if legacy_sources:
        cfg["cd2_remote_source_dirs"] = legacy_sources
        return
    legacy_dest = normalize_path_text(raw.get("cd2_remote_pull_dest_dir"))
    if not legacy_dest:
        return
    lowered = legacy_dest.lower()
    looks_like_source_dir = any(marker in lowered for marker in ("bdmv", "原盘", "01-bdmv"))
    if looks_like_source_dir:
        cfg["cd2_remote_source_dirs"] = [legacy_dest]
        cfg["cd2_remote_pull_dest_dir"] = ""


def save_config(cfg: Dict) -> None:
    ensure_app_dir()
    tmp = CONFIG_PATH.with_suffix(".tmp")
    saved = {key: value for key, value in (cfg or {}).items() if key in DEFAULT_CONFIG}
    tmp.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def env_flag_enabled(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def auth_enabled(cfg: Dict) -> bool:
    return not env_flag_enabled("ISO_PACKER_DISABLE_AUTH")


def cd2_pull_disabled() -> bool:
    return env_flag_enabled("ISO_PACKER_DISABLE_CD2_PULL")


def cd2_status_poll_disabled() -> bool:
    return env_flag_enabled("ISO_PACKER_DISABLE_CD2_STATUS_POLL")


def load_state() -> None:
    global state
    if STATE_PATH.exists():
        try:
            loaded = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass
    if not isinstance(state.get("items"), dict):
        state["items"] = {}
    if not isinstance(state.get("cd2"), dict):
        state["cd2"] = {}
    if not isinstance(state["cd2"].get("auto_pull_claims"), dict):
        state["cd2"]["auto_pull_claims"] = {}


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
        raw_values = [cfg.get(field)]
        if scope != "media_compare" or not raw_values[0]:
            raw_values.append(DEFAULT_CONFIG.get(field))
        for raw in raw_values:
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


def int_config(cfg: Dict, key: str, fallback: int, minimum: Optional[int] = None) -> int:
    try:
        value = int(float((cfg or {}).get(key, fallback)))
    except (TypeError, ValueError):
        value = fallback
    if minimum is not None:
        value = max(minimum, value)
    return value


def cd2_cache_status_fields(cfg: Dict, checked_at: Optional[str], cache_hit: bool = False) -> Dict:
    poll_seconds = int_config(cfg, "cd2_queue_poll_seconds", DEFAULT_CONFIG["cd2_queue_poll_seconds"], minimum=1)
    checked_dt = parse_time(checked_at)
    age_seconds = seconds_between(checked_at) if checked_dt else None
    expires_in = max(0, poll_seconds - int(age_seconds or 0)) if checked_dt else 0
    expires_at = (checked_dt + timedelta(seconds=poll_seconds)).strftime("%Y-%m-%d %H:%M:%S") if checked_dt else ""
    if not checked_dt:
        cache_human = f"未缓存，轮询 {poll_seconds}s"
    elif cache_hit:
        cache_human = f"缓存 {age_seconds}s，{expires_in}s 后刷新"
    else:
        cache_human = f"实时刷新，{poll_seconds}s 后过期"
    return {
        "cache_hit": bool(cache_hit),
        "cache_ttl_seconds": poll_seconds,
        "cache_age_seconds": age_seconds,
        "cache_expires_in_seconds": expires_in,
        "cache_expires_at": expires_at,
        "cache_human": cache_human,
    }


def set_failure(item: Dict, code: str, message: Optional[str] = None) -> None:
    item["failure_code"] = code
    item["failure_label"] = FAILURE_LABELS.get(code, code)
    if code in FAILURE_SUGGESTIONS:
        item["failure_suggestion"] = FAILURE_SUGGESTIONS[code]
    if message is not None:
        item["error"] = message


def clear_failure(item: Dict) -> None:
    item.pop("failure_code", None)
    item.pop("failure_label", None)
    item.pop("failure_suggestion", None)


def set_warning(item: Dict, code: str, message: str) -> None:
    item["warning_code"] = code
    item["warning_label"] = WARNING_LABELS.get(code, code)
    item["warning_message"] = message
    if code in WARNING_SUGGESTIONS:
        item["warning_suggestion"] = WARNING_SUGGESTIONS[code]


def clear_warning(item: Dict) -> None:
    item.pop("warning_code", None)
    item.pop("warning_label", None)
    item.pop("warning_message", None)
    item.pop("warning_suggestion", None)


def with_issue_guidance(item: Dict) -> Dict:
    copy = dict(item or {})
    failure_code = copy.get("failure_code")
    if failure_code and not copy.get("failure_suggestion") and failure_code in FAILURE_SUGGESTIONS:
        copy["failure_suggestion"] = FAILURE_SUGGESTIONS[failure_code]
    warning_code = copy.get("warning_code")
    if warning_code and not copy.get("warning_suggestion") and warning_code in WARNING_SUGGESTIONS:
        copy["warning_suggestion"] = WARNING_SUGGESTIONS[warning_code]
    return copy


def task_issue_text(item: Dict) -> str:
    item = with_issue_guidance(item)
    if item.get("failure_label"):
        detail = item.get("error") or item.get("reason") or item.get("last_error") or ""
        parts = [f"{item['failure_label']}: {detail}" if detail else str(item["failure_label"])]
        if item.get("failure_suggestion"):
            parts.append(f"建议：{item['failure_suggestion']}")
        return "；".join(parts)
    if item.get("warning_label"):
        detail = item.get("warning_message") or item.get("error") or ""
        parts = [f"{item['warning_label']}: {detail}" if detail else str(item["warning_label"])]
        if item.get("warning_suggestion"):
            parts.append(f"建议：{item['warning_suggestion']}")
        return "；".join(parts)
    value = item.get("error") or item.get("reason") or item.get("last_error") or ""
    return str(value) if value else "-"


def cd2_webhook_secret_matches(cfg: Dict) -> bool:
    expected = str((cfg or {}).get("cd2_webhook_secret") or "").strip()
    if not expected:
        return False
    provided = (
        request.headers.get("X-ISO-Packer-Token")
        or request.headers.get("X-CD2-Webhook-Token")
        or request.args.get("token")
        or request.form.get("token")
        or ""
    )
    return secrets.compare_digest(str(provided or ""), expected)


def cd2_webhook_payload() -> Dict:
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return dict(request.form.items())


def apply_cd2_api_form(cfg: Dict, form) -> Dict:
    if not form:
        return cfg
    cfg["cd2_api_enabled"] = True
    cfg["cd2_auth_mode"] = cd2_auth_mode_from_cfg({"cd2_auth_mode": form.get("cd2_auth_mode", cfg.get("cd2_auth_mode", "api_token"))})
    cfg["cd2_api_addr"] = normalize_cd2_api_addr(form.get("cd2_api_addr", cfg.get("cd2_api_addr", "host.docker.internal:19798")))
    cfg["cd2_api_username"] = form.get("cd2_api_username", cfg.get("cd2_api_username", "")).strip()
    new_cd2_password = (form.get("cd2_api_password") or "").strip()
    if new_cd2_password:
        cfg["cd2_api_password"] = new_cd2_password
    return cfg


def normalize_tmdb_domain(value: str, fallback: str) -> str:
    text = str(value or "").strip().strip("/")
    if not text:
        text = fallback
    text = re.sub(r"^https?://", "", text, flags=re.I)
    return text.strip("/") or fallback


def apply_tmdb_form(cfg: Dict, form) -> Dict:
    if not form:
        return cfg
    cfg["tmdb_api_enabled"] = "tmdb_api_enabled" in form or str(form.get("tmdb_api_enabled", "")).lower() in {"1", "true", "on", "yes"}
    cfg["tmdb_api_domain"] = normalize_tmdb_domain(form.get("tmdb_api_domain", cfg.get("tmdb_api_domain")), "api.themoviedb.org")
    cfg["tmdb_image_domain"] = normalize_tmdb_domain(form.get("tmdb_image_domain", cfg.get("tmdb_image_domain")), "image.tmdb.org")
    new_token = str(form.get("tmdb_api_token") or "").strip()
    if new_token:
        cfg["tmdb_api_token"] = new_token
    return cfg


def tmdb_config_from_cfg(cfg: Dict) -> Dict:
    cfg = cfg or {}
    api_key = str(cfg.get("tmdb_api_token") or "").strip()
    bearer_token = str(cfg.get("tmdb_bearer_token") or "").strip()
    env_api_key = str(os.environ.get("TMDB_API_KEY") or "").strip()
    env_bearer_token = str(os.environ.get("TMDB_BEARER_TOKEN") or "").strip()
    normalized = tmdb_settings({
        "enabled": bool(cfg.get("tmdb_api_enabled") or env_api_key or env_bearer_token),
        "api_key": api_key or env_api_key,
        "bearer_token": bearer_token or env_bearer_token,
        "api_domain": normalize_tmdb_domain(cfg.get("tmdb_api_domain"), "api.themoviedb.org"),
        "image_domain": normalize_tmdb_domain(cfg.get("tmdb_image_domain"), "image.tmdb.org"),
    })
    return {
        "enabled": bool(normalized.get("enabled")),
        "api_key": str(normalized.get("api_key") or "").strip(),
        "bearer_token": str(normalized.get("bearer_token") or "").strip(),
        "api_domain": str(normalized.get("api_base") or "https://api.themoviedb.org").strip(),
        "image_domain": str(normalized.get("image_base") or "https://image.tmdb.org").strip(),
    }


def cd2_webhook_fingerprint(payload: Dict) -> str:
    relevant = {
        key: payload.get(key)
        for key in sorted(payload or {})
        if str(key).lower() not in {"token", "secret", "password", "authorization"}
    }
    body = json.dumps(relevant, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def record_cd2_webhook_event(cfg: Dict, payload: Dict) -> Dict:
    now_value = now()
    fingerprint = cd2_webhook_fingerprint(payload)
    debounce_seconds = int_config(cfg, "cd2_event_debounce_seconds", 10, minimum=0)
    dedupe_ttl = int_config(cfg, "cd2_event_dedupe_ttl_seconds", 600, minimum=0)
    event = {
        "received_at": now_value,
        "source": str(cfg.get("cd2_event_source") or "cd2"),
        "fingerprint": fingerprint,
        "event": str(payload.get("event") or payload.get("type") or payload.get("action") or "unknown"),
        "path": str(payload.get("path") or payload.get("file") or payload.get("name") or ""),
    }
    with lock:
        cd2_state = state.setdefault("cd2", {})
        webhook_state = cd2_state.setdefault("webhook", {})
        recent = list(webhook_state.get("recent_events") or [])
        recent = [
            item for item in recent
            if dedupe_ttl <= 0 or seconds_between(item.get("received_at")) <= dedupe_ttl
        ]
        duplicate = any(item.get("fingerprint") == fingerprint for item in recent)
        last_triggered_at = webhook_state.get("last_triggered_at")
        debounced = bool(last_triggered_at and seconds_between(last_triggered_at) < debounce_seconds)
        webhook_state.update({
            "last_event": event,
            "last_received_at": now_value,
            "duplicate_count": int(webhook_state.get("duplicate_count") or 0) + (1 if duplicate else 0),
            "debounced_count": int(webhook_state.get("debounced_count") or 0) + (1 if debounced else 0),
        })
        if not duplicate:
            recent.append(event)
        webhook_state["recent_events"] = recent[-CD2_WEBHOOK_EVENT_LIMIT:]
        should_scan = not duplicate and not debounced
        if should_scan:
            webhook_state["last_triggered_at"] = now_value
            webhook_state["last_scan_reason"] = f"{event['event']} {event['path']}".strip()
        save_state_locked()
    return {"event": event, "duplicate": duplicate, "debounced": debounced, "should_scan": should_scan}


def latest_cd2_webhook_event_for_candidate(candidate: Path, cfg: Dict) -> Optional[Dict]:
    with lock:
        event = ((state.get("cd2") or {}).get("webhook") or {}).get("last_event")
    if not event:
        return None
    event_path = event.get("path") or ""
    if not event_path or not cd2_path_matches_candidate(event_path, candidate, cfg):
        return None
    return dict(event)


def cd2_remote_path_for_refresh(path: str, cfg: Dict) -> str:
    aliases = cd2_path_aliases_from_cfg(cfg or {})
    for value in alias_variants_for_path(path, aliases):
        normalized = normalize_path_text(value)
        for alias in aliases:
            remote = normalize_path_text((alias or {}).get("remote"))
            if remote and (normalized == remote or normalized.startswith(remote + "/")):
                return normalized
    return normalize_path_text(path)


def cd2_local_path_to_remote(path: str, cfg: Dict) -> str:
    normalized = normalize_path_text(path)
    if not normalized:
        return ""
    for alias in cd2_path_aliases_from_cfg(cfg or {}):
        local = normalize_path_text((alias or {}).get("local"))
        remote = normalize_path_text((alias or {}).get("remote"))
        if not local or not remote:
            continue
        if normalized == local:
            return remote
        if normalized.startswith(local + "/"):
            return normalize_path_text(remote + normalized[len(local):])
    return ""


def create_cd2_pull_tasks_for_browser_sources(cfg: Dict, sources: list[Path]) -> tuple[Dict, int]:
    if not (cfg.get("cd2_manual_pull_enabled") or cfg.get("cd2_auto_pull_enabled")):
        return {"ok": False, "message": "CD2 拉取未启用，请先开启手动拉取或自动拉取"}, 400

    results = []
    ok_count = 0
    last_status = 400
    for source in sources:
        remote_path = cd2_local_path_to_remote(str(source), cfg)
        if not remote_path:
            results.append({
                "ok": False,
                "source": str(source),
                "message": "所选路径不能映射到 CD2 远端路径，请检查路径别名",
            })
            continue
        result, status_code = create_cd2_pull_task(cfg, remote_path, mode="manual")
        last_status = status_code
        result = dict(result or {})
        result.setdefault("source", str(source))
        result.setdefault("source_path", remote_path)
        results.append(result)
        if result.get("ok"):
            ok_count += 1

    failed_count = len(results) - ok_count
    if ok_count == 0:
        message = (results[0].get("message") if results else "") or "CD2 远程拉取任务创建失败"
        return {
            "ok": False,
            "remote_pull": True,
            "message": message,
            "created_count": 0,
            "failed_count": failed_count,
            "pulls": results,
        }, last_status or 400

    message = f"已提交 {ok_count} 个 CD2 远程拉取任务"
    if failed_count:
        message += f"，{failed_count} 个失败"
    return {
        "ok": True,
        "remote_pull": True,
        "message": message,
        "created_count": ok_count,
        "failed_count": failed_count,
        "pulls": results,
    }, 200


def cd2_monitor_copy_dest_dir_from_cfg(cfg: Dict) -> str:
    roots = parse_cd2_remote_source_dirs((cfg or {}).get("cd2_remote_source_dirs"))
    if not roots:
        return ""
    return cd2_remote_path_for_refresh(roots[0], cfg)


def record_cd2_monitor_copy_result(result: Dict) -> None:
    with lock:
        cd2_state = state.setdefault("cd2", {})
        copy_state = cd2_state.setdefault("monitor_copy", {})
        copy_state["last_result"] = dict(result)
        recent = list(copy_state.get("recent_results") or [])
        recent.append(dict(result))
        copy_state["recent_results"] = recent[-20:]
        save_state_locked()


def create_cd2_monitor_copy_tasks_for_browser_sources(cfg: Dict, sources: list[Path]) -> tuple[Dict, int]:
    dest_dir = cd2_monitor_copy_dest_dir_from_cfg(cfg)
    if not dest_dir:
        return {"ok": False, "message": "请先在设置页配置网盘监控目录"}, 400
    if cd2_pull_disabled():
        return {"ok": False, "message": "本地预览已禁用真实 CD2 文件任务"}, 400

    client = get_cd2_client(cfg)
    if client is None:
        return {"ok": False, "message": cd2_client_cache.get("last_error") or "CD2 API 未连接"}, 400
    if not hasattr(client, "copy_file"):
        return {"ok": False, "message": "当前 clouddrive2-client 不支持创建复制任务"}, 400

    results = []
    ok_count = 0
    duplicate_count = 0
    last_status = 400
    for source in sources:
        remote_path = cd2_local_path_to_remote(str(source), cfg)
        if not remote_path:
            result = {
                "ok": False,
                "source": str(source),
                "message": "所选路径不能映射到 CD2 远端路径，请检查路径别名",
            }
            results.append(result)
            record_cd2_monitor_copy_result({**result, "dest_dir": dest_dir, "checked_at": now()})
            continue
        if remote_path_under(remote_path, dest_dir):
            result = {
                "ok": False,
                "source": str(source),
                "source_path": remote_path,
                "message": "所选目录已经在网盘监控目录内，无需复制",
            }
            results.append(result)
            record_cd2_monitor_copy_result({**result, "dest_dir": dest_dir, "checked_at": now()})
            continue
        try:
            copy_result = client.copy_file([remote_path], dest_dir)
            ok, message, result_paths = cd2_result_success(copy_result)
        except Exception as exc:
            ok, message, result_paths = False, cd2_error_message(exc), []
        duplicate = (not ok) and cd2_already_exists_message(message)
        if duplicate:
            ok = True
            message = "目标已存在，跳过转存"
        result = {
            "ok": ok,
            "status": "duplicate" if duplicate else ("done" if ok else "failed"),
            "source": str(source),
            "source_path": remote_path,
            "dest_dir": dest_dir,
            "message": message or ("CD2 网盘复制任务已创建" if ok else "CD2 网盘复制任务创建失败"),
            "result_paths": result_paths,
            "checked_at": now(),
        }
        results.append(result)
        record_cd2_monitor_copy_result(result)
        if ok:
            if duplicate:
                duplicate_count += 1
            else:
                ok_count += 1
            last_status = 200
        else:
            last_status = 400

    failed_count = len(results) - ok_count - duplicate_count
    if ok_count == 0 and duplicate_count == 0:
        message = (results[0].get("message") if results else "") or "CD2 网盘复制任务创建失败"
        return {
            "ok": False,
            "remote_copy": True,
            "message": message,
            "created_count": 0,
            "skipped_count": 0,
            "failed_count": failed_count,
            "dest_dir": dest_dir,
            "copies": results,
        }, last_status or 400

    if ok_count:
        message = f"已提交 {ok_count} 个 CD2 网盘复制任务"
    else:
        message = ""
    if duplicate_count:
        message = f"{message}，{duplicate_count} 个目标已存在已跳过" if message else f"{duplicate_count} 个目标已存在，已跳过转存"
    if failed_count:
        message = f"{message}，{failed_count} 个失败" if message else f"{failed_count} 个失败"
    return {
        "ok": True,
        "remote_copy": True,
        "message": message,
        "created_count": ok_count,
        "skipped_count": duplicate_count,
        "failed_count": failed_count,
        "dest_dir": dest_dir,
        "copies": results,
    }, 200


def cd2_pull_dest_dir_from_cfg(cfg: Dict) -> str:
    explicit = normalize_path_text((cfg or {}).get("cd2_remote_pull_dest_dir"))
    if explicit:
        return explicit
    local_dir = normalize_path_text((cfg or {}).get("cd2_local_pull_dir") or (cfg or {}).get("watch_dir") or DEFAULT_CONFIG["watch_dir"])
    return cd2_local_path_to_remote(local_dir, cfg)


def cd2_remote_source_roots(cfg: Dict) -> list[str]:
    return [cd2_remote_path_for_refresh(root, cfg) for root in parse_cd2_remote_source_dirs((cfg or {}).get("cd2_remote_source_dirs"))]


def remote_path_under(path: str, root: str) -> bool:
    value = normalize_path_text(path).lower()
    base = normalize_path_text(root).lower()
    return bool(value and base and (value == base or value.startswith(base + "/")))


def cd2_already_exists_message(text: str) -> bool:
    lowered = str(text or "").lower()
    return "already_exists" in lowered or "already exists" in lowered or "已存在" in lowered


def cd2_remote_source_allowed(path: str, cfg: Dict) -> bool:
    aliases = cd2_path_aliases_from_cfg(cfg or {})
    path_variants = alias_variants_for_path(path, aliases)
    root_variants: list[str] = []
    for root in parse_cd2_remote_source_dirs((cfg or {}).get("cd2_remote_source_dirs")):
        root_variants.extend(alias_variants_for_path(root, aliases))
        refreshed = cd2_remote_path_for_refresh(root, cfg)
        if refreshed:
            root_variants.extend(alias_variants_for_path(refreshed, aliases))
    return any(remote_path_under(candidate, root) for candidate in path_variants for root in root_variants)


def cd2_result_success(result) -> tuple[bool, str, list[str]]:
    def field(name: str, default=None):
        if isinstance(result, dict):
            return result.get(name, default)
        return getattr(result, name, default)

    success = field("success", True)
    error = str(field("errorMessage", "") or "")
    paths = list(field("resultFilePaths", []) or [])
    if success is False:
        return False, error or "CD2 复制任务创建失败", paths
    return True, error, paths


def record_cd2_refresh_result(path: str, ok: bool, message: str, reason: str = "") -> None:
    result = {
        "path": path,
        "ok": bool(ok),
        "message": message,
        "reason": reason,
        "checked_at": now(),
    }
    with lock:
        cd2_state = state.setdefault("cd2", {})
        refresh_state = cd2_state.setdefault("refresh", {})
        refresh_state["last_result"] = result
        recent = list(refresh_state.get("recent_results") or [])
        recent.append(result)
        refresh_state["recent_results"] = recent[-20:]
        save_state_locked()


def refresh_cd2_directory(cfg: Dict, path: str, reason: str = "") -> Dict:
    remote_path = cd2_remote_path_for_refresh(path, cfg)
    if not cfg.get("cd2_refresh_enabled"):
        result = {"ok": False, "path": remote_path, "message": "CD2 目录刷新未启用", "reason": reason}
        record_cd2_refresh_result(remote_path, False, result["message"], reason)
        return result
    if not remote_path:
        result = {"ok": False, "path": remote_path, "message": "CD2 刷新路径为空", "reason": reason}
        record_cd2_refresh_result(remote_path, False, result["message"], reason)
        return result
    client = get_cd2_client(cfg)
    if client is None:
        message = cd2_client_cache.get("last_error") or "CD2 API 未连接"
        result = {"ok": False, "path": remote_path, "message": message, "reason": reason}
        record_cd2_refresh_result(remote_path, False, message, reason)
        return result
    if not hasattr(client, "get_sub_files"):
        message = "当前 clouddrive2-client 不支持目录刷新"
        result = {"ok": False, "path": remote_path, "message": message, "reason": reason}
        record_cd2_refresh_result(remote_path, False, message, reason)
        return result
    try:
        list(client.get_sub_files(remote_path, force_refresh=True))
    except TypeError:
        try:
            list(client.get_sub_files(remote_path, True))
        except Exception as exc:
            message = cd2_error_message(exc)
            record_cd2_refresh_result(remote_path, False, message, reason)
            return {"ok": False, "path": remote_path, "message": message, "reason": reason}
    except Exception as exc:
        message = cd2_error_message(exc)
        record_cd2_refresh_result(remote_path, False, message, reason)
        return {"ok": False, "path": remote_path, "message": message, "reason": reason}
    message = "CD2 目录刷新完成"
    record_cd2_refresh_result(remote_path, True, message, reason)
    return {"ok": True, "path": remote_path, "message": message, "reason": reason}


def cd2_file_name(file_obj) -> str:
    return str(getattr(file_obj, "name", "") or getattr(file_obj, "fileName", "") or "")


def cd2_file_path(file_obj, parent_path: str = "") -> str:
    path = str(getattr(file_obj, "fullPathName", "") or getattr(file_obj, "path", "") or "")
    if path:
        return normalize_path_text(path)
    name = cd2_file_name(file_obj)
    return normalize_path_text(f"{normalize_path_text(parent_path)}/{name}") if name else normalize_path_text(parent_path)


def cd2_file_is_dir(file_obj) -> bool:
    if hasattr(file_obj, "isDirectory"):
        return bool(getattr(file_obj, "isDirectory"))
    file_type = str(getattr(file_obj, "fileType", "") or "").lower()
    return file_type in {"dir", "directory", "folder"}


def cd2_file_size(file_obj) -> int:
    try:
        return int(getattr(file_obj, "size", 0) or 0)
    except (TypeError, ValueError):
        return 0


def cd2_file_mtime(file_obj) -> str:
    value = getattr(file_obj, "writeTime", None) or getattr(file_obj, "modifyTime", None) or ""
    if hasattr(value, "ToJsonString"):
        try:
            return str(value.ToJsonString() or "")
        except Exception:
            pass
    return str(value or "")


def cd2_time_sort_value(value) -> float:
    if hasattr(value, "seconds"):
        try:
            return float(value.seconds) + float(getattr(value, "nanos", 0) or 0) / 1_000_000_000
        except (TypeError, ValueError):
            pass
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def cd2_remote_root_disc_type(path: str) -> str:
    name = (normalize_path_text(path).rsplit("/", 1)[-1] or "").casefold()
    if re.search(r"(?:^|[^a-z0-9])bdmv(?:$|[^a-z0-9])", name):
        return "BDMV"
    if re.search(r"(?:^|[^a-z0-9])video[^a-z0-9]*ts(?:$|[^a-z0-9])", name):
        return "VIDEO_TS"
    return ""


def list_cd2_sub_files(client, path: str, force_refresh: bool = False):
    try:
        return list(client.get_sub_files(path, force_refresh=force_refresh))
    except TypeError:
        return list(client.get_sub_files(path, force_refresh))


def cd2_directory_parent(path: str) -> Optional[str]:
    normalized = normalize_path_text(path) or "/"
    if normalized == "/":
        return None
    parent = normalized.rsplit("/", 1)[0] or "/"
    return parent


def cd2_disc_type_for_remote_path(client, path: str) -> str:
    sub_files = list_cd2_sub_files(client, path, force_refresh=True)
    names = {cd2_file_name(item).lower() for item in sub_files if cd2_file_is_dir(item)}
    if "bdmv" in names:
        return "BDMV"
    if "video_ts" in names:
        return "VIDEO_TS"
    return ""


def scan_cd2_remote_candidates(cfg: Dict, force_refresh: bool = False, client=None) -> Dict:
    pull_configured = bool(cfg.get("cd2_manual_pull_enabled") or cfg.get("cd2_auto_pull_enabled"))
    pull_guard_enabled = cd2_pull_disabled()
    pull_enabled = pull_configured and not pull_guard_enabled
    roots = parse_cd2_remote_source_dirs(cfg.get("cd2_remote_source_dirs"))
    remote_roots = cd2_remote_source_roots(cfg)
    scan_depth = int_config(cfg, "cd2_remote_scan_depth", DEFAULT_CONFIG["cd2_remote_scan_depth"], minimum=1)
    payload = {
        "ok": True,
        "checked_at": now(),
        "roots": roots,
        "remote_roots": remote_roots,
        "scan_depth": scan_depth,
        "manual_pull_enabled": bool(cfg.get("cd2_manual_pull_enabled")),
        "auto_pull_enabled": bool(cfg.get("cd2_auto_pull_enabled")),
        "pull_configured": pull_configured,
        "pull_guard_enabled": pull_guard_enabled,
        "pull_enabled": pull_enabled,
        "pull_dest_dir": cd2_pull_dest_dir_from_cfg(cfg),
        "candidates": [],
        "errors": [],
        "partial": False,
    }
    if not roots:
        payload["message"] = "未配置网盘监控目录"
        return payload
    if not cfg.get("cd2_api_enabled"):
        payload["ok"] = False
        payload["message"] = "CD2 API 未启用"
        return payload
    client = client or get_cd2_client(cfg)
    if client is None:
        payload["ok"] = False
        payload["message"] = cd2_client_cache.get("last_error") or "CD2 API 未连接"
        return payload
    if not hasattr(client, "get_sub_files"):
        payload["ok"] = False
        payload["message"] = "当前 clouddrive2-client 不支持远程目录扫描"
        return payload
    for root, remote_root in zip(roots, remote_roots):
        root_disc_type = cd2_remote_root_disc_type(remote_root)
        stack = [(remote_root, 0, bool(force_refresh))]
        while stack:
            current_root, current_depth, current_force_refresh = stack.pop()
            try:
                children = list_cd2_sub_files(client, current_root, force_refresh=current_force_refresh)
            except Exception as exc:
                payload["errors"].append({"root": current_root, "message": cd2_error_message(exc)})
                continue
            children.sort(
                key=lambda item: (
                    cd2_time_sort_value(getattr(item, "writeTime", None) or getattr(item, "modifyTime", None)),
                    cd2_file_name(item).casefold(),
                ),
                reverse=True,
            )
            for child in children:
                if not cd2_file_is_dir(child) or bool(getattr(child, "isSearchResult", False)):
                    continue
                child_path = cd2_file_path(child, current_root)
                child_depth = current_depth + 1
                disc_type = root_disc_type if current_depth == 0 else ""
                if not disc_type:
                    try:
                        sub_files = list_cd2_sub_files(client, child_path, force_refresh=False)
                    except Exception as exc:
                        payload["errors"].append({"root": child_path, "message": cd2_error_message(exc)})
                        continue
                    names = {cd2_file_name(item).lower() for item in sub_files if cd2_file_is_dir(item)}
                    disc_type = "BDMV" if "bdmv" in names else ("VIDEO_TS" if "video_ts" in names else "")
                if disc_type:
                    pull_status = cd2_remote_candidate_status(cfg, child_path)
                    candidate = {
                        "name": cd2_file_name(child) or child_path.rsplit("/", 1)[-1],
                        "path": child_path,
                        "root": remote_root,
                        "depth": child_depth,
                        "disc_type": disc_type,
                        "size": cd2_file_size(child),
                        "modified": cd2_file_mtime(child),
                        **pull_status,
                    }
                    candidate["skip_reason"] = cd2_remote_candidate_skip_reason(candidate, cfg)
                    payload["candidates"].append(candidate)
                    continue
                if child_depth < scan_depth:
                    stack.append((child_path, child_depth, False))
    payload["candidates"].sort(
        key=lambda item: (
            cd2_time_sort_value(item.get("modified")),
            str(item.get("name") or item.get("path") or "").casefold(),
        ),
        reverse=True,
    )
    payload["candidate_count"] = len(payload["candidates"])
    payload["summary"] = cd2_remote_candidate_summary(payload["candidates"])
    payload["message"] = f"发现 {payload['candidate_count']} 个远程原盘候选"
    if payload["errors"]:
        payload["ok"] = False
        payload["partial"] = bool(payload["candidates"])
        payload["message"] = (
            f"CD2 远程目录扫描不完整：发现 {payload['candidate_count']} 个候选，"
            f"另有 {len(payload['errors'])} 个目录读取失败"
            if payload["partial"]
            else "CD2 远程目录扫描失败"
        )
    return payload


def record_cd2_pull_result(
    source_path: str,
    dest_dir: str,
    ok: bool,
    message: str,
    disc_type: str = "",
    result_paths=None,
    mode: str = "manual",
) -> None:
    result = {
        "source_path": source_path,
        "dest_dir": dest_dir,
        "disc_type": disc_type,
        "ok": bool(ok),
        "message": message,
        "result_paths": list(result_paths or []),
        "mode": mode,
        "created_at": now(),
    }
    with lock:
        cd2_state = state.setdefault("cd2", {})
        pull_state = cd2_state.setdefault("pull", {})
        pull_state["last_result"] = result
        recent = list(pull_state.get("recent_results") or [])
        recent.append(result)
        pull_state["recent_results"] = recent[-20:]
        save_state_locked()


def cd2_local_pull_path_for_source(cfg: Dict, source_path: str) -> Path:
    local_pull_dir = Path(cfg.get("cd2_local_pull_dir") or cfg.get("watch_dir") or DEFAULT_CONFIG["watch_dir"]).expanduser()
    return (local_pull_dir / safe_filename(source_path.rsplit("/", 1)[-1])).resolve()


def cd2_auto_pull_claim_key(source_path: str, dest_dir: str) -> str:
    source = normalize_path_text(source_path).casefold()
    destination = normalize_path_text(dest_dir).casefold()
    return f"{source}\n{destination}" if source and destination else ""


def cd2_auto_pull_claims_locked() -> Dict:
    cd2_state = state.setdefault("cd2", {})
    claims = cd2_state.get("auto_pull_claims")
    if not isinstance(claims, dict):
        claims = {}
        cd2_state["auto_pull_claims"] = claims
    return claims


def cd2_auto_pull_claim_status(cfg: Dict, source_path: str, dest_dir: str) -> Optional[Dict]:
    source_path = normalize_path_text(source_path)
    dest_dir = normalize_path_text(dest_dir)
    claim_key = cd2_auto_pull_claim_key(source_path, dest_dir)
    if not claim_key:
        return None
    stale_creating = False
    with lock:
        claims = cd2_auto_pull_claims_locked()
        claim = claims.get(claim_key)
        items = list((state.get("items") or {}).items())
        matching_items = [
            item for _item_key, item in items
            if normalize_path_text(item.get("cd2_pull_source")) == source_path
            and (
                not normalize_path_text(item.get("cd2_pull_dest"))
                or normalize_path_text(item.get("cd2_pull_dest")) == dest_dir
            )
            and item.get("status") != "removed"
        ]
        completed_item = next(
            (
                item for item in matching_items
                if item.get("cd2_pull_finished_at")
                or item.get("status") in {"done", "transfer_done", "waiting_cd2_upload"}
            ),
            None,
        )
        if claim:
            claim = dict(claim)
            claim_status = claim.get("status") or "submitted"
            if claim_status == "creating" and seconds_between(claim.get("updated_at") or claim.get("created_at")) > CD2_AUTO_PULL_CREATING_TIMEOUT_SECONDS:
                claims.pop(claim_key, None)
                save_state_locked()
                stale_creating = True
            elif completed_item and claim_status != "completed":
                claim.update({"status": "completed", "updated_at": now()})
                claims[claim_key] = claim
                save_state_locked()
            else:
                return claim
        if stale_creating:
            claim = None
        if not claim:
            for item in matching_items:
                item_status = item.get("status") or ""
                if item.get("cd2_pull_finished_at") or item_status in {"done", "transfer_done", "waiting_cd2_upload"}:
                    legacy_status = "completed"
                elif item_status in {"failed", "verify_failed", "transfer_failed", "removed"}:
                    continue
                else:
                    legacy_status = "submitted"
                claim = {
                    "source_path": source_path,
                    "dest_dir": dest_dir,
                    "status": legacy_status,
                    "created_at": item.get("cd2_pull_created_at") or now(),
                    "updated_at": now(),
                    "legacy": True,
                }
                claims[claim_key] = claim
                save_state_locked()
                return dict(claim)
        recent = list((state.get("cd2", {}).get("pull", {}) or {}).get("recent_results") or [])
        for result in reversed(recent):
            if not result.get("ok"):
                continue
            if normalize_path_text(result.get("source_path")) != source_path:
                continue
            if normalize_path_text(result.get("dest_dir")) != dest_dir:
                continue
            claim = {
                "source_path": source_path,
                "dest_dir": dest_dir,
                "status": "submitted",
                "created_at": result.get("created_at") or now(),
                "updated_at": now(),
                "legacy": True,
            }
            claims[claim_key] = claim
            save_state_locked()
            return dict(claim)
    return None


def claim_cd2_auto_pull(cfg: Dict, source_path: str, dest_dir: str) -> tuple[bool, Optional[Dict]]:
    source_path = normalize_path_text(source_path)
    dest_dir = normalize_path_text(dest_dir)
    claim_key = cd2_auto_pull_claim_key(source_path, dest_dir)
    if not claim_key:
        return False, {"status": "invalid"}
    with lock:
        existing = cd2_auto_pull_claim_status(cfg, source_path, dest_dir)
        if existing:
            return False, existing
        claim = {
            "source_path": source_path,
            "dest_dir": dest_dir,
            "status": "creating",
            "created_at": now(),
            "updated_at": now(),
        }
        cd2_auto_pull_claims_locked()[claim_key] = claim
        save_state_locked()
        return True, dict(claim)


def update_cd2_auto_pull_claim(source_path: str, dest_dir: str, status: str, **updates) -> None:
    claim_key = cd2_auto_pull_claim_key(source_path, dest_dir)
    if not claim_key:
        return
    with lock:
        claims = cd2_auto_pull_claims_locked()
        claim = claims.get(claim_key)
        if not claim:
            return
        claim = dict(claim)
        claim.update(updates)
        claim["status"] = status
        claim["updated_at"] = now()
        claims[claim_key] = claim
        save_state_locked()


def release_cd2_auto_pull_claim(source_path: str, dest_dir: str) -> None:
    claim_key = cd2_auto_pull_claim_key(source_path, dest_dir)
    if not claim_key:
        return
    with lock:
        claims = cd2_auto_pull_claims_locked()
        if claim_key in claims:
            claims.pop(claim_key, None)
            save_state_locked()


def cd2_remote_candidate_status(cfg: Dict, source_path: str) -> Dict:
    source_path = normalize_path_text(source_path)
    dest_dir = cd2_pull_dest_dir_from_cfg(cfg)
    local_source = cd2_local_pull_path_for_source(cfg, source_path)
    result = {
        "local_path": str(local_source),
        "pull_state": "new",
        "pull_status_label": "新候选",
    }
    claim = cd2_auto_pull_claim_status(cfg, source_path, dest_dir)
    if claim:
        claim_status = claim.get("status") or "submitted"
        result.update({
            "pull_mode": "auto",
            "pull_created_at": claim.get("created_at") or "",
            "pull_status_label": "已完成" if claim_status == "completed" else "处理中",
        })
        result["pull_state"] = "done" if claim_status == "completed" else "active"
        return result
    local_key = str(local_source)
    source_match = None
    with lock:
        items = dict(state.get("items", {}))
    for key, item in items.items():
        if item.get("status") == "removed":
            continue
        if key == local_key or normalize_path_text(item.get("cd2_pull_source")) == source_path:
            source_match = dict(item)
            break
    if source_match:
        item_status = source_match.get("status") or ""
        result.update({
            "pull_item_status": item_status,
            "pull_mode": source_match.get("cd2_pull_mode") or "",
            "pull_created_at": source_match.get("cd2_pull_created_at") or "",
            "pull_error": source_match.get("error") or source_match.get("last_error") or "",
            "pull_status_label": status_label(item_status),
        })
        if item_status in {"done", "transfer_done"}:
            result["pull_state"] = "done"
        elif item_status in {"failed", "verify_failed", "transfer_failed"}:
            result["pull_state"] = "failed"
        elif item_status in TERMINAL_STATUSES:
            result["pull_state"] = "finished"
        else:
            result["pull_state"] = "active"
        return result
    failure_cooldown = int_config(cfg, "cd2_auto_pull_failure_cooldown_seconds", CD2_AUTO_PULL_FAILURE_COOLDOWN_SECONDS, minimum=0)
    if cd2_pull_recent_failure(source_path, failure_cooldown):
        result["pull_state"] = "recent_failure"
        result["pull_status_label"] = "最近失败"
    return result


def cd2_pull_recent_failure(source_path: str, cooldown_seconds: int = CD2_AUTO_PULL_FAILURE_COOLDOWN_SECONDS) -> bool:
    if cooldown_seconds <= 0:
        return False
    source_path = normalize_path_text(source_path)
    with lock:
        recent = list(state.get("cd2", {}).get("pull", {}).get("recent_results") or [])
    for result in reversed(recent):
        if normalize_path_text(result.get("source_path")) != source_path:
            continue
        if result.get("ok"):
            return False
        if seconds_between(result.get("created_at")) < cooldown_seconds:
            return True
        return False
    return False


def cd2_auto_pull_keywords(value) -> list[str]:
    parts = re.split(r"[\n,;]+", str(value or ""))
    seen = set()
    result = []
    for part in parts:
        keyword = part.strip().lower()
        if keyword and keyword not in seen:
            seen.add(keyword)
            result.append(keyword)
    return result


def cd2_auto_pull_filter_reason(candidate: Dict, cfg: Dict) -> str:
    text = " ".join([
        str((candidate or {}).get("name") or ""),
        str((candidate or {}).get("path") or ""),
    ]).lower()
    min_size_gb = int_config(cfg, "cd2_auto_pull_min_size_gb", DEFAULT_CONFIG["cd2_auto_pull_min_size_gb"], minimum=0)
    size = int((candidate or {}).get("size") or 0)
    if min_size_gb > 0 and size > 0 and size < min_size_gb * 1024 * 1024 * 1024:
        return f"低于最小体积: {min_size_gb} GB"
    for keyword in cd2_auto_pull_keywords((cfg or {}).get("cd2_auto_pull_exclude_keywords")):
        if keyword in text:
            return f"命中排除关键词: {keyword}"
    include_keywords = cd2_auto_pull_keywords((cfg or {}).get("cd2_auto_pull_include_keywords"))
    if include_keywords and not any(keyword in text for keyword in include_keywords):
        return "未命中包含关键词"
    return ""


def cd2_remote_candidate_skip_reason(candidate: Dict, cfg: Dict) -> str:
    pull_state = (candidate or {}).get("pull_state") or "new"
    if pull_state == "new":
        return cd2_auto_pull_filter_reason(candidate, cfg)
    if pull_state == "active":
        return "已有拉取或封装任务"
    if pull_state == "done":
        return "已处理"
    if pull_state == "recent_failure":
        return "最近失败冷却中"
    if pull_state in {"failed", "finished"}:
        return (candidate or {}).get("pull_status_label") or "已结束"
    return ""


def cd2_remote_candidate_summary(candidates: list[Dict]) -> Dict:
    summary = {"total": len(candidates), "pullable": 0, "skipped": 0, "by_state": {}, "by_skip_reason": {}}
    for candidate in candidates:
        state_name = candidate.get("pull_state") or "unknown"
        summary["by_state"][state_name] = summary["by_state"].get(state_name, 0) + 1
        reason = candidate.get("skip_reason") or ""
        if reason:
            summary["skipped"] += 1
            summary["by_skip_reason"][reason] = summary["by_skip_reason"].get(reason, 0) + 1
        else:
            summary["pullable"] += 1
    return summary


def cd2_auto_pull_active_count() -> int:
    with lock:
        claims_store = cd2_auto_pull_claims_locked()
        stale_keys = [
            key for key, claim in claims_store.items()
            if (claim or {}).get("status") == "creating"
            and seconds_between((claim or {}).get("updated_at") or (claim or {}).get("created_at")) > CD2_AUTO_PULL_CREATING_TIMEOUT_SECONDS
        ]
        for key in stale_keys:
            claims_store.pop(key, None)
        if stale_keys:
            save_state_locked()
        claims = dict(claims_store)
        items = list((state.get("items") or {}).values())
    active_claim_keys = {
        key for key, claim in claims.items()
        if (claim or {}).get("status") in {"creating", "submitted"}
    }
    count = len(active_claim_keys)
    for item in items:
        status = item.get("status") or ""
        if item.get("cd2_pull_mode") != "auto":
            continue
        if not item.get("cd2_pull_source") or item.get("cd2_pull_finished_at"):
            continue
        if status in TERMINAL_STATUSES:
            continue
        claim_key = cd2_auto_pull_claim_key(
            item.get("cd2_pull_source"),
            item.get("cd2_pull_dest"),
        )
        if claim_key in active_claim_keys:
            continue
        count += 1
    return count


def cd2_pull_already_tracked(
    source_path: str,
    local_source: Path,
    include_finished_source: bool = False,
    dest_dir: str = "",
) -> bool:
    source_path = normalize_path_text(source_path)
    dest_dir = normalize_path_text(dest_dir)
    local_key = str(local_source)
    with lock:
        items = dict(state.get("items", {}))
    for key, item in items.items():
        status = item.get("status")
        if status == "removed":
            continue
        if key == local_key and status not in TERMINAL_STATUSES:
            return True
        item_source = normalize_path_text(item.get("cd2_pull_source"))
        item_dest = normalize_path_text(item.get("cd2_pull_dest"))
        same_remote_pull = item_source == source_path and (
            not dest_dir or not item_dest or item_dest == dest_dir
        )
        if include_finished_source and same_remote_pull:
            return True
        if same_remote_pull and status not in TERMINAL_STATUSES:
            return True
    return False


def clear_cd2_pull_record(cfg: Dict, source_path: str) -> tuple[Dict, int]:
    source_path = normalize_path_text(source_path)
    if not source_path:
        return {"ok": False, "message": "缺少远程源路径"}, 400
    if not cd2_remote_source_allowed(source_path, cfg):
        return {"ok": False, "message": "远程源路径不在已配置的 CD2 源目录内"}, 403

    local_source = cd2_local_pull_path_for_source(cfg, source_path)
    local_key = str(local_source)
    removed_items = []
    removed_claim_count = 0
    removed_recent_count = 0
    removed_last_result = False

    with lock:
        active = state.get("active") or {}
        if active and (active.get("source") == local_key or normalize_path_text(active.get("cd2_pull_source")) == source_path):
            return {"ok": False, "message": "候选仍在运行中，不能清除记录"}, 409

        claim = cd2_auto_pull_claim_status(cfg, source_path, cd2_pull_dest_dir_from_cfg(cfg))
        if claim and claim.get("status") in {"creating", "submitted"}:
            return {"ok": False, "message": "候选仍在拉取中，不能清除记录"}, 409

        items = state.setdefault("items", {})
        for key, item in list(items.items()):
            if key != local_key and normalize_path_text(item.get("cd2_pull_source")) != source_path:
                continue
            status = item.get("status") or ""
            if status not in TERMINAL_STATUSES and status != "removed":
                return {"ok": False, "message": "候选仍在拉取或封装流程中，不能清除记录"}, 409
            removed_items.append(key)
            del items[key]

        cd2_state = state.setdefault("cd2", {})
        claims = cd2_auto_pull_claims_locked()
        for key, claim in list(claims.items()):
            if normalize_path_text((claim or {}).get("source_path")) != source_path:
                continue
            claims.pop(key, None)
            removed_claim_count += 1
        pull_state = cd2_state.setdefault("pull", {})
        recent = list(pull_state.get("recent_results") or [])
        if recent:
            kept = []
            for result in recent:
                if normalize_path_text(result.get("source_path")) == source_path:
                    removed_recent_count += 1
                    continue
                kept.append(result)
            pull_state["recent_results"] = kept
        last_result = pull_state.get("last_result") or {}
        if normalize_path_text(last_result.get("source_path")) == source_path:
            pull_state.pop("last_result", None)
            removed_last_result = True

        changed = bool(removed_items or removed_claim_count or removed_recent_count or removed_last_result)
        if changed:
            save_state_locked()

    message = "已清除候选记录，可重新拉取" if changed else "没有可清除的候选记录"
    return {
        "ok": True,
        "message": message,
        "source_path": source_path,
        "local_path": local_key,
        "removed_items": removed_items,
        "removed_item_count": len(removed_items),
        "removed_claim_count": removed_claim_count,
        "removed_recent_count": removed_recent_count,
    }, 200


def cd2_remote_task_matches_pull(source_path: str, dest_dir: str, cd2_status: Optional[Dict]) -> bool:
    if not cd2_status or not cd2_status.get("connected"):
        return False
    source_path = normalize_path_text(source_path)
    dest_dir = normalize_path_text(dest_dir)
    name = source_path.rsplit("/", 1)[-1]
    for task in cd2_status.get("copy_tasks", []) or []:
        if task.get("done"):
            continue
        task_source = normalize_path_text(task.get("source") or "")
        task_target = normalize_path_text(task.get("target") or "")
        if task_source and task_source == source_path:
            return True
        if name and dest_dir and task_target == normalize_path_text(dest_dir + "/" + name):
            return True
        if name and task_target.endswith("/" + name):
            return True
    for task in cd2_status.get("downloads", []) or []:
        if task.get("done"):
            continue
        task_path = normalize_path_text(task.get("path") or task.get("key") or "")
        if task_path and (task_path == source_path or (name and task_path.endswith("/" + name))):
            return True
    return False


def create_cd2_pull_task(cfg: Dict, source_path: str, mode: str = "manual", cd2_status: Optional[Dict] = None) -> tuple[Dict, int]:
    source_path = normalize_path_text(source_path)
    if not source_path:
        return {"ok": False, "message": "缺少远程源路径"}, 400
    if cd2_pull_disabled():
        return {"ok": False, "message": "本地测试已禁用真实 CD2 拉取"}, 400
    if not cd2_remote_source_allowed(source_path, cfg):
        return {"ok": False, "message": "远程源路径不在已配置的 CD2 源目录内"}, 403
    dest_dir = cd2_pull_dest_dir_from_cfg(cfg)
    if not dest_dir:
        return {"ok": False, "message": "请先配置下载目录"}, 400
    if remote_path_under(dest_dir, source_path):
        return {"ok": False, "message": "CD2 拉取目标不能位于源目录内部"}, 400

    local_source = cd2_local_pull_path_for_source(cfg, source_path)
    include_finished = mode == "auto"
    if cd2_pull_already_tracked(
        source_path,
        local_source,
        include_finished_source=include_finished,
        dest_dir=dest_dir,
    ):
        return {"ok": False, "message": "该远程候选已经在拉取或封装流程中"}, 409
    if mode == "auto":
        existing_claim = cd2_auto_pull_claim_status(cfg, source_path, dest_dir)
        if existing_claim:
            return {"ok": False, "message": "该远程候选已有自动拉取认领记录"}, 409
    failure_cooldown = int_config(cfg, "cd2_auto_pull_failure_cooldown_seconds", CD2_AUTO_PULL_FAILURE_COOLDOWN_SECONDS, minimum=0)
    if mode == "auto" and cd2_pull_recent_failure(source_path, failure_cooldown):
        return {"ok": False, "message": "该远程候选最近自动拉取失败，暂时跳过"}, 409
    if mode == "auto" and cd2_remote_task_matches_pull(source_path, dest_dir, cd2_status):
        return {"ok": False, "message": "CD2 队列里已有对应拉取任务"}, 409

    client = get_cd2_client(cfg)
    if client is None:
        return {"ok": False, "message": cd2_client_cache.get("last_error") or "CD2 API 未连接"}, 400
    if not hasattr(client, "get_sub_files"):
        return {"ok": False, "message": "当前 clouddrive2-client 不支持候选确认"}, 400
    if not hasattr(client, "copy_file"):
        return {"ok": False, "message": "当前 clouddrive2-client 不支持创建复制任务"}, 400
    try:
        disc_type = cd2_disc_type_for_remote_path(client, source_path)
    except Exception as exc:
        message = cd2_error_message(exc)
        record_cd2_pull_result(source_path, dest_dir, False, message, mode=mode)
        return {"ok": False, "message": message}, 400
    if not disc_type:
        message = "远程路径不是 BDMV / VIDEO_TS 原盘候选"
        record_cd2_pull_result(source_path, dest_dir, False, message, mode=mode)
        return {"ok": False, "message": message}, 400

    claim_created = False
    if mode == "auto":
        claim_created, existing_claim = claim_cd2_auto_pull(cfg, source_path, dest_dir)
        if not claim_created:
            return {"ok": False, "message": "该远程候选已有自动拉取认领记录"}, 409
    try:
        result = client.copy_file([source_path], dest_dir)
        ok, message, result_paths = cd2_result_success(result)
    except Exception as exc:
        ok, message, result_paths = False, cd2_error_message(exc), []
    record_cd2_pull_result(source_path, dest_dir, ok, message or "CD2 拉取任务已创建", disc_type, result_paths, mode)
    if not ok:
        if claim_created:
            release_cd2_auto_pull_claim(source_path, dest_dir)
        return {"ok": False, "message": message}, 400

    created_at = now()
    with lock:
        item = state.setdefault("items", {}).setdefault(str(local_source), {"first_seen": created_at})
        item.update({
            "status": "waiting_cd2_pull",
            "pack_iso": True,
            "last_size": 0,
            "last_changed": created_at,
            "partial_files": True,
            "error": "等待 CD2 拉取完成",
            "cd2_pull_source": source_path,
            "cd2_pull_dest": dest_dir,
            "cd2_pull_disc_type": disc_type,
            "cd2_pull_created_at": created_at,
            "cd2_pull_mode": mode,
            "cd2_pull_result_paths": result_paths,
        })
        item.pop("done_at", None)
        item.pop("target", None)
        item.pop("cd2_pull_finished_at", None)
        save_state_locked()
    if claim_created:
        update_cd2_auto_pull_claim(
            source_path,
            dest_dir,
            "submitted",
            local_path=str(local_source),
            result_paths=result_paths,
        )
    message = "CD2 自动拉取任务已创建" if mode == "auto" else "CD2 拉取任务已创建"
    return {
        "ok": True,
        "message": message,
        "source_path": source_path,
        "dest_dir": dest_dir,
        "local_path": str(local_source),
        "disc_type": disc_type,
        "mode": mode,
        "result_paths": result_paths,
    }, 200


def maybe_auto_pull_cd2_candidate(cfg: Dict, cd2_status: Optional[Dict]) -> Optional[Dict]:
    if not cfg.get("cd2_auto_pull_enabled"):
        return None
    if not cfg.get("cd2_api_enabled"):
        return None
    if not parse_cd2_remote_source_dirs(cfg.get("cd2_remote_source_dirs")):
        return None
    if not cd2_pull_dest_dir_from_cfg(cfg):
        with lock:
            cd2_state = state.setdefault("cd2", {})
            auto_state = cd2_state.setdefault("auto_pull", {})
            auto_state["last_result"] = {
                "ok": False,
                "message": "未配置下载目录",
                "checked_at": now(),
            }
            save_state_locked()
        return None

    max_active_tasks = int_config(cfg, "cd2_auto_pull_max_active_tasks", DEFAULT_CONFIG["cd2_auto_pull_max_active_tasks"], minimum=1)
    active_pull_count = cd2_auto_pull_active_count()
    if active_pull_count >= max_active_tasks:
        result = {
            "ok": True,
            "checked_at": now(),
            "candidate_count": 0,
            "message": f"已有 {active_pull_count} 个自动拉取任务进行中，达到上限 {max_active_tasks}",
            "created": False,
            "created_count": 0,
            "active_pull_count": active_pull_count,
            "max_active_tasks": max_active_tasks,
            "skipped": [],
        }
        with lock:
            cd2_state = state.setdefault("cd2", {})
            cd2_state.setdefault("auto_pull", {})["last_result"] = result
            save_state_locked()
        return result

    payload = controlled_cd2_remote_candidates(cfg, force_refresh=False)
    result = {
        "ok": bool(payload.get("ok")),
        "checked_at": now(),
        "candidate_count": len(payload.get("candidates") or []),
        "message": payload.get("message") or "",
        "created": False,
        "created_count": 0,
        "created_tasks": [],
        "max_tasks_per_scan": int_config(cfg, "cd2_auto_pull_max_tasks_per_scan", DEFAULT_CONFIG["cd2_auto_pull_max_tasks_per_scan"], minimum=1),
        "active_pull_count": active_pull_count,
        "max_active_tasks": max_active_tasks,
        "skipped": [],
    }
    if not payload.get("ok"):
        with lock:
            cd2_state = state.setdefault("cd2", {})
            cd2_state.setdefault("auto_pull", {})["last_result"] = result
            save_state_locked()
        return result

    for candidate in payload.get("candidates") or []:
        if result["created_count"] >= result["max_tasks_per_scan"]:
            break
        if result["active_pull_count"] + result["created_count"] >= result["max_active_tasks"]:
            break
        source_path = normalize_path_text(candidate.get("path"))
        if not source_path:
            continue
        filter_reason = cd2_auto_pull_filter_reason(candidate, cfg)
        if filter_reason:
            result["skipped"].append({
                "source_path": source_path,
                "status_code": 0,
                "message": filter_reason,
            })
            continue
        created, status_code = create_cd2_pull_task(cfg, source_path, mode="auto", cd2_status=cd2_status)
        if created.get("ok"):
            if result["created_count"] == 0:
                result.update(created)
            result["created"] = True
            result["created_count"] += 1
            result["created_tasks"].append({
                "source_path": created.get("source_path") or source_path,
                "dest_dir": created.get("dest_dir") or "",
                "local_path": created.get("local_path") or "",
                "disc_type": created.get("disc_type") or "",
                "status_code": status_code,
            })
            result["status_code"] = status_code
            log(f"CD2 自动拉取已创建: {source_path} -> {created.get('dest_dir')}")
            continue
        result["skipped"].append({
            "source_path": source_path,
            "status_code": status_code,
            "message": created.get("message") or "",
        })

    if result["created"]:
        result["message"] = f"本轮已创建 {result['created_count']} 个 CD2 自动拉取任务"
    elif result["skipped"]:
        result["message"] = result["skipped"][0].get("message") or result["message"]
    with lock:
        cd2_state = state.setdefault("cd2", {})
        auto_state = cd2_state.setdefault("auto_pull", {})
        auto_state["last_result"] = result
        save_state_locked()
    return result


def cd2_recorded_pull_pending(item: Dict, cd2_status: Optional[Dict], finish_missing: bool = True) -> Optional[Dict]:
    source_path = normalize_path_text((item or {}).get("cd2_pull_source"))
    dest_dir = normalize_path_text((item or {}).get("cd2_pull_dest"))
    if not source_path:
        return None
    if item.get("cd2_pull_finished_at"):
        if item.get("cd2_pull_mode") == "auto":
            update_cd2_auto_pull_claim(source_path, dest_dir, "completed")
        return None
    if not cd2_status or not cd2_status.get("connected"):
        return {
            "kind": "copy",
            "source": source_path,
            "target": dest_dir,
            "human": "等待 CD2 拉取状态刷新",
            "done": False,
        }
    for task in cd2_status.get("copy_tasks", []) or []:
        if task.get("done"):
            continue
        task_source = normalize_path_text(task.get("source") or "")
        task_target = normalize_path_text(task.get("target") or "")
        if (
            (task_source and task_source == source_path)
            or (dest_dir and (task_target == dest_dir or task_target.startswith(dest_dir + "/")))
            or (task_target and source_path.rsplit("/", 1)[-1] and task_target.endswith("/" + source_path.rsplit("/", 1)[-1]))
        ):
            item["cd2_pull_seen_task"] = True
            return task
    if not finish_missing:
        return None
    item["cd2_pull_finished_at"] = now()
    if item.get("cd2_pull_mode") == "auto":
        update_cd2_auto_pull_claim(source_path, dest_dir, "completed")
    return None


def update_cd2_confirm_state(item: Dict, candidate: Path, cfg: Dict, webhook_event: Dict, size: int, signature: Optional[Dict], partial: bool) -> bool:
    delay_seconds = int_config(cfg, "cd2_confirm_delay_seconds", 30, minimum=0)
    required_checks = int_config(cfg, "cd2_confirm_stable_checks", 1, minimum=1)
    event_id = webhook_event.get("fingerprint") or ""
    if item.get("cd2_confirm_event_id") == event_id and item.get("cd2_confirm_finished_at"):
        return True
    status = item.get("status")
    if status != "waiting_cd2_confirm" or item.get("cd2_confirm_event_id") != event_id:
        started_at = now()
        item.update({
            "status": "waiting_cd2_confirm",
            "error": f"等待 CD2 确认 {delay_seconds} 秒",
            "cd2_confirm_event_id": event_id,
            "cd2_confirm_event_path": webhook_event.get("path") or "",
            "cd2_confirm_started_at": started_at,
            "cd2_confirm_checks": 0,
            "last_size": max(0, int(size or 0)),
            "tree_signature": signature,
            "partial_files": partial,
        })
    else:
        started_at = item.get("cd2_confirm_started_at") or now()
    elapsed = seconds_between(started_at)
    if elapsed < delay_seconds:
        item["error"] = f"等待 CD2 确认 {elapsed}s / {delay_seconds}s"
        item["last_size"] = max(0, int(size or 0))
        item["tree_signature"] = signature
        item["partial_files"] = partial
        return False
    checks = int(item.get("cd2_confirm_checks") or 0) + 1
    item["cd2_confirm_checks"] = checks
    if checks < required_checks:
        item["error"] = f"等待 CD2 确认 {checks} / {required_checks}"
        item["last_size"] = max(0, int(size or 0))
        item["tree_signature"] = signature
        item["partial_files"] = partial
        return False
    item["cd2_confirm_finished_at"] = now()
    item.pop("error", None)
    return True


def normalize_upload_path(path: str) -> str:
    return normalize_path_text(str(Path(str(path or "")).expanduser()))


def is_strict_iso_path(path) -> bool:
    normalized = normalize_upload_path(str(path or ""))
    name = normalized.rsplit("/", 1)[-1]
    return bool(name) and Path(name).suffix.lower() == ".iso"


def upload_lookup_keys(path: str, cfg: Optional[Dict] = None):
    cfg = cfg or {}
    aliases = cd2_path_aliases_from_cfg(cfg)
    base_paths = alias_variants_for_path(path, aliases)
    normalized = normalize_upload_path(path)
    if normalized not in base_paths:
        base_paths.insert(0, normalized)
    keys = []
    for base_path in base_paths:
        if base_path:
            keys.append(base_path)
    for root_name in ("cd2_mount_root", "cd2_target_dir"):
        root_value = cfg.get(root_name)
        if not root_value:
            continue
        try:
            root = Path(str(root_value)).expanduser().resolve()
            target = Path(str(path)).expanduser().resolve()
            relative = target.relative_to(root)
        except Exception:
            continue
        parts = relative.parts
        for index in range(len(parts)):
            suffix = "/".join(parts[index:])
            if suffix:
                keys.append(suffix)
                keys.append("/" + suffix)
    seen = set()
    result = []
    for key in keys:
        key = normalize_upload_path(key)
        lowered = key.lower()
        if lowered and lowered not in seen:
            seen.add(lowered)
            result.append(key)
    return result


def cd2_upload_match_mode_from_cfg(cfg: Optional[Dict] = None) -> str:
    mode = str((cfg or {}).get("cd2_upload_match_mode") or DEFAULT_CONFIG["cd2_upload_match_mode"]).strip()
    if mode not in CD2_UPLOAD_MATCH_MODES:
        return DEFAULT_CONFIG["cd2_upload_match_mode"]
    return mode


def find_upload_for_path(upload_map: Dict, path: str, cfg: Optional[Dict] = None):
    if not upload_map or not is_strict_iso_path(path):
        return None
    direct = {
        normalize_upload_path(key): value
        for key, value in upload_map.items()
        if is_strict_iso_path(((value or {}).get("path") or key) if isinstance(value, dict) else key)
    }
    for key in upload_lookup_keys(path, cfg):
        upload = direct.get(key)
        if upload:
            return upload
    if cd2_upload_match_mode_from_cfg(cfg) == "alias_only":
        return None
    candidates = [(normalize_upload_path(key).lower(), value) for key, value in direct.items()]
    for key in upload_lookup_keys(path, cfg):
        lowered = key.lower().strip("/")
        if not lowered:
            continue
        for candidate, upload in candidates:
            candidate = candidate.strip("/")
            if candidate == lowered or candidate.endswith("/" + lowered) or lowered.endswith("/" + candidate):
                return upload
    return None


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
        return "CD2 权限不足：请检查 API Token 是否具备读取传输任务权限"
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
        client = CloudDriveClient(addr, options=CD2_GRPC_CHANNEL_OPTIONS)
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
    for name in ("status", "statusEnum", "state", "taskStatus"):
        status = getattr(task, name, None)
        if status not in (None, ""):
            return str(status)
    return "unknown"


def is_copy_task_done(info: Dict) -> bool:
    status = str(info.get("status") or "").strip().lower()
    if status in COPY_TASK_DONE_STATUSES:
        return True
    failed_files = int(info.get("failed_files") or 0)
    total_files = int(info.get("total_files") or 0)
    done_files = int(info.get("done_files") or 0)
    total = int(info.get("total") or 0)
    current = int(info.get("current") or 0)
    percent = float(info.get("percent") or 0)
    files_done = total_files > 0 and done_files >= total_files
    bytes_done = total > 0 and current >= total
    return failed_files <= 0 and (files_done or bytes_done or percent >= 100.0)


def is_download_done(info: Dict) -> bool:
    status = str(info.get("status") or "").strip().lower()
    if status in COPY_TASK_DONE_STATUSES:
        return True
    total = int(info.get("total") or 0)
    current = int(info.get("current") or 0)
    return total > 0 and current >= total


def cd2_path_matches_candidate(path: str, candidate: Path, cfg: Optional[Dict] = None) -> bool:
    aliases = cd2_path_aliases_from_cfg(cfg or {})
    candidate_variants = alias_variants_for_path(str(candidate), aliases)
    value_variants = alias_variants_for_path(path, aliases)
    if not candidate_variants:
        candidate_variants = [str(candidate)]
    for candidate_value in candidate_variants:
        candidate_path = normalize_match_path(candidate_value)
        if not candidate_path:
            continue
        for value in value_variants:
            value_path = normalize_match_path(value)
            if value_path == candidate_path or value_path.startswith(candidate_path + "/"):
                return True
    name = candidate.name.strip().lower()
    if not name:
        return False
    return any(
        (value.endswith("/" + name) or ("/" + name + "/") in value)
        for value in (normalize_match_path(item) for item in value_variants)
    )


def cd2_pending_source_task(candidate: Path, cd2_status: Optional[Dict], cfg: Optional[Dict] = None) -> Optional[Dict]:
    if not cd2_status or not cd2_status.get("connected"):
        return None
    for task in cd2_status.get("copy_tasks", []) or []:
        if task.get("done"):
            continue
        fields = (task.get("source"), task.get("target"), task.get("key"))
        if any(cd2_path_matches_candidate(value, candidate, cfg) for value in fields):
            return task
    for task in cd2_status.get("downloads", []) or []:
        if task.get("done"):
            continue
        fields = (task.get("path"), task.get("key"))
        if any(cd2_path_matches_candidate(value, candidate, cfg) for value in fields):
            return task
    return None


def cd2_pending_reason(task: Dict) -> str:
    kind = task.get("kind")
    if kind == "copy":
        return task.get("human") or "CD2 复制任务未完成"
    if kind == "download":
        return task.get("human") or "CD2 下载任务未完成"
    return task.get("human") or "CD2 任务未完成"


def source_readiness_blocker(source: Path, source_size: int, cd2_status: Optional[Dict] = None, cfg: Optional[Dict] = None, ignore_cd2_tasks: bool = False):
    if source_size < 0:
        return "receiving", "源目录仍在变化，文件暂不可读", None
    if source_size <= 0:
        return "receiving", "源目录为空或仍在接收中", None
    if has_partial_files(source):
        return "waiting_partial", "检测到未完成临时文件", None
    structure_ready, structure_reason = disc_structure_ready(source)
    if not structure_ready:
        return "waiting_partial", structure_reason, None
    if not ignore_cd2_tasks:
        pending_task = cd2_pending_source_task(source, cd2_status, cfg)
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
            "status": extract_task_status(download),
            "current": current,
            "total": total,
            "percent": percent,
            "bytes_per_second": float_attr(download, "bytesPerSecond"),
            "detail": getattr(download, "detailDownloadInfo", "") or "",
            "error": getattr(download, "lastDownloadError", "") or "",
            "summary": f"{format_size(current)} / {format_size(total)}",
        }
        info["done"] = is_download_done(info)
        info["human"] = (
            f"CD2 下载{'完成' if info['done'] else '中'} {percent:.1f}% "
            f"({format_size(current)} / {format_size(total)})"
        ) if total > 0 else f"CD2 下载{'完成' if info['done'] else '中'}"
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


def cached_cd2_upload_status(cfg: Dict, poll_seconds: int):
    with cd2_lock:
        cached_status = cd2_client_cache.get("upload_status")
        cached_map = cd2_client_cache.get("upload_map") or {}
        cached_checked_at = cd2_client_cache.get("checked_at")
        if cached_status and cached_checked_at and seconds_between(cached_checked_at) < poll_seconds:
            status = dict(cached_status)
            status.update(cd2_cache_status_fields(cfg, status.get("checked_at"), cache_hit=True))
            return dict(cached_map), status
    return None


def base_cd2_upload_status(cfg: Dict) -> Dict:
    return {
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


def cd2_error_status(cfg: Dict, status: Dict, message: str):
    status["last_error"] = message
    status["human"] = message
    status.update(cd2_cache_status_fields(cfg, status.get("checked_at"), cache_hit=False))
    return {}, status


def cd2_disconnected_status(cfg: Dict, status: Dict, message: str):
    status["checked_at"] = cd2_client_cache.get("checked_at")
    status["auth_mode"] = cd2_client_cache.get("auth_mode")
    status["last_success_at"] = cd2_client_cache.get("last_success_at")
    return cd2_error_status(cfg, status, message)


def record_cd2_upload_queue_failure(message: str) -> None:
    with cd2_lock:
        cd2_client_cache["last_error"] = message
        cd2_client_cache["checked_at"] = now()
        cd2_client_cache["upload_map"] = {}
        cd2_client_cache["upload_status"] = None


def build_cd2_upload_info(upload) -> Dict:
    current = int(getattr(upload, "transferedBytes", 0) or 0)
    total = int(getattr(upload, "size", 0) or 0)
    percent = 100.0 if total <= 0 else min(100.0, max(0.0, current * 100 / total))
    return {
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


def attach_cd2_upload_entries(status: Dict, result) -> Dict:
    upload_map = {}
    for upload in getattr(result, "uploadFiles", []) or []:
        info = build_cd2_upload_info(upload)
        if not is_strict_iso_path(info["path"]):
            continue
        upload_map[normalize_upload_path(info["path"])] = info
        status["uploads"].append(info)
    return upload_map


def summarize_cd2_queue_status(status: Dict, queue_errors: list[str]) -> None:
    parts = []
    if status["upload_count"]:
        parts.append(f"{status['upload_count']} 项上传")
    if status["download_count"]:
        parts.append(f"{status['download_count']} 项下载")
    if status["copy_task_count"]:
        parts.append(f"{status['copy_task_count']} 项复制")
    status["human"] = " / ".join(parts) if parts else "未发现传输任务"
    if queue_errors:
        status["human"] = f"{status['human']}，部分队列读取失败"


def cache_cd2_upload_status(upload_map: Dict, status: Dict) -> None:
    with cd2_lock:
        cd2_client_cache["checked_at"] = status["checked_at"]
        cd2_client_cache["last_success_at"] = status["last_success_at"]
        cd2_client_cache["last_error"] = status["last_error"]
        cd2_client_cache["upload_map"] = dict(upload_map)
        cd2_client_cache["upload_status"] = dict(status)


def fetch_cd2_uploads(cfg: Dict):
    poll_seconds = max(1, int(cfg.get("cd2_queue_poll_seconds", 10) or 10))
    cached = cached_cd2_upload_status(cfg, poll_seconds)
    if cached:
        return cached
    status = base_cd2_upload_status(cfg)
    if not status["enabled"]:
        return cd2_error_status(cfg, status, "CD2 API 未启用")
    if not status["available"]:
        return cd2_error_status(cfg, status, "缺少 clouddrive2-client 依赖")
    auth_mode = cd2_auth_mode_from_cfg(cfg)
    if auth_mode == "password" and not str(cfg.get("cd2_api_username") or "").strip():
        return cd2_disconnected_status(cfg, status, "CD2 缺少用户名")
    if not str(cfg.get("cd2_api_password") or "").strip():
        secret_label = "API Token" if auth_mode == "api_token" else "密码"
        return cd2_disconnected_status(cfg, status, f"CD2 缺少{secret_label}")
    client = get_cd2_client(cfg)
    if client is None:
        return cd2_disconnected_status(
            cfg,
            status,
            cd2_client_cache.get("last_error") or "CD2 API 未连接",
        )
    queue_errors = []
    try:
        result = client.get_upload_file_list(get_all=True)
    except Exception as exc:
        message = cd2_error_message(exc)
        record_cd2_upload_queue_failure(message)
        return cd2_disconnected_status(cfg, status, message)
    try:
        downloads = fetch_cd2_downloads(client)
    except Exception as exc:
        downloads = []
        queue_errors.append(f"下载任务读取失败：{cd2_error_message(exc)}")
    try:
        copy_tasks = fetch_cd2_copy_tasks(client)
    except Exception as exc:
        copy_tasks = []
        queue_errors.append(f"复制任务读取失败：{cd2_error_message(exc)}")

    checked_at = now()
    status.update({
        "connected": True,
        "auth_mode": cd2_client_cache.get("auth_mode"),
        "checked_at": checked_at,
        "last_success_at": checked_at,
        "last_error": "；".join(queue_errors) if queue_errors else None,
        "upload_count": int(getattr(result, "totalCount", 0) or 0),
        "global_bytes_per_second": float(getattr(result, "globalBytesPerSecond", 0) or 0),
        "total_bytes": int(getattr(result, "totalBytes", 0) or 0),
        "finished_bytes": int(getattr(result, "finishedBytes", 0) or 0),
        "download_count": len(downloads),
        "copy_task_count": len(copy_tasks),
        "downloads": downloads,
        "copy_tasks": copy_tasks,
    })
    upload_map = attach_cd2_upload_entries(status, result)
    status["upload_count"] = len(status["uploads"])
    summarize_cd2_queue_status(status, queue_errors)
    status.update(cd2_cache_status_fields(cfg, status.get("checked_at"), cache_hit=False))
    cache_cd2_upload_status(upload_map, status)
    return upload_map, status


def attach_cd2_uploads(cfg: Dict, items: Dict, active: Optional[Dict] = None):
    upload_map, cd2_status = fetch_cd2_uploads(cfg)
    enriched = {}
    for key, item in (items or {}).items():
        copy = dict(item or {})
        upload = find_upload_for_path(upload_map, copy.get("target") or "", cfg)
        if upload:
            copy["cd2_upload"] = upload
        enriched[key] = copy
    if active:
        upload = find_upload_for_path(upload_map, active.get("target") or "", cfg)
        if upload:
            active = dict(active)
            active["cd2_upload"] = upload
    return enriched, active, cd2_status


def cd2_upload_done(upload: Optional[Dict]) -> bool:
    if not upload:
        return True
    status = str(upload.get("status") or "").strip().lower()
    if status in COPY_TASK_DONE_STATUSES:
        return True
    total = int(upload.get("total") or 0)
    current = int(upload.get("current") or upload.get("uploaded") or 0)
    percent = float(upload.get("percent") or 0)
    return (total > 0 and current >= total) or percent >= 100.0


def cd2_upload_queue_grace_seconds(cfg: Dict) -> int:
    poll_seconds = max(1, int(cfg.get("cd2_queue_poll_seconds", 10) or 10))
    return max(CD2_UPLOAD_QUEUE_GRACE_MIN_SECONDS, poll_seconds * CD2_UPLOAD_QUEUE_GRACE_POLLS)


def cd2_upload_observation_gap_seconds(cfg: Dict) -> int:
    poll_seconds = max(1, int(cfg.get("cd2_queue_poll_seconds", 10) or 10))
    return max(60, poll_seconds * 3)


def cd2_status_is_fresh_for_wait(cd2_status: Optional[Dict], wait_started_at: str) -> bool:
    checked_at = (cd2_status or {}).get("checked_at")
    checked_dt = parse_time(checked_at)
    started_dt = parse_time(wait_started_at)
    return bool(checked_dt and started_dt and checked_dt >= started_dt)


CD2_UPLOAD_MONITOR_FIELDS = (
    "cd2_upload_last_observed_at",
    "cd2_upload_progress_at",
    "cd2_upload_progress_current",
    "cd2_upload_progress_total",
    "cd2_upload_progress_percent",
    "cd2_upload_missing_since",
    "cd2_upload_monitor_paused",
)


def clear_cd2_upload_monitor(item: Dict) -> None:
    for field in CD2_UPLOAD_MONITOR_FIELDS:
        item.pop(field, None)


def initialize_cd2_upload_progress(item: Dict, upload: Dict, observed_at: str) -> None:
    item["cd2_upload_progress_at"] = observed_at
    item["cd2_upload_progress_current"] = int(upload.get("current") or upload.get("uploaded") or 0)
    item["cd2_upload_progress_total"] = int(upload.get("total") or 0)
    item["cd2_upload_progress_percent"] = float(upload.get("percent") or 0)
    item.pop("cd2_upload_missing_since", None)


def finish_cd2_upload_item(item: Dict, upload: Optional[Dict], finished_at: str) -> None:
    item["status"] = "transfer_done"
    item["finished_at"] = finished_at
    item["done_at"] = finished_at
    item["last_changed"] = finished_at
    item["cd2_upload"] = upload or item.get("cd2_upload") or {}
    item["cd2_upload_done_at"] = finished_at
    item.pop("error", None)
    clear_failure(item)
    clear_cd2_upload_monitor(item)
    log_message = "CD2 上传完成" if upload else "CD2 上传队列已清理"
    state.setdefault("events", []).append(f"[{finished_at}] {log_message}: {item.get('target') or '-'}")
    state["events"] = state["events"][-200:]


def fail_cd2_upload_item(item: Dict, code: str, message: str, failed_at: str) -> None:
    item["status"] = "transfer_failed"
    item["finished_at"] = failed_at
    item["last_changed"] = failed_at
    item.pop("done_at", None)
    set_failure(item, code, message)
    state.setdefault("events", []).append(f"[{failed_at}] {FAILURE_LABELS.get(code, code)}: {item.get('target') or '-'}")
    state["events"] = state["events"][-200:]


def check_waiting_cd2_uploads(cfg: Dict, upload_map: Dict, cd2_status: Optional[Dict]) -> None:
    if not cfg.get("cd2_wait_upload_complete"):
        return
    now_value = now()
    connected = bool((cd2_status or {}).get("connected"))
    wait_error = (cd2_status or {}).get("human") or (cd2_status or {}).get("last_error") or "等待 CD2 API 连接"
    grace_seconds = cd2_upload_queue_grace_seconds(cfg)
    observation_gap_seconds = cd2_upload_observation_gap_seconds(cfg)
    checked_at = str((cd2_status or {}).get("checked_at") or "")
    log_messages = []
    with lock:
        items = state.get("items", {})
        for key, item in items.items():
            if item.get("status") != "waiting_cd2_upload":
                continue
            wait_started_at = item.get("cd2_upload_wait_started_at") or item.get("transfer_finished_at") or now_value
            item["cd2_upload_wait_started_at"] = wait_started_at
            if not connected:
                item["error"] = f"监控 CloudDrive 上传队列：{wait_error}"
                item["cd2_upload_monitor_paused"] = True
                continue
            if not cd2_status_is_fresh_for_wait(cd2_status, wait_started_at):
                item["error"] = "监控 CloudDrive 上传队列：等待队列刷新"
                item["cd2_upload_monitor_paused"] = True
                continue
            last_observed_at = item.get("cd2_upload_last_observed_at")
            if checked_at and checked_at == last_observed_at:
                continue
            upload = find_upload_for_path(upload_map, item.get("target") or "", cfg)
            if upload and cd2_upload_done(upload):
                finish_cd2_upload_item(item, upload, now_value)
                log_messages.append(f"CD2 上传完成: {item.get('target') or key}")
                continue
            if not upload and item.get("cd2_upload_seen_at"):
                finish_cd2_upload_item(item, None, now_value)
                log_messages.append(f"CD2 上传队列已清理: {item.get('target') or key}")
                continue

            observation_interrupted = bool(item.pop("cd2_upload_monitor_paused", False))
            if last_observed_at and checked_at:
                observation_interrupted = observation_interrupted or seconds_between(last_observed_at, checked_at) > observation_gap_seconds
            item["cd2_upload_last_observed_at"] = checked_at or now_value

            if upload:
                item["cd2_upload"] = upload
                item["cd2_upload_seen_at"] = item.get("cd2_upload_seen_at") or now_value
                current = int(upload.get("current") or upload.get("uploaded") or 0)
                total = int(upload.get("total") or 0)
                percent = float(upload.get("percent") or 0)
                previous_current = item.get("cd2_upload_progress_current")
                previous_total = item.get("cd2_upload_progress_total")
                previous_percent = item.get("cd2_upload_progress_percent")
                if observation_interrupted or previous_current is None or not item.get("cd2_upload_progress_at"):
                    initialize_cd2_upload_progress(item, upload, checked_at or now_value)
                else:
                    advanced = current > int(previous_current or 0) or percent > float(previous_percent or 0)
                    restarted = current < int(previous_current or 0) or (int(previous_total or 0) > 0 and total != int(previous_total or 0))
                    if advanced or restarted:
                        initialize_cd2_upload_progress(item, upload, checked_at or now_value)
                    elif seconds_between(item.get("cd2_upload_progress_at"), checked_at or now_value) >= CD2_UPLOAD_STALL_SECONDS:
                        message = (
                            f"CD2 上传连续 {CD2_UPLOAD_STALL_SECONDS // 60} 分钟没有进展："
                            f"{upload.get('human') or upload.get('summary') or upload.get('status') or '上传中'}"
                        )
                        fail_cd2_upload_item(item, "cd2_upload_stalled", message, now_value)
                        log_messages.append(f"CD2 上传停滞: {item.get('target') or key}")
                        continue
                item["error"] = f"监控 CloudDrive 上传队列：{upload.get('human') or upload.get('summary') or upload.get('status') or '上传中'}"
                continue

            if observation_interrupted or not item.get("cd2_upload_missing_since"):
                item["cd2_upload_missing_since"] = checked_at or now_value
            missing_seconds = seconds_between(item.get("cd2_upload_missing_since"), checked_at or now_value)
            if missing_seconds >= CD2_UPLOAD_STALL_SECONDS:
                message = f"连续 {CD2_UPLOAD_STALL_SECONDS // 60} 分钟未在 CD2 上传队列找到对应任务"
                fail_cd2_upload_item(item, "cd2_upload_missing", message, now_value)
                log_messages.append(f"CD2 上传任务未出现: {item.get('target') or key}")
                continue
            if seconds_between(wait_started_at) < grace_seconds:
                item["error"] = f"监控 CloudDrive 上传队列：等待队列出现 {seconds_between(wait_started_at)}s / {grace_seconds}s"
            else:
                item["error"] = (
                    f"未在 CD2 上传队列找到对应任务，已观察 {missing_seconds}s / "
                    f"{CD2_UPLOAD_STALL_SECONDS}s"
                )
        save_state_locked()
    for message in log_messages:
        log(message)


def invalidate_cd2_upload_cache() -> None:
    with cd2_lock:
        cd2_client_cache["upload_map"] = {}
        cd2_client_cache["upload_status"] = None


def recheck_waiting_cd2_uploads(cfg: Dict) -> Dict:
    invalidate_cd2_upload_cache()
    upload_map, cd2_status = fetch_cd2_uploads(cfg)
    check_waiting_cd2_uploads(cfg, upload_map, cd2_status)
    return cd2_status


def state_item_key(source_text: str) -> Optional[str]:
    source_text = str(source_text or "").strip()
    if not source_text:
        return None
    with lock:
        items = state.get("items") or {}
        if source_text in items:
            return source_text
        normalized = normalize_path_text(source_text)
        for key in items:
            if normalize_path_text(key) == normalized:
                return key
        try:
            resolved = str(Path(source_text).expanduser().resolve())
        except Exception:
            resolved = ""
        if resolved:
            for key in items:
                try:
                    if str(Path(key).expanduser().resolve()) == resolved:
                        return key
                except Exception:
                    continue
    return None


CD2_UPLOAD_RECHECK_FAILURES = {"cd2_upload_stalled", "cd2_upload_missing"}
SOURCE_RECHECK_STATUSES = {
    "receiving",
    "waiting_partial",
    "waiting_stable",
    "waiting_cd2_pull",
    "waiting_cd2_confirm",
}


def reset_task_for_recheck(source_text: str, cfg: Dict):
    key = state_item_key(source_text)
    if not key:
        return {"ok": False, "message": "任务不存在或已被清理"}, 404, ""
    with lock:
        item = state.get("items", {}).get(key)
        if not item:
            return {"ok": False, "message": "任务不存在或已被清理"}, 404, ""
        status = item.get("status")
        failure_code = item.get("failure_code")
        if status in SOURCE_RECHECK_STATUSES:
            item["status"] = "waiting_cd2_pull" if status == "waiting_cd2_pull" else "watching"
            item["last_changed"] = now()
            item["error"] = "已请求重新检测"
            item.pop("failure_code", None)
            item.pop("failure_label", None)
            item.pop("failure_suggestion", None)
            save_state_locked()
            return {"ok": True, "message": "已重新加入源目录检测", "source": key}, 200, "source"
        if status != "waiting_cd2_upload" and failure_code not in CD2_UPLOAD_RECHECK_FAILURES:
            return {"ok": False, "message": "当前任务没有可重新检测的 CD2 上传状态"}, 409, ""
        item["status"] = "waiting_cd2_upload"
        item["cd2_upload_wait_started_at"] = now()
        item["last_changed"] = item["cd2_upload_wait_started_at"]
        item["error"] = "已请求重新读取 CD2 上传队列"
        item.pop("finished_at", None)
        item.pop("done_at", None)
        item.pop("cd2_upload", None)
        item.pop("cd2_upload_seen_at", None)
        item.pop("cd2_upload_done_at", None)
        clear_failure(item)
        clear_cd2_upload_monitor(item)
        save_state_locked()
    return {"ok": True, "message": "已重新检测 CD2 上传队列", "source": key}, 200, "upload"


def confirm_cd2_upload_task(source_text: str, cfg: Dict):
    key = state_item_key(source_text)
    if not key:
        return {"ok": False, "message": "任务不存在或已被清理"}, 404
    with lock:
        item = state.get("items", {}).get(key)
        snapshot = dict(item or {})
    status = snapshot.get("status")
    failure_code = snapshot.get("failure_code")
    if status == "transfer_done":
        return {"ok": True, "message": "该任务已经标记为已上传", "source": key}, 200
    if status != "waiting_cd2_upload" and failure_code not in CD2_UPLOAD_RECHECK_FAILURES:
        return {"ok": False, "message": "当前任务不是待确认的 CD2 上传任务"}, 409

    try:
        source = Path(key).expanduser().resolve()
        watch_dir = Path(cfg["watch_dir"]).expanduser().resolve()
        target = Path(str(snapshot.get("target") or "")).expanduser().resolve()
        target_dir_text = str(cfg.get("cd2_target_dir") or "").strip()
        target_dir = Path(target_dir_text).expanduser().resolve() if target_dir_text else None
    except Exception as exc:
        return {"ok": False, "message": f"任务路径无效: {exc}"}, 400
    if source == watch_dir or not path_in_root(source, watch_dir):
        return {"ok": False, "message": "源路径不在允许的监控目录内"}, 403
    if target.suffix.lower() != ".iso" or target_dir is None or not path_in_root(target, target_dir):
        return {"ok": False, "message": "目标文件不在允许的 CD2 成品目录内"}, 403
    if not target.is_file() or target.stat().st_size <= 0:
        return {"ok": False, "message": "CD2 目标 ISO 不存在或为空文件"}, 409
    expected_size = snapshot.get("target_size")
    if expected_size in (None, ""):
        expected_size = (snapshot.get("cd2_upload") or {}).get("total")
    try:
        expected_size = int(expected_size or 0)
    except (TypeError, ValueError):
        expected_size = 0
    actual_size = target.stat().st_size
    if expected_size > 0 and actual_size != expected_size:
        return {"ok": False, "message": f"CD2 目标 ISO 大小不一致: {actual_size} != {expected_size}"}, 409
    try:
        valid = bool(validate_iso(target))
    except Exception as exc:
        log(f"人工确认 CD2 ISO 校验异常 {target}: {exc}")
        valid = False
    if not valid:
        return {"ok": False, "message": "CD2 目标 ISO 结构校验失败，不能确认已上传"}, 409

    with lock:
        current = state.get("items", {}).get(key)
        if not current:
            return {"ok": False, "message": "任务不存在或已被清理"}, 404
        if current.get("status") == "transfer_done":
            return {"ok": True, "message": "该任务已经标记为已上传", "source": key}, 200
        if current.get("target") != snapshot.get("target"):
            return {"ok": False, "message": "任务目标已变化，请重新检测后再确认"}, 409
        finished_at = now()
        finish_cd2_upload_item(current, None, finished_at)
        current["target_size"] = actual_size
        current["cd2_upload_manual_confirmed"] = True
        current["cd2_upload_manual_confirmed_at"] = finished_at
        save_state_locked()
    log(f"人工确认 CD2 上传完成: {target}")
    return {"ok": True, "message": "已确认 CD2 上传完成", "source": key, "target": str(target)}, 200


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
    return output_dir / f"{base}.iso"


RELEASE_VERSION_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])V([0-9]+)(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
RELEASE_VERSION_LIKE_RE = re.compile(
    r"(?<![A-Za-z0-9])V([0-9A-Za-z]+)(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
RELEASE_BARE_VERSION_RE = re.compile(
    r"(?<![A-Za-z0-9])V(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
RELEASE_SITE_RE = re.compile(r"@([^@/\\]+?)\s*$")


def release_name_stem(value: str) -> str:
    text = str(value or "").strip().rstrip("/\\")
    if not text:
        return ""
    text = re.split(r"[/\\]", text)[-1]
    return re.sub(r"\.iso$", "", text, flags=re.IGNORECASE)


def normalize_release_site(value: str) -> str:
    return re.sub(r"[\s/\\]+", "", str(value or "")).strip().casefold()


def parse_release_identity(value: str) -> Dict:
    """Parse the conservative identity used for automatic ISO replacement."""
    name = release_name_stem(value)
    title, year = local_media_tmdb_query(name)
    version_tokens = list(RELEASE_VERSION_LIKE_RE.finditer(name))
    valid_tokens = list(RELEASE_VERSION_TOKEN_RE.finditer(name))
    version = None
    version_status = "unversioned"
    if version_tokens and len(version_tokens) == 1 and len(valid_tokens) == 1:
        try:
            parsed_version = int(valid_tokens[0].group(1))
        except (TypeError, ValueError, OverflowError):
            version_status = "ambiguous"
        else:
            if parsed_version > 0:
                version = parsed_version
                version_status = "versioned"
            else:
                version_status = "ambiguous"
    elif version_tokens or RELEASE_BARE_VERSION_RE.search(name):
        version_status = "ambiguous"

    site_match = RELEASE_SITE_RE.search(name)
    site = site_match.group(1).strip() if site_match else ""
    site_key = normalize_release_site(site)
    title_key = media_identity_key(title, year)
    identity_key = f"{title_key}|{site_key}" if title_key and site_key else ""
    return {
        "name": name,
        "title": title,
        "year": year,
        "site": site,
        "site_key": site_key,
        "version": version,
        "version_status": version_status,
        "identity_key": identity_key,
    }


def replacement_search_roots(cfg: Dict, output_dir: Path) -> list[Path]:
    roots = [output_dir.expanduser()]
    if cfg.get("cd2_transfer_enabled"):
        target_dir = str(cfg.get("cd2_target_dir") or DEFAULT_CONFIG["cd2_target_dir"]).strip()
        if target_dir:
            roots.append(Path(target_dir).expanduser())
    result = []
    seen = set()
    for root in roots:
        try:
            key = str(root.resolve()).casefold()
        except OSError:
            key = str(root).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(root)
    return result


def find_replacement_iso_candidates(source: Path, target: Path, cfg: Dict) -> list[Path]:
    """Find lower, explicitly versioned ISO files from the same site and film."""
    incoming = parse_release_identity(source.name)
    if incoming.get("version_status") != "versioned" or not incoming.get("identity_key"):
        return []

    candidates = []
    seen = set()
    output_dir = Path(cfg["output_dir"]).expanduser().resolve()
    for root in replacement_search_roots(cfg, output_dir):
        try:
            entries = sorted(root.iterdir(), key=lambda path: path.name.casefold())
        except (FileNotFoundError, NotADirectoryError, OSError):
            continue
        for candidate in entries:
            if candidate.suffix.lower() != ".iso":
                continue
            try:
                if not candidate.is_file():
                    continue
            except OSError:
                continue
            try:
                candidate_key = str(candidate.resolve()).casefold()
                target_key = str(target.resolve()).casefold()
            except OSError:
                candidate_key = str(candidate).casefold()
                target_key = str(target).casefold()
            if candidate_key in seen or candidate_key == target_key:
                continue
            existing = parse_release_identity(candidate.name)
            if (
                existing.get("version_status") == "versioned"
                and existing.get("identity_key") == incoming.get("identity_key")
                and int(existing.get("version") or 0) < int(incoming.get("version") or 0)
            ):
                seen.add(candidate_key)
                candidates.append(candidate)
    return candidates


def cleanup_replaced_iso_candidates(source: Path, new_target: Path, candidates: list[Path]) -> None:
    if not candidates:
        return
    removed = []
    failed = []
    new_target_key = str(new_target.resolve()).casefold()
    for candidate in candidates:
        try:
            candidate_key = str(candidate.resolve()).casefold()
        except OSError:
            candidate_key = str(candidate).casefold()
        if candidate_key == new_target_key or not candidate.exists():
            continue
        try:
            candidate.unlink()
            removed.append(str(candidate))
        except Exception as exc:
            failed.append(f"{candidate} ({exc})")
    if removed:
        log(f"新版本ISO已完成，已清理旧版本: {'; '.join(removed)}")
    if failed:
        message = "；".join(failed)
        log(f"新版本ISO已完成，但旧版本清理失败: {message}")
    with lock:
        item = state.setdefault("items", {}).setdefault(str(source), {})
        if removed:
            item["replaced_iso_paths"] = removed
            item["replaced_iso_count"] = len(removed)
        if failed:
            set_warning(item, "replaced_iso_cleanup_failed", message)
        item["last_changed"] = now()
        save_state_locked()


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


def mark_active_status(status: str, target: Path, phase: Optional[str] = None) -> None:
    with lock:
        active = state.get("active")
        if not active:
            return
        active["status"] = status
        active["target"] = str(target)
        progress = dict(active.get("progress") or {})
        if phase:
            progress["phase"] = phase
            progress["percent"] = max(0.0, min(100.0, float(progress.get("percent") or 0)))
            progress["updated_at"] = now()
            active["progress"] = progress
        source = active.get("source")
        item = state.get("items", {}).get(source) if source else None
        if item and item.get("status") not in TERMINAL_STATUSES:
            item["status"] = status
            item["last_changed"] = now()
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
                update_active_progress("packing", target, {
                    "percent": min(percent, 99.9),
                    "current": current,
                    "total": source_size,
                    "stage_text": "正在生成 ISO 文件",
                })
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
    update_active_progress("packing", target, {
        "percent": 100.0 if proc.returncode == 0 else min(current * 100 / max(source_size, 1), 99.9),
        "current": current,
        "total": source_size,
        "stage_text": "ISO 生成完成，等待校验",
    })
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def validate_iso(target: Path) -> bool:
    if not target.exists() or target.stat().st_size <= 0:
        return False
    result = subprocess.run(["xorriso", "-indev", str(target), "-toc"], text=True, capture_output=True)
    return result.returncode == 0



def resolve_cd2_target_dir(cfg: Dict) -> Optional[Path]:
    mount_root = Path(str(cfg.get("cd2_mount_root") or DEFAULT_CONFIG["cd2_mount_root"])).expanduser()
    target_dir = Path(str(cfg.get("cd2_target_dir") or DEFAULT_CONFIG["cd2_target_dir"])).expanduser()
    if cfg.get("cd2_require_mount", True) and not mount_root.is_mount():
        log(f"CloudDrive2挂载目录未挂载，停止转移: {mount_root}")
        return None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log(f"创建CloudDrive2目标目录失败 {target_dir}: {exc}")
        return None
    return target_dir


def prepare_cd2_transfer_path(target: Path, target_dir: Path) -> Optional[Path]:
    final_path = target_dir / target.name
    if not is_strict_iso_path(final_path):
        log(f"拒绝向 CloudDrive2 挂载目录写入非 ISO 文件: {final_path}")
        return None
    if final_path.exists():
        log(f"上传目录已存在同名ISO，停止转移，等待手动处理: {final_path}")
        return None
    return final_path


def remove_failed_cd2_transfer_target(final_path: Path) -> None:
    try:
        if final_path.exists():
            final_path.unlink()
    except Exception as exc:
        log(f"清理 CloudDrive2 未完成目标失败 {final_path}: {exc}")


def copy_iso_to_mount(source: Path, final_path: Path, total: int) -> bool:
    copied = 0
    last_update = 0.0
    created = False
    try:
        with source.open("rb") as src, final_path.open("xb") as dst:
            created = True
            while True:
                chunk = src.read(16 * 1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                copied += len(chunk)
                current_time = time.time()
                if current_time - last_update >= 2:
                    percent = 100.0 if total <= 0 else copied * 100 / total
                    update_active_progress("transfer", final_path, {
                        "percent": min(percent, 99.9),
                        "current": copied,
                        "total": total,
                        "stage_text": "正在复制 ISO 到 CD2 挂载目录",
                    })
                    last_update = current_time
            dst.flush()
            os.fsync(dst.fileno())
    except Exception:
        if created:
            remove_failed_cd2_transfer_target(final_path)
        raise
    update_active_progress("transfer_verify", final_path, {
        "percent": 100.0,
        "current": copied,
        "total": total,
        "stage_text": "转存写入完成，正在校验目标 ISO",
    })
    try:
        final_size = final_path.stat().st_size
        if final_size != total:
            log(f"CloudDrive2转移大小校验失败: {final_size} != {total}")
            remove_failed_cd2_transfer_target(final_path)
            return False
        if not validate_iso(final_path):
            log(f"CloudDrive2目标 ISO 结构校验失败: {final_path}")
            remove_failed_cd2_transfer_target(final_path)
            return False
    except Exception:
        remove_failed_cd2_transfer_target(final_path)
        raise
    return True


def finalize_cd2_transfer(target: Path, final_path: Path, total: int) -> bool:
    if final_path.stat().st_size != total:
        log(f"CloudDrive2最终文件大小校验失败: {final_path.stat().st_size} != {total}")
        remove_failed_cd2_transfer_target(final_path)
        return False
    update_active_progress("transfer_verify", final_path, {
        "percent": 100.0,
        "current": total,
        "total": total,
        "verified": True,
        "stage_text": "目标文件大小校验通过，正在收尾",
    })
    target.unlink()
    log(f"CloudDrive2转移完成并校验通过，已删除输出目录临时ISO: {target}，目标文件保留: {final_path}")
    return True


def maybe_refresh_cd2_after_transfer(cfg: Dict, final_path: Path) -> None:
    if not (cfg.get("cd2_refresh_enabled") and cfg.get("cd2_refresh_after_transfer")):
        return
    mark_active_status("refreshing_cd2_dir", final_path, "refresh_cd2_dir")
    refresh = refresh_cd2_directory(cfg, str(final_path.parent), "transfer")
    if refresh.get("ok"):
        log(f"CD2 目标目录刷新完成: {refresh.get('path')}")
    else:
        log(f"CD2 目标目录刷新失败: {refresh.get('message')}")


def transfer_iso_to_mount(target: Path, cfg: Dict) -> Optional[Path]:
    if not cfg.get("cd2_transfer_enabled"):
        return target
    if not target.is_file() or target.is_symlink():
        log(f"待转移 ISO 不存在或不是普通文件: {target}")
        return None
    if not is_strict_iso_path(target):
        log(f"拒绝向 CloudDrive2 转存非 ISO 文件: {target}")
        return None
    try:
        source_valid = validate_iso(target)
    except Exception as exc:
        log(f"待转移 ISO 结构校验异常 {target}: {exc}")
        return None
    if not source_valid:
        log(f"拒绝向 CloudDrive2 转存结构校验失败的 ISO: {target}")
        return None
    target_dir = resolve_cd2_target_dir(cfg)
    if not target_dir:
        return None

    if path_in_root(target, target_dir):
        log(f"ISO 已在 CloudDrive2 目标目录，跳过重复转存: {target}")
        maybe_refresh_cd2_after_transfer(cfg, target)
        return target

    total = target.stat().st_size
    final_path = target_dir / target.name
    if final_path.exists() and cd2_transfer_target_is_complete(target, final_path):
        try:
            target.unlink()
            log(f"CloudDrive2 目标目录已有同名且校验通过的 ISO，删除本机重复文件: {target}")
        except Exception as exc:
            log(f"CloudDrive2 目标目录已有同名且校验通过的 ISO，本机重复文件删除失败: {target} ({exc})")
        maybe_refresh_cd2_after_transfer(cfg, final_path)
        return final_path

    final_path = prepare_cd2_transfer_path(target, target_dir)
    if not final_path:
        return None

    log(f"开始转移到CloudDrive2挂载目录: {target} -> {final_path}")
    try:
        if not copy_iso_to_mount(target, final_path, total):
            return None
        if not finalize_cd2_transfer(target, final_path, total):
            return None
        maybe_refresh_cd2_after_transfer(cfg, final_path)
        return final_path
    except Exception as exc:
        log(f"CloudDrive2转移失败: {exc}")
        return None


def remove_non_iso_task(source: Path) -> None:
    with lock:
        state.get("items", {}).pop(str(source), None)
        state["active"] = None
        save_state_locked()


def record_insufficient_space(source: Path) -> None:
    with lock:
        item = state["items"].setdefault(str(source), {})
        set_failure(item, "insufficient_space", "空间不足，暂停处理")
        item["last_changed"] = now()
        save_state_locked()


def classify_existing_output_iso(target: Path, source_size: int) -> tuple[str, str]:
    if not target.exists():
        return "missing", ""
    try:
        output_size = target.stat().st_size
    except OSError as exc:
        return "unknown", f"读取文件大小失败: {exc}"
    if output_size <= 0:
        return "incomplete", "文件大小为 0"
    if source_size > 0 and output_size < int(source_size * 0.95):
        return "incomplete", f"文件大小明显小于源目录: {output_size} < {source_size}"
    try:
        if validate_iso(target):
            return "complete", "ISO 校验通过"
    except Exception as exc:
        return "unknown", f"ISO 校验无法完成: {exc}"
    return "incomplete", "ISO 校验未通过"


def cd2_transfer_target_is_complete(source: Path, final_path: Path) -> bool:
    """确认 CD2 同名文件是完整转存的同一份 ISO。"""
    try:
        if not source.is_file() or not final_path.is_file():
            return False
        source_size = source.stat().st_size
        final_size = final_path.stat().st_size
    except OSError:
        return False
    if source_size <= 0 or source_size != final_size:
        return False
    try:
        return validate_iso(final_path)
    except Exception as exc:
        log(f"CD2 同名目标 ISO 校验失败 {final_path}: {exc}")
        return False


def cleanup_existing_output_iso(target: Path, source_size: int) -> Optional[str]:
    status, reason = classify_existing_output_iso(target, source_size)
    if status == "missing":
        return None
    if status != "incomplete":
        message = f"输出目录已存在同名 ISO，{reason}，等待手动处理: {target}"
        log(message)
        return message
    try:
        target.unlink()
    except Exception as exc:
        message = f"输出目录中断残留 ISO 删除失败，等待手动处理: {target} ({exc})"
        log(message)
        return message
    log(f"清理输出目录中断残留 ISO，准备重新封装: {target} ({reason})")
    return None


def record_output_conflict(source: Path, target: Path, message: Optional[str] = None) -> None:
    with lock:
        state["active"] = None
        item = state["items"].setdefault(str(source), {})
        failed_at = now()
        item.update({
            "status": "failed",
            "target": str(target),
            "pack_finished_at": failed_at,
            "finished_at": failed_at,
            "last_changed": failed_at,
        })
        set_failure(item, "output_exists", message or f"输出目录已存在同名 ISO，请手动处理后重新封装: {target}")
        save_state_locked()


def start_process_item_task(source: Path, target: Path, source_size: int, task_started_at: str) -> Optional[str]:
    with lock:
        active_task = state.get("active")
        if active_task is not None:
            active_source = active_task.get("source") or "unknown"
            if active_source == str(source):
                return f"跳过重复启动任务: {source}"
            return f"已有任务执行中，跳过 {source}: {active_source}"

        item = state["items"].setdefault(str(source), {})
        item.update({
            "task_started_at": task_started_at,
            "pack_started_at": task_started_at,
            "status": "running",
            "target": str(target),
        })
        item.pop("error", None)
        item.pop("reason", None)
        item.pop("last_error", None)
        clear_failure(item)
        clear_warning(item)
        item.pop("cd2_source_task", None)
        state["active"] = {
            "source": str(source),
            "target": str(target),
            "output_target": str(target),
            "started_at": task_started_at,
            "task_started_at": task_started_at,
            "pack_started_at": task_started_at,
            "status": "running",
            "progress": {
                "phase": "packing",
                "percent": 0,
                "current": 0,
                "total": source_size,
                "stage_text": "准备生成 ISO 文件",
                "updated_at": now(),
            },
        }
        save_state_locked()
    return None


def record_pack_failure(source: Path, error: str) -> None:
    with lock:
        state["active"] = None
        item = state["items"].setdefault(str(source), {})
        item["status"] = "failed"
        set_failure(item, "pack_failed", error)
        item["pack_finished_at"] = now()
        item["finished_at"] = now()
        item["last_changed"] = now()
        save_state_locked()


def record_verify_failure(source: Path) -> None:
    with lock:
        state["active"] = None
        item = state["items"].setdefault(str(source), {})
        item["status"] = "verify_failed"
        set_failure(item, "verify_failed", "xorriso 校验失败")
        item["pack_finished_at"] = now()
        item["finished_at"] = now()
        item["last_changed"] = now()
        save_state_locked()


def mark_transfer_started(source: Path, target: Path, task_started_at: str) -> str:
    transfer_started_at = now()
    with lock:
        item = state["items"].setdefault(str(source), {})
        item["status"] = "transferring"
        item["pack_finished_at"] = now()
        item["transfer_started_at"] = transfer_started_at
        state["active"] = {
            "source": str(source),
            "target": str(target),
            "output_target": str(target),
            "started_at": task_started_at,
            "task_started_at": task_started_at,
            "pack_started_at": task_started_at,
            "pack_finished_at": item["pack_finished_at"],
            "transfer_started_at": transfer_started_at,
            "status": "transferring",
            "progress": {
                "phase": "transfer",
                "percent": 0,
                "current": 0,
                "total": target.stat().st_size if target.exists() else 0,
                "stage_text": "封装完成，正在转存 ISO",
                "updated_at": now(),
            },
        }
        save_state_locked()
    return transfer_started_at


def record_transfer_failure(
    source: Path,
    target: Path,
    source_size: int,
    transfer_finished_at: str,
    code: str = "transfer_failed",
    message: str = "移动到 CD2 挂载目录失败",
) -> None:
    with lock:
        item = state["items"].setdefault(str(source), {})
        item.update({
            "status": "transfer_failed",
            "target": str(target),
            "done_at": transfer_finished_at,
            "finished_at": transfer_finished_at,
            "pack_finished_at": item.get("pack_finished_at") or transfer_finished_at,
            "transfer_finished_at": transfer_finished_at,
            "size": source_size,
        })
        set_failure(item, code, message)
        item["last_changed"] = now()
        state["active"] = None
        save_state_locked()


def delete_source_if_configured(source: Path, cfg: Dict) -> Optional[str]:
    if not cfg.get("delete_source_after_success"):
        return None
    try:
        if source.is_dir():
            shutil.rmtree(source)
        else:
            source.unlink()
        log(f"已删除源文件: {source}")
        return None
    except Exception as exc:
        log(f"删除源文件失败 {source}: {exc}")
        return str(exc)


def finish_process_item_success(
    source: Path,
    final_target: Path,
    source_size: int,
    cfg: Dict,
    transfer_started_at,
    transfer_finished_at,
    delete_source_error: Optional[str],
    cd2_upload_already_done: bool = False,
) -> None:
    with lock:
        item = state["items"].setdefault(str(source), {})
        if cfg.get("cd2_transfer_enabled"):
            status = "transfer_done"
            if cfg.get("cd2_wait_upload_complete") and not cd2_upload_already_done:
                status = "waiting_cd2_upload"
        else:
            status = "done"
        finished_at = now()
        update = {
            "status": status,
            "target": str(final_target),
            "target_size": final_target.stat().st_size if final_target.exists() else 0,
            "pack_finished_at": item.get("pack_finished_at") or finished_at,
            "transfer_started_at": transfer_started_at,
            "transfer_finished_at": transfer_finished_at,
            "size": source_size,
        }
        if status == "waiting_cd2_upload":
            update["cd2_upload_wait_started_at"] = finished_at
            item.pop("cd2_upload_seen_at", None)
            item.pop("cd2_upload_done_at", None)
            item.pop("cd2_upload_queue_missing_at", None)
            update["error"] = "监控 CloudDrive 上传队列"
            item.pop("done_at", None)
            item.pop("finished_at", None)
        else:
            update["done_at"] = finished_at
            update["finished_at"] = finished_at
            item.pop("error", None)
        item.update(update)
        clear_failure(item)
        if delete_source_error:
            set_warning(item, "delete_source_failed", delete_source_error)
        else:
            clear_warning(item)
        state["active"] = None
        save_state_locked()


def record_unexpected_process_error(source: Path, partial: Path, exc: Exception) -> None:
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
            set_failure(item, "unexpected_error", str(exc))
            item["pack_finished_at"] = item.get("pack_finished_at") or failed_at
            item["finished_at"] = failed_at
            item["last_changed"] = failed_at
        save_state_locked()


def process_item(source: Path, cfg: Dict, ignore_cd2_tasks: bool = False) -> None:
    output_dir = Path(cfg["output_dir"]).expanduser().resolve()
    source_size = size_of(source)
    upload_map, cd2_status = fetch_cd2_uploads(cfg)
    check_waiting_cd2_uploads(cfg, upload_map, cd2_status)
    wait_status, wait_reason, pending_task = source_readiness_blocker(source, source_size, cd2_status, cfg, ignore_cd2_tasks=ignore_cd2_tasks)
    if wait_status:
        mark_source_waiting(source, wait_status, wait_reason, source_size, pending_task)
        log(f"等待源目录完成 {source}: {wait_reason}")
        return

    pack_iso, pack_reason = should_pack_iso(source)
    if not pack_iso:
        log(f"跳过ISO封装 {source}: {pack_reason}")
        log(f"普通媒体内容不加入任务列表，保留源路径: {source}")
        remove_non_iso_task(source)
        return

    target = iso_path_for(source, output_dir)
    reuse_existing_iso = False
    if target.exists():
        existing_status, existing_reason = classify_existing_output_iso(target, source_size)
        if existing_status == "complete":
            reuse_existing_iso = True
            log(f"复用输出目录中已校验通过的 ISO，跳过重复封装: {target}")
        elif existing_status == "incomplete":
            if not enough_space(output_dir, source_size, float(cfg["min_free_space_gb"])):
                log(f"空间不足，暂停处理 {source}")
                record_insufficient_space(source)
                return
            output_conflict = cleanup_existing_output_iso(target, source_size)
            if output_conflict:
                record_output_conflict(source, target, output_conflict)
                return
        else:
            output_conflict = f"输出目录已存在同名 ISO，{existing_reason}，等待手动处理: {target}"
            log(output_conflict)
            record_output_conflict(source, target, output_conflict)
            return
    elif not enough_space(output_dir, source_size, float(cfg["min_free_space_gb"])):
        log(f"空间不足，暂停处理 {source}")
        record_insufficient_space(source)
        return

    replacement_candidates = find_replacement_iso_candidates(source, target, cfg)
    partial = target.with_suffix(target.suffix + ".partial")
    task_started_at = now()
    skip_message = start_process_item_task(source, target, source_size, task_started_at)
    if skip_message:
        log(skip_message)
        return
    if reuse_existing_iso:
        with lock:
            item = state["items"].setdefault(str(source), {})
            item["iso_reused"] = True
            item["iso_reused_at"] = now()
            save_state_locked()
        update_active_progress("verify", target, {
            "percent": 100.0,
            "current": target.stat().st_size if target.exists() else 0,
            "total": source_size,
            "stage_text": "已有 ISO 校验通过，继续准备转存或完成归档",
        })
    else:
        log(f"开始生成 ISO: {source} -> {target}")
    try:
        if not reuse_existing_iso:
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
                record_pack_failure(source, error)
                return

            update_active_progress("finalize", target, {
                "percent": 100.0,
                "current": target.stat().st_size if target.exists() else partial.stat().st_size if partial.exists() else source_size,
                "total": source_size,
                "stage_text": "ISO 写入完成，正在移动到最终输出文件",
            })
            partial.replace(target)
            update_active_progress("verify", target, {
                "percent": 100.0,
                "current": target.stat().st_size if target.exists() else source_size,
                "total": source_size,
                "stage_text": "ISO 已生成，正在进行结构校验",
            })
            if not validate_iso(target):
                log(f"ISO 验证失败，保留源文件: {target}")
                record_verify_failure(source)
                return

        update_active_progress("finalize", target, {
            "percent": 100.0,
            "current": target.stat().st_size if target.exists() else source_size,
            "total": source_size,
            "stage_text": "ISO 校验通过，正在准备转存或完成归档",
        })
        log(f"ISO 完成并验证通过: {target}")
        final_target = target
        cd2_upload_already_done = False
        if cfg.get("cd2_transfer_enabled"):
            target_dir = resolve_cd2_target_dir(cfg)
            existing_target = target_dir / target.name if target_dir else None
            if existing_target and existing_target.exists():
                if cd2_transfer_target_is_complete(target, existing_target):
                    final_target = existing_target
                    existing_upload = find_upload_for_path(upload_map, existing_target, cfg)
                    cd2_upload_already_done = bool(existing_upload and cd2_upload_done(existing_upload))
                    try:
                        if target.resolve() != existing_target.resolve():
                            target.unlink()
                            log(f"CD2 目标目录已有同名且校验通过的 ISO，删除本机重复文件: {target}")
                    except Exception as exc:
                        log(f"CD2 目标目录已有同名且校验通过的 ISO，本机重复文件删除失败: {target} ({exc})")
                    log(f"CD2 目标目录已有同名且校验通过的 ISO，跳过重复转存: {existing_target}")
                else:
                    transfer_finished_at = now()
                    message = f"上传目录已存在同名 ISO，但无法确认其完整性，请手动处理后重试: {existing_target}"
                    record_transfer_failure(source, target, source_size, transfer_finished_at, "target_exists", message)
                    log(message)
                    return
            if final_target == target:
                transfer_started_at = mark_transfer_started(source, target, task_started_at)
                moved_target = transfer_iso_to_mount(target, cfg)
                transfer_finished_at = now()
                if not moved_target:
                    record_transfer_failure(source, target, source_size, transfer_finished_at)
                    return
                final_target = moved_target
            else:
                transfer_started_at = now()
                transfer_finished_at = transfer_started_at
        else:
            transfer_started_at = None
            transfer_finished_at = None

        delete_source_error = delete_source_if_configured(source, cfg)
        finish_process_item_success(
            source,
            final_target,
            source_size,
            cfg,
            transfer_started_at,
            transfer_finished_at,
            delete_source_error,
            cd2_upload_already_done=cd2_upload_already_done,
        )
        cleanup_replaced_iso_candidates(source, final_target, replacement_candidates)
    except Exception as exc:
        record_unexpected_process_error(source, partial, exc)


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
        save_state_locked()

    upload_map, cd2_status = fetch_cd2_uploads(cfg)
    check_waiting_cd2_uploads(cfg, upload_map, cd2_status)
    maybe_auto_pull_cd2_candidate(cfg, cd2_status)
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
            active_statuses = {"running", "transferring", "refreshing_cd2_dir"}
            if item.get("status") in TERMINAL_STATUSES | active_statuses | {"waiting_cd2_upload"}:
                item.setdefault("last_size", size)
                item["partial_files"] = partial
                save_state_locked()
                continue
            webhook_event = latest_cd2_webhook_event_for_candidate(candidate, cfg)
            if webhook_event and not update_cd2_confirm_state(item, candidate, cfg, webhook_event, size, signature, partial):
                save_state_locked()
                continue
            last_size = item.get("last_size")
            last_signature = item.get("tree_signature")
            last_changed = item.get("last_changed", now())
            pending_task = cd2_recorded_pull_pending(item, cd2_status, finish_missing=False)
            if pending_task:
                wait_status = "waiting_cd2_pull"
                wait_reason = pending_task.get("human") or "等待 CD2 拉取完成"
            else:
                wait_status, wait_reason, pending_task = source_readiness_blocker(candidate, size, cd2_status, cfg)
            if not wait_status:
                pending_task = cd2_recorded_pull_pending(item, cd2_status)
                if pending_task:
                    wait_status = "waiting_cd2_pull"
                    wait_reason = pending_task.get("human") or "等待 CD2 拉取完成"
            if wait_status:
                item["last_size"] = max(0, size)
                item["tree_signature"] = signature
                item["last_changed"] = now()
                item["status"] = wait_status
                item["partial_files"] = partial or wait_status in {"waiting_partial", "waiting_cd2_pull"}
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
            if item.get("status") != "waiting_cd2_confirm":
                item.pop("cd2_confirm_event_id", None)
                item.pop("cd2_confirm_event_path", None)
                item.pop("cd2_confirm_started_at", None)
                item.pop("cd2_confirm_checks", None)
                item.pop("cd2_confirm_finished_at", None)
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
            if key not in current and item.get("status") not in {"done", "transfer_done", "waiting_cd2_upload", "waiting_cd2_pull", "failed", "verify_failed", "transfer_failed"}:
                item["status"] = "removed"
        save_state_locked()


def visible_iso_items(items: Dict) -> Dict:
    visible = {}
    for key, item in (items or {}).items():
        if item.get("pack_iso") is not True:
            continue
        safe_item = with_issue_guidance(item)
        status = safe_item.get("status")
        failure_code = safe_item.get("failure_code")
        safe_item["can_recheck"] = (
            status in SOURCE_RECHECK_STATUSES
            or failure_code in CD2_UPLOAD_RECHECK_FAILURES
        )
        safe_item["can_confirm_upload"] = (
            status == "waiting_cd2_upload"
            or failure_code in CD2_UPLOAD_RECHECK_FAILURES
        )
        if safe_item.get("failure_code") or safe_item.get("warning_code"):
            safe_item["issue_text"] = task_issue_text(safe_item)
        visible[key] = safe_item
    return visible


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


def ui_safe_config(cfg: Dict) -> Dict:
    safe_cfg = sanitize_config(cfg)
    safe_cfg["cd2_path_aliases_text"] = cd2_path_aliases_to_text(cfg)
    safe_cfg["cd2_remote_source_dirs_text"] = cd2_remote_source_dirs_to_text(cfg)
    safe_cfg["cd2_pull_guard_enabled"] = cd2_pull_disabled()
    safe_cfg["cd2_status_poll_guard_enabled"] = cd2_status_poll_disabled()
    return safe_cfg


def ui_safe_cd2_status(cd2_status: Optional[Dict]) -> Dict:
    """Return CD2 status fields that are useful for polling UI updates."""
    if not isinstance(cd2_status, dict):
        return {}
    hidden_keys = {"uploads", "downloads", "copy_tasks"}
    safe_status = {key: value for key, value in cd2_status.items() if key not in hidden_keys}
    for key in ("upload_count", "download_count", "copy_task_count"):
        safe_status.setdefault(key, 0)
    return safe_status


def ui_state_context(cfg: Optional[Dict] = None) -> Dict:
    cfg = cfg or load_config()
    with lock:
        visible_items = visible_iso_items(state.get("items", {}))
        events = list(reversed(state.get("events", [])[-120:]))
        snapshot = json.loads(json.dumps(state, ensure_ascii=False))
        snapshot["items"] = visible_items
    snapshot_items, snapshot_active, cd2_status = attach_cd2_uploads(cfg, snapshot.get("items", {}), snapshot.get("active"))
    snapshot["items"] = {
        key: apply_task_timings(item, snapshot_active if snapshot_active and snapshot_active.get("source") == key else None)
        for key, item in snapshot_items.items()
    }
    if snapshot_active:
        snapshot["active"] = apply_task_timings(dict(snapshot_active), snapshot_active)
    snapshot["cd2_status"] = cd2_status
    ordered_items = ordered_visible_items(snapshot["items"], snapshot.get("active"))
    return {
        "cfg": ui_safe_config(cfg),
        "config": ui_safe_config(cfg),
        "state": snapshot,
        "items": ordered_items[:5],
        "history_items": ordered_items,
        "events": events,
        "cd2_status": cd2_status,
        "status_label": status_label,
        "badge_class": badge_class,
        "format_size": format_size,
        "issue_text": task_issue_text,
        "item_name": item_display_name,
    }


def item_display_name(source: str) -> str:
    text = str(source or "").strip().rstrip("/\\")
    if not text:
        return "未命名任务"
    try:
        name = Path(text).name
    except Exception:
        name = ""
    return name or text.rsplit("/", 1)[-1] or text


def item_timestamp(item: Dict) -> Optional[datetime]:
    for key in ("finished_at", "done_at", "updated_at", "last_changed", "first_seen"):
        parsed = parse_time((item or {}).get(key))
        if parsed:
            return parsed
    return None


def dashboard_stats(history_items) -> Dict:
    current = datetime.now()
    today = current.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week = current - timedelta(days=7)
    month = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    done_statuses = {"done", "transfer_done"}
    failed_statuses = {"failed", "verify_failed", "transfer_failed"}
    stats = {
        "today_done": 0,
        "yesterday_count": 0,
        "yesterday_gb": 0,
        "week_done": 0,
        "this_week_count": 0,
        "this_week_gb": 0,
        "month_done": 0,
        "this_month_count": 0,
        "this_month_tb": 0,
        "failed": 0,
        "active": 0,
        "waiting": 0,
        "last_done_at": "",
    }
    active_statuses = {"running", "transferring", "refreshing_cd2_dir"}
    last_done_at = None
    for _, item in history_items or []:
        status = (item or {}).get("status")
        item_time = item_timestamp(item)
        size_bytes = (item or {}).get("last_size") or (item or {}).get("size") or 0
        if status in done_statuses and item_time:
            if item_time >= today:
                stats["today_done"] += 1
            if yesterday <= item_time < today:
                stats["yesterday_count"] += 1
                stats["yesterday_gb"] += size_bytes / (1024 ** 3)
            if item_time >= week:
                stats["week_done"] += 1
                stats["this_week_count"] += 1
                stats["this_week_gb"] += size_bytes / (1024 ** 3)
            if item_time >= month:
                stats["month_done"] += 1
                stats["this_month_count"] += 1
                stats["this_month_tb"] += size_bytes / (1024 ** 4)
            if last_done_at is None or item_time > last_done_at:
                last_done_at = item_time
        if status in failed_statuses:
            stats["failed"] += 1
        if status in active_statuses:
            stats["active"] += 1
        elif status and status not in TERMINAL_STATUSES and status != "removed":
            stats["waiting"] += 1
    # 格式化为整数
    stats["yesterday_gb"] = int(stats["yesterday_gb"])
    stats["this_week_gb"] = int(stats["this_week_gb"])
    stats["this_month_tb"] = round(stats["this_month_tb"], 1)
    if last_done_at:
        stats["last_done_at"] = last_done_at.strftime("%Y-%m-%d %H:%M")
    return stats


def infer_resolution_label(text: str) -> str:
    upper = str(text or "").upper()
    if any(token in upper for token in ("2160P", "UHD", "4K")):
        return "4K UHD"
    if "1080" in upper:
        return "1080P"
    if "720" in upper:
        return "720P"
    return "本地记录"


def local_media_poster_cache_key(source: str, name: str) -> str:
    raw = f"{source}|{name}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:20]


def local_media_tmdb_query(name: str) -> tuple[str, str]:
    text = str(name or "").strip()
    if not text:
        return "", ""
    try:
        text = Path(text).stem
    except Exception:
        pass
    text = re.sub(r"[\._]+", " ", text)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    year = year_match.group(1) if year_match else ""
    if year_match:
        text = text[:year_match.start()]
    text = re.sub(r"[\[\(].*?[\]\)]", " ", text)
    text = re.split(
        r"\b(2160p|1080p|720p|uhd|bluray|blu-ray|remux|x264|x265|hevc|hdr10|dovi|dolby|vision|atmos|truehd|dts)\b",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    text = re.sub(r"\s+", " ", text).strip(" -_.,")
    return text or str(name or "").strip(), year


def detect_media_resolution(name: str) -> str:
    upper = str(name or "").upper()
    if re.search(r"\b(2160P|UHD|4K)\b", upper):
        return "2160p"
    if re.search(r"\b1080P\b", upper):
        return "1080p"
    if re.search(r"\b720P\b", upper):
        return "720p"
    return ""


def detect_media_source(name: str) -> str:
    text = str(name or "")
    patterns = [
        ("UHD BluRay", r"\b(UHD[ ._-]*BluRay|Ultra[ ._-]*HD)\b"),
        ("BluRay Remux", r"\b(BluRay|Blu-Ray)[ ._-]*REMUX\b|\bREMUX\b"),
        ("BluRay", r"\b(BluRay|Blu-Ray|BDRip|BDMV)\b"),
        ("WEB-DL", r"\bWEB[ ._-]*DL\b"),
        ("WEBRip", r"\bWEB[ ._-]*Rip\b"),
        ("HDTV", r"\bHDTV\b"),
        ("DVD", r"\b(DVD|VIDEO_TS)\b"),
    ]
    for label, pattern in patterns:
        if re.search(pattern, text, flags=re.I):
            return label
    return ""


MEDIA_GROUP_STOPWORDS = {
    "2160p", "1080p", "720p", "uhd", "4k", "bluray", "blu-ray", "bdrip", "bdmv",
    "remux", "web", "webdl", "web-dl", "webrip", "hdtv", "dvd", "x264", "x265",
    "h264", "h265", "avc", "hevc", "hdr", "hdr10", "hdr10plus", "dovi", "dv",
    "dolby", "vision", "atmos", "truehd", "dts", "dtshd", "ma", "aac", "flac",
    "ac3", "eac3", "ddp", "dd", "mp4", "mkv", "iso",
}


def clean_media_group_token(token: str) -> str:
    value = str(token or "").strip().strip("[](){}").strip(" ._-")
    if not value or len(value) > 48:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{1,47}", value):
        return ""
    lowered = re.sub(r"[._-]+", "", value).lower()
    dashed = value.lower()
    if lowered in MEDIA_GROUP_STOPWORDS or dashed in MEDIA_GROUP_STOPWORDS:
        return ""
    if value.isdigit():
        return ""
    return value


def detect_media_group(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    patterns = [
        r"[\[\(]([A-Za-z0-9][A-Za-z0-9._@-]{1,47})[\]\)]\s*$",
        r"[-–—]\s*([A-Za-z0-9][A-Za-z0-9._@]{1,47})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        group = clean_media_group_token(match.group(1)) if match else ""
        if group:
            return group

    tail_match = re.search(r"([A-Za-z0-9][A-Za-z0-9._@-]{1,47})$", text)
    tail = clean_media_group_token(tail_match.group(1)) if tail_match else ""
    has_media_tokens = re.search(
        r"\b(19\d{2}|20\d{2}|2160p|1080p|720p|uhd|4k|bluray|blu-ray|remux|web[ ._-]*dl|webrip|x264|x265|hevc|avc|hdr10|dovi)\b",
        text,
        flags=re.I,
    )
    if tail and ("@" in tail or (has_media_tokens and re.search(r"[a-z][A-Z]|[A-Z][a-z]", tail))):
        return tail
    return ""


def media_identity_key(title: str, year: str) -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(title or "").lower(), flags=re.U)
    return f"{normalized}|{year or ''}" if normalized else ""


def media_parse_score(name: str, kind: str, resolution: str, source: str, group: str, year: str) -> int:
    score = 0
    if year:
        score += 2
    if resolution:
        score += 2
    if source:
        score += 2
    if group:
        score += 1
    if Path(str(name or "")).suffix.lower() in MEDIA_FILE_EXTENSIONS:
        score += 2
    return score


def media_candidate_from_path(path: Path, root_name: str, root: Path) -> Optional[Dict]:
    try:
        if not path.is_file() or path.suffix.lower() not in MEDIA_FILE_EXTENSIONS:
            return None
        stat = path.stat()
    except OSError:
        return None
    display_path = path
    raw_name = display_path.stem
    kind = "iso" if display_path.suffix.lower() == ".iso" else "video"
    title, year = local_media_tmdb_query(raw_name)
    resolution = detect_media_resolution(raw_name)
    source = detect_media_source(raw_name)
    group = detect_media_group(raw_name)
    score = media_parse_score(raw_name, kind, resolution, source, group, year)
    key = media_identity_key(title, year)
    try:
        relative = str(display_path.relative_to(root))
    except ValueError:
        relative = display_path.name
    return {
        "name": raw_name,
        "title": title or raw_name,
        "year": year,
        "identity_key": key or hashlib.sha1(str(display_path).encode("utf-8", errors="ignore")).hexdigest()[:12],
        "resolution": resolution,
        "source": source,
        "group": group or "未知组",
        "kind": kind,
        "type": "file",
        "path": str(display_path),
        "relative_path": relative,
        "root": root_name,
        "size": stat.st_size,
        "size_human": format_size(stat.st_size),
        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "score": score,
    }


def media_candidate_matches_query(candidate: Dict, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(str(candidate.get(key) or "") for key in (
        "name", "title", "year", "resolution", "source", "group", "path", "relative_path"
    )).lower()
    return query.lower() in haystack


def build_media_compare_groups(candidates: list[Dict]) -> list[Dict]:
    grouped = {}
    for candidate in candidates:
        grouped.setdefault(candidate.get("identity_key") or candidate.get("name"), []).append(candidate)
    groups = []
    for key, items in grouped.items():
        items.sort(key=lambda item: item.get("mtime") or "", reverse=True)
        if len(items) < 2:
            continue
        groups_seen = sorted({str(item.get("group") or "未知组") for item in items})
        resolutions = sorted({str(item.get("resolution") or "未知") for item in items})
        sources = sorted({str(item.get("source") or "未知来源") for item in items})
        groups.append({
            "key": key,
            "title": items[0].get("title") or items[0].get("name"),
            "year": items[0].get("year") or "",
            "count": len(items),
            "group_count": len(groups_seen),
            "groups": groups_seen,
            "resolutions": resolutions,
            "sources": sources,
            "multi_group": len(items) > 1 and len(groups_seen) > 1,
            "items": items,
            "latest_mtime": items[0].get("mtime") or "",
        })
    groups.sort(key=lambda group: (
        not group.get("multi_group"),
        -int(group.get("count") or 0),
        str(group.get("title") or "").lower(),
    ))
    return groups


def scan_media_compare_payload() -> tuple[Dict, int]:
    cfg = load_config()
    roots = file_browser_roots_from_config(cfg)
    root_name = str(request.args.get("root") or "cd2").strip()
    root = roots.get(root_name)
    if not root:
        return {"ok": False, "message": "无效的根目录"}, 400
    if root_name == "cd2":
        default_path = str(Path(str(cfg.get("cd2_target_dir") or DEFAULT_CONFIG["cd2_target_dir"])).expanduser())
    else:
        default_path = str(root)
    raw_path = str(request.args.get("path") or default_path).strip() or default_path
    if raw_path == "/":
        raw_path = str(root)
    try:
        path = Path(raw_path).expanduser().resolve()
        root = root.resolve()
    except Exception as exc:
        return {"ok": False, "message": f"路径无效: {exc}"}, 400
    if not path.exists():
        return {"ok": False, "message": "目录不存在"}, 404
    if not path.is_dir():
        path = path.parent
    if not path_in_root(path, root):
        return {"ok": False, "message": "禁止访问根目录外路径"}, 403

    depth = clamp_int_arg("depth", 1, minimum=1, maximum=2)
    query = str(request.args.get("q") or "").strip()
    queue = [(path, 0)]
    candidates = []
    seen_paths = set()
    scanned_dirs = 0
    truncated = False

    while queue and len(candidates) < MEDIA_SCAN_MAX_ITEMS:
        current, level = queue.pop(0)
        scanned_dirs += 1
        try:
            children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (OSError, PermissionError):
            continue
        for child in children:
            if len(candidates) >= MEDIA_SCAN_MAX_ITEMS:
                truncated = True
                break
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir:
                if level + 1 < depth:
                    queue.append((child, level + 1))
                continue
            if str(child) not in seen_paths:
                candidate = media_candidate_from_path(child, root_name, root)
                if candidate and media_candidate_matches_query(candidate, query):
                    candidates.append(candidate)
                    seen_paths.add(candidate["path"])
        if truncated:
            break

    groups = build_media_compare_groups(candidates)
    compared_candidate_count = sum(int(group.get("count") or 0) for group in groups)
    summary = {
        "candidate_count": compared_candidate_count,
        "scanned_candidate_count": len(candidates),
        "group_count": len(groups),
        "multi_group_count": sum(1 for group in groups if group.get("multi_group")),
        "duplicate_like_count": sum(1 for group in groups if int(group.get("group_count") or 0) > 1),
        "scanned_dirs": scanned_dirs,
        "truncated": truncated,
    }
    return {
        "ok": True,
        "root": root_name,
        "root_path": str(root),
        "path": str(path),
        "mode": "finished_files",
        "depth": depth,
        "query": query,
        "summary": summary,
        "groups": groups,
    }, 200


def local_media_cached_poster(cache_key: str) -> Dict:
    with lock:
        return dict((state.get("local_media_posters") or {}).get(cache_key) or {})


def prune_local_media_poster_cache_locked(limit: int = LOCAL_MEDIA_POSTER_CACHE_LIMIT) -> None:
    cache = state.get("local_media_posters")
    if not isinstance(cache, dict) or len(cache) <= limit:
        return
    kept = sorted(
        cache.items(),
        key=lambda pair: str((pair[1] or {}).get("updated_at") or ""),
        reverse=True,
    )[:limit]
    state["local_media_posters"] = dict(kept)


def store_local_media_poster(cache_key: str, payload: Dict) -> None:
    with lock:
        cache = state.setdefault("local_media_posters", {})
        cache[cache_key] = payload
        prune_local_media_poster_cache_locked()
        save_state_locked()


def apply_local_media_poster(card: Dict, payload: Dict) -> Dict:
    if not payload:
        return card
    poster_url = str(payload.get("poster_url") or "")
    if poster_url:
        card["poster_path"] = poster_url
        card["poster_url"] = poster_url
    if payload.get("title_zh"):
        card["title"] = str(payload.get("title_zh") or card.get("title") or "")
    for key in ("tmdb_id", "tmdb_title", "tmdb_original_title", "poster_status", "year"):
        if payload.get(key):
            card[key] = payload.get(key)
    return card


def enrich_local_media_card_with_tmdb(card: Dict, cfg: Optional[Dict]) -> Dict:
    tmdb_cfg = tmdb_config_from_cfg(cfg or {})
    if not tmdb_cfg.get("enabled") or not (tmdb_cfg.get("api_key") or tmdb_cfg.get("bearer_token")):
        card["poster_status"] = "TMDB 未配置"
        return card

    cache_key = local_media_poster_cache_key(str(card.get("source") or ""), str(card.get("raw_name") or ""))
    cached = local_media_cached_poster(cache_key)
    if cached:
        return apply_local_media_poster(card, cached)

    query, year = local_media_tmdb_query(str(card.get("raw_name") or card.get("title") or ""))
    if not query:
        card["poster_status"] = "TMDB 未匹配"
        return card
    try:
        result = tmdb_search_movie(query, year, tmdb_config=tmdb_cfg)
        tmdb_item = apply_tmdb_result({
            "title": query,
            "year": year,
            "poster_url": "",
            "poster_source": "",
        }, result, tmdb_config=tmdb_cfg)
        payload = {
            "query": query,
            "year": year,
            "tmdb_id": tmdb_item.get("tmdb_id") or "",
            "tmdb_title": tmdb_item.get("tmdb_title") or "",
            "tmdb_original_title": tmdb_item.get("tmdb_original_title") or "",
            "title_zh": tmdb_item.get("title_zh") or "",
            "poster_url": tmdb_item.get("poster_url") or "",
            "poster_source": tmdb_item.get("poster_source") or "",
            "poster_status": tmdb_item.get("poster_status") or tmdb_item.get("tmdb_status") or "TMDB 未匹配",
            "updated_at": now(),
        }
        store_local_media_poster(cache_key, payload)
        return apply_local_media_poster(card, payload)
    except Exception as exc:
        card["poster_status"] = f"TMDB 查询失败: {exc}"
        return card


def local_media_cards(history_items, limit: int = 8, cfg: Optional[Dict] = None) -> list[Dict]:
    cards = []
    for source, item in history_items or []:
        status = (item or {}).get("status")
        if status not in {"done", "transfer_done", "failed", "verify_failed", "transfer_failed"}:
            continue
        name = item_display_name(source)
        size_value = (item or {}).get("last_size") or (item or {}).get("size") or 0
        # 检测是否有杜比视界
        upper_text = f"{name} {source}".upper()
        has_dv = any(token in upper_text for token in ("DV", "DOLBY", "VISION", "DOVI"))

        _, release_year = local_media_tmdb_query(name)

        cards.append({
            "title": name,
            "raw_name": name,
            "subtitle": status_label(status),
            "source": source,
            "resolution": infer_resolution_label(f"{name} {source}"),
            "year": release_year,
            "size": format_size(size_value) if size_value else "-",
            "completed_at": (item or {}).get("finished_at") or (item or {}).get("done_at") or "",
            "status": "done" if status in {"done", "transfer_done"} else "pending_confirm",
            "match_status": "ISO 归档完成" if status in {"done", "transfer_done"} else "待手动绑定 ID",
            "initial": (name[:1] or "I").upper(),
            "is_dv": has_dv,
            "poster_path": "",
            "poster_status": "等待 TMDB 海报",
        })
        if len(cards) >= limit:
            break

    if cfg:
        cards = [enrich_local_media_card_with_tmdb(card, cfg) for card in cards]
    return cards


DEFAULT_RELEASE_CALENDAR_PAYLOAD = {
    "mode": "curated_with_sources",
    "updated_at": "2026-06-26",
    "primary_source": {
        "name": "Blu-ray.com Release Calendar",
        "url": "https://www.blu-ray.com/movies/releasedates.php",
        "usage": "基础发行日历源。",
    },
    "review_sources": [
        {"name": "碟影", "usage": "中文碟讯与片单校对。"},
        {"name": "贴吧 / 豆瓣", "usage": "社区和厂牌片单人工补充。"},
    ],
    "tmdb": {
        "enabled": False,
        "status": "not_configured",
        "message": "设置 TMDB_API_KEY 或 TMDB_BEARER_TOKEN 后可自动补中文名和海报",
        "matched_count": 0,
    },
    "items": [
        {
            "date": "06.28",
            "studio": "Criterion",
            "title": "4K UHD 修复版",
            "specs": "Dolby Vision / HDR10 / 原盘候选",
            "region": "US",
            "status": "待关注",
            "accent": "emerald",
            "source": "Blu-ray.com",
            "review": "待中文校对",
        },
        {
            "date": "07.02",
            "studio": "Arrow",
            "title": "导演剪辑版蓝光",
            "specs": "1080p AVC / DTS-HD MA / 可洗版",
            "region": "UK",
            "status": "可替换",
            "accent": "blue",
            "source": "Blu-ray.com",
            "review": "待碟影校对",
        },
        {
            "date": "07.09",
            "studio": "Kino",
            "title": "经典片新版发行",
            "specs": "4K 扫描 / 双碟版 / 收藏向",
            "region": "US",
            "status": "待入库",
            "accent": "amber",
            "source": "Blu-ray.com",
            "review": "待社区校对",
        },
        {
            "date": "07.16",
            "studio": "Manual",
            "title": "中文校对片单",
            "specs": "碟影 / 贴吧 / 豆瓣人工补充",
            "region": "自定义",
            "status": "校对层",
            "accent": "zinc",
            "source": "人工维护",
            "review": "本地覆盖",
        },
    ],
}


def normalize_release_calendar_item(raw: Dict) -> Dict:
    popularity = raw.get("popularity")
    try:
        popularity = int(popularity)
    except (TypeError, ValueError):
        popularity = 9999
    title = str(raw.get("title") or "未命名发行条目")
    title_zh = str(raw.get("title_zh") or raw.get("chinese_title") or "").strip()
    title_status = str(raw.get("title_status") or ("中文已校对" if title_zh else "显示原名"))
    if title_status in {"待中文名", "中文名待校对"}:
        title_status = "显示原名"
    poster_url = str(raw.get("poster_url") or raw.get("poster") or "").strip()
    poster_initials = "".join([part[:1] for part in re.split(r"\s+", title.strip()) if part])[:2].upper()
    if not poster_initials:
        poster_initials = title[:2]
    date_text = str(raw.get("date") or "待定")
    sort_date = str(raw.get("sort_date") or "9999-12-31")
    release_label = sort_date if re.match(r"^\d{4}-\d{2}-\d{2}$", sort_date) and sort_date != "9999-12-31" else date_text
    return {
        "date": date_text,
        "sort_date": sort_date,
        "release_label": release_label,
        "studio": str(raw.get("studio") or "Unknown"),
        "title": title,
        "title_zh": title_zh,
        "title_status": title_status,
        "year": str(raw.get("year") or ""),
        "specs": str(raw.get("specs") or "规格待补"),
        "region": str(raw.get("region") or "待定"),
        "status": str(raw.get("status") or "待校对"),
        "accent": str(raw.get("accent") or "zinc"),
        "source": str(raw.get("source") or "本地维护"),
        "url": str(raw.get("url") or raw.get("source_url") or ""),
        "source_url": str(raw.get("source_url") or raw.get("url") or ""),
        "poster_url": poster_url,
        "poster_source": str(raw.get("poster_source") or ("人工维护" if poster_url else "")),
        "poster_status": str(raw.get("poster_status") or ("海报已补" if poster_url else "待补海报")),
        "poster_initials": poster_initials,
        "popularity": popularity,
        "review": str(raw.get("review") or "待校对"),
        "tmdb_id": raw.get("tmdb_id") or "",
        "tmdb_title": str(raw.get("tmdb_title") or ""),
        "tmdb_original_title": str(raw.get("tmdb_original_title") or ""),
        "tmdb_status": str(raw.get("tmdb_status") or "TMDB 未配置"),
    }


def release_calendar_sort_key(item: Dict):
    return (item.get("sort_date") or "9999-12-31", item.get("popularity") or 9999, item.get("title") or "")


def release_calendar_date(item: Dict):
    raw_date = str(item.get("sort_date") or "")[:10]
    try:
        return datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        return None


def select_release_calendar_window(items: list[Dict], limit: int = 12) -> tuple[list[Dict], Dict]:
    today = datetime.now().date()
    dated_items = [(release_calendar_date(item), item) for item in items]
    upcoming = [(date_value, item) for date_value, item in dated_items if date_value and date_value >= today]
    undated = [item for date_value, item in dated_items if not date_value]
    recent = [(date_value, item) for date_value, item in dated_items if date_value and date_value < today]

    if upcoming:
        selected = [item for _date, item in sorted(upcoming, key=lambda pair: release_calendar_sort_key(pair[1]))]
        selected.extend(undated)
        mode = "upcoming"
        label = "今日起发行"
        note = "按今天日期优先显示待发售条目"
    else:
        selected = [
            item
            for _date, item in sorted(
                recent,
                key=lambda pair: (
                    pair[0] or datetime.min.date(),
                    -(pair[1].get("popularity") or 9999),
                    pair[1].get("title") or "",
                ),
                reverse=True,
            )
        ]
        selected.extend(undated)
        mode = "recent"
        label = "最近已发售"
        note = "当前缓存没有今天之后的条目，暂时显示最近已发售"

    return selected[:limit], {
        "mode": mode,
        "label": label,
        "note": note,
        "today": today.isoformat(),
        "total_count": len(items),
        "visible_count": min(len(selected), limit),
        "upcoming_count": len(upcoming),
        "recent_count": len(recent),
    }


def release_calendar_payload() -> Dict:
    """首页蓝光发行日历第三版：基础源 + 中文人工校对层。

    首页只读取本地 JSON 缓存，避免渲染时依赖外网。外网刷新通过
    /api/release-calendar/refresh 或 scripts/update_release_calendar.py 手动触发。
    """
    payload = DEFAULT_RELEASE_CALENDAR_PAYLOAD.copy()
    if RELEASE_CALENDAR_PATH.exists():
        try:
            loaded = json.loads(RELEASE_CALENDAR_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload.update({key: value for key, value in loaded.items() if key != "items"})
                if isinstance(loaded.get("items"), list):
                    payload["items"] = loaded["items"]
        except Exception as exc:
            log(f"发行日历数据读取失败，使用内置兜底: {exc}")
    all_items = sorted([
        normalize_release_calendar_item(item)
        for item in payload.get("items", [])
        if isinstance(item, dict)
    ], key=release_calendar_sort_key)
    if not all_items:
        all_items = sorted(
            [normalize_release_calendar_item(item) for item in DEFAULT_RELEASE_CALENDAR_PAYLOAD["items"]],
            key=release_calendar_sort_key,
        )
    payload["all_items_count"] = len(all_items)
    payload["items"], payload["window"] = select_release_calendar_window(all_items)
    return payload


def create_isolated_cd2_client(cfg: Dict):
    """Create a short-lived CD2 client without replacing the shared queue client."""
    if not CloudDriveClient:
        return None, "缺少 clouddrive2-client 依赖"
    if not cfg.get("cd2_api_enabled"):
        return None, "CD2 API 未启用"
    addr = normalize_cd2_api_addr(cfg.get("cd2_api_addr"))
    auth_mode = cd2_auth_mode_from_cfg(cfg)
    username = str(cfg.get("cd2_api_username") or "").strip()
    secret = str(cfg.get("cd2_api_password") or "")
    if not addr or not secret:
        return None, "CD2 认证信息不完整"
    if auth_mode == "password" and not username:
        return None, "CD2 缺少用户名"
    client = None
    try:
        client = CloudDriveClient(addr, options=CD2_GRPC_CHANNEL_OPTIONS)
        if auth_mode == "api_token":
            client.jwt_token = secret
        elif not client.authenticate(username, secret):
            raise RuntimeError("CD2 认证失败：请检查用户名密码")
        return client, ""
    except Exception as exc:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        return None, cd2_error_message(exc)


def cd2_candidate_scan_config_key(cfg: Dict):
    return (
        cd2_client_key_from_cfg(cfg),
        tuple(parse_cd2_remote_source_dirs(cfg.get("cd2_remote_source_dirs"))),
        tuple(cd2_remote_source_roots(cfg)),
        int_config(cfg, "cd2_remote_scan_depth", DEFAULT_CONFIG["cd2_remote_scan_depth"], minimum=1),
        bool(cfg.get("cd2_manual_pull_enabled")),
        bool(cfg.get("cd2_auto_pull_enabled")),
        normalize_path_text(cd2_pull_dest_dir_from_cfg(cfg)),
    )


def reset_cd2_candidate_scan_controller() -> None:
    with cd2_candidate_scan_lock:
        client = cd2_candidate_scan_state.get("client")
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        cd2_candidate_scan_state.update({
            "thread": None,
            "event": None,
            "client": None,
            "config_key": None,
            "started_at": None,
            "started_monotonic": 0.0,
            "timed_out": False,
            "payload": None,
            "last_success": None,
        })


def candidate_scan_timeout_payload(cfg: Dict, config_key, message: str = "CD2 远程候选扫描超时，请稍后重试") -> Dict:
    with cd2_candidate_scan_lock:
        last_success = cd2_candidate_scan_state.get("last_success")
        stale_payload = None
        if last_success and last_success.get("config_key") == config_key:
            stale_payload = dict(last_success.get("payload") or {})
            stale_payload["candidates"] = list(stale_payload.get("candidates") or [])
    payload = stale_payload or {
        "ok": False,
        "candidates": [],
        "candidate_count": 0,
        "errors": [],
    }
    payload.update({
        "ok": False,
        "scan_timeout": True,
        "stale": bool(stale_payload),
        "message": message,
    })
    return payload


def controlled_cd2_remote_candidates(
    cfg: Dict,
    force_refresh: bool = False,
    timeout_seconds: float = CD2_CANDIDATE_SCAN_TIMEOUT_SECONDS,
) -> Dict:
    config_key = cd2_candidate_scan_config_key(cfg)
    with cd2_candidate_scan_lock:
        thread = cd2_candidate_scan_state.get("thread")
        if thread is not None and thread.is_alive():
            return candidate_scan_timeout_payload(cfg, config_key)
        last_success = cd2_candidate_scan_state.get("last_success")
        if (
            not force_refresh
            and last_success
            and last_success.get("config_key") == config_key
            and time.monotonic() - float(last_success.get("completed_monotonic") or 0) < CD2_CANDIDATE_SCAN_CACHE_SECONDS
        ):
            payload = dict(last_success.get("payload") or {})
            payload["candidates"] = list(payload.get("candidates") or [])
            payload["cache_hit"] = True
            return payload
        event = threading.Event()
        cd2_candidate_scan_state.update({
            "thread": None,
            "event": event,
            "client": None,
            "config_key": config_key,
            "started_at": now(),
            "started_monotonic": time.monotonic(),
            "timed_out": False,
            "payload": None,
        })

        def worker():
            payload = None
            client = None
            try:
                client, error = create_isolated_cd2_client(cfg)
                if client is None:
                    payload = {
                        "ok": False,
                        "scan_timeout": False,
                        "candidates": [],
                        "candidate_count": 0,
                        "message": error,
                    }
                    return
                with cd2_candidate_scan_lock:
                    if cd2_candidate_scan_state.get("config_key") == config_key:
                        cd2_candidate_scan_state["client"] = client
                payload = scan_cd2_remote_candidates(cfg, force_refresh=force_refresh, client=client)
            except Exception as exc:
                payload = {
                    "ok": False,
                    "scan_timeout": False,
                    "candidates": [],
                    "candidate_count": 0,
                    "message": f"CD2 远程目录扫描失败：{cd2_error_message(exc)}",
                }
            finally:
                try:
                    client.close()
                except Exception:
                    pass
                with cd2_candidate_scan_lock:
                    if cd2_candidate_scan_state.get("config_key") == config_key:
                        cd2_candidate_scan_state["payload"] = payload
                        cd2_candidate_scan_state["client"] = None
                        if payload and payload.get("ok"):
                            cd2_candidate_scan_state["last_success"] = {
                                "config_key": config_key,
                                "payload": dict(payload),
                                "completed_monotonic": time.monotonic(),
                            }
                        cd2_candidate_scan_state["thread"] = None
                        event.set()

        thread = threading.Thread(target=worker, name="cd2-candidate-scan", daemon=True)
        cd2_candidate_scan_state["thread"] = thread
        thread.start()
    if event.wait(max(0.0, float(timeout_seconds))):
        with cd2_candidate_scan_lock:
            payload = dict(cd2_candidate_scan_state.get("payload") or {})
            payload["candidates"] = list(payload.get("candidates") or [])
            return payload
    with cd2_candidate_scan_lock:
        cd2_candidate_scan_state["timed_out"] = True
        client = cd2_candidate_scan_state.get("client")
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    return candidate_scan_timeout_payload(cfg, config_key)


def release_calendar_items() -> list[Dict]:
    return release_calendar_payload()["items"]


def release_calendar_month(items: list[Dict]) -> Dict:
    """Build a compact month grid for the homepage release calendar."""
    releases_by_day: dict[str, list[Dict]] = {}
    parsed_dates: list[datetime] = []
    for item in items:
        raw_date = str(item.get("sort_date") or "")[:10]
        try:
            release_date = datetime.strptime(raw_date, "%Y-%m-%d")
        except ValueError:
            continue
        key = release_date.date().isoformat()
        releases_by_day.setdefault(key, []).append(item)
        parsed_dates.append(release_date)

    month_ref = parsed_dates[0] if parsed_dates else datetime.now()
    first_day = datetime(month_ref.year, month_ref.month, 1)
    if month_ref.month == 12:
        next_month = datetime(month_ref.year + 1, 1, 1)
    else:
        next_month = datetime(month_ref.year, month_ref.month + 1, 1)
    days_in_month = (next_month - first_day).days

    cells: list[Dict] = [{"empty": True} for _ in range(first_day.weekday())]
    release_days: list[Dict] = []
    for day in range(1, days_in_month + 1):
        current = datetime(month_ref.year, month_ref.month, day)
        key = current.date().isoformat()
        day_items = releases_by_day.get(key, [])
        cell = {
            "empty": False,
            "day": day,
            "date": key,
            "label": f"{month_ref.month:02d}.{day:02d}",
            "count": len(day_items),
            "releases": day_items[:2],
            "has_items": bool(day_items),
        }
        cells.append(cell)
        if day_items:
            release_days.append(cell)

    while len(cells) % 7:
        cells.append({"empty": True})

    return {
        "title": f"{month_ref.year}年{month_ref.month}月",
        "weekdays": ["一", "二", "三", "四", "五", "六", "日"],
        "cells": cells,
        "release_days": release_days,
    }


@app.route("/api/release-calendar/refresh", methods=["POST"])
def api_release_calendar_refresh():
    try:
        data = request.get_json(silent=True) or {}
        limit = int(data.get("limit") or request.form.get("limit") or 12)
        limit = max(4, min(limit, 24))
        cfg = load_config()
        payload = refresh_release_calendar_cache(RELEASE_CALENDAR_PATH, limit=limit, tmdb_config=tmdb_config_from_cfg(cfg))
        log(f"蓝光发行日历已从 Blu-ray.com 刷新: {len(payload.get('items', []))} 条")
        return jsonify({
            "ok": True,
            "count": len(payload.get("items", [])),
            "updated_at": payload.get("updated_at"),
            "fetched_at": payload.get("fetched_at"),
            "source": payload.get("primary_source", {}),
            "tmdb": payload.get("tmdb", {}),
        })
    except Exception as exc:
        log(f"蓝光发行日历外网刷新失败: {exc}")
        return jsonify({"ok": False, "error": f"外网刷新失败：{exc}"}), 502


@app.route("/api/tmdb/test", methods=["POST"])
def api_tmdb_test():
    cfg = load_config()
    apply_tmdb_form(cfg, request.form)
    tmdb_cfg = tmdb_config_from_cfg(cfg)
    if not tmdb_cfg.get("enabled"):
        return jsonify({"ok": False, "message": "TMDB 元数据补全未启用"}), 400
    if not tmdb_cfg.get("api_key"):
        return jsonify({"ok": False, "message": "请先填写 TMDB API Token"}), 400
    try:
        payload = tmdb_get_json("/configuration", {}, tmdb_config=tmdb_cfg, timeout=10)
        images = payload.get("images") or {}
        return jsonify({
            "ok": True,
            "message": "TMDB 连接正常",
            "secure_base_url": images.get("secure_base_url") or "",
            "poster_sizes": images.get("poster_sizes") or [],
        })
    except Exception as exc:
        return jsonify({"ok": False, "message": f"TMDB 测试失败：{exc}"}), 400


def first_failed_job(history_items) -> Optional[Dict]:
    for source, item in history_items or []:
        if (item or {}).get("status") in {"failed", "verify_failed", "transfer_failed"}:
            failure_code = (item or {}).get("failure_code")
            return {
                "name": item_display_name(source),
                "path": source,
                "stage": (item or {}).get("failure_label") or status_label((item or {}).get("status")),
                "error_msg": (item or {}).get("error") or (item or {}).get("last_error") or "-",
                "advice": task_issue_text(item),
                "failure_code": failure_code or "",
                "can_rerun": failure_code not in CD2_UPLOAD_RECHECK_FAILURES,
                "can_recheck": failure_code in CD2_UPLOAD_RECHECK_FAILURES,
                "can_confirm_upload": failure_code in CD2_UPLOAD_RECHECK_FAILURES,
            }
    return None


def cleanup_interrupted_output_partials(cfg: Dict) -> int:
    output_dir = Path(cfg["output_dir"]).expanduser()
    removed = 0
    try:
        partials = list(output_dir.glob("*.iso.partial"))
    except Exception as exc:
        log(f"扫描输出目录临时ISO失败: {exc}")
        return 0
    for partial in partials:
        try:
            partial.unlink()
            removed += 1
            log(f"清理上次中断残留临时ISO: {partial}")
        except Exception as exc:
            log(f"清理上次中断残留临时ISO失败 {partial}: {exc}")
    return removed


def interrupted_partial_path(target: Path) -> Path:
    return target.with_suffix(target.suffix + ".partial")


def interrupted_cd2_final_path(target: Path, cfg: Dict) -> Optional[Path]:
    if not cfg.get("cd2_transfer_enabled"):
        return None
    target_dir = resolve_cd2_target_dir(cfg)
    if not target_dir:
        return None
    final_path = target_dir / target.name
    return final_path if final_path.exists() else None


def recovered_source_size(source: Optional[Path], target: Path) -> int:
    if source and source.exists():
        return size_of(source)
    return target.stat().st_size if target.exists() else 0


def remove_invalid_recovered_iso(target: Path) -> None:
    try:
        target.unlink()
        log(f"上次中断留下的ISO校验失败，已删除并等待重新封装: {target}")
    except Exception as exc:
        log(f"上次中断留下的ISO校验失败但删除失败 {target}: {exc}")


def recovered_iso_is_usable(target: Path) -> bool:
    if not target.exists():
        return False
    if not validate_iso(target):
        remove_invalid_recovered_iso(target)
        return False
    return True


@dataclass
class RecoveredTransfer:
    target: Path
    started_at: Optional[str]
    finished_at: Optional[str]
    ok: bool


def recover_iso_transfer(
    source: Path,
    target: Path,
    cfg: Dict,
    active: Dict,
    source_size: int,
) -> RecoveredTransfer:
    transfer_started_at = active.get("transfer_started_at")
    transfer_finished_at = active.get("transfer_finished_at")
    if not cfg.get("cd2_transfer_enabled"):
        return RecoveredTransfer(target, transfer_started_at, transfer_finished_at, True)

    target_dir = resolve_cd2_target_dir(cfg)
    if target_dir and path_in_root(target, target_dir):
        transfer_started_at = transfer_started_at or active.get("pack_finished_at") or now()
        transfer_finished_at = transfer_finished_at or now()
        return RecoveredTransfer(target, transfer_started_at, transfer_finished_at, True)

    task_started_at = active.get("task_started_at") or active.get("started_at") or now()
    transfer_started_at = mark_transfer_started(source, target, task_started_at)
    moved_target = transfer_iso_to_mount(target, cfg)
    transfer_finished_at = now()
    if not moved_target:
        record_transfer_failure(source, target, source_size, transfer_finished_at)
        return RecoveredTransfer(target, transfer_started_at, transfer_finished_at, False)
    return RecoveredTransfer(moved_target, transfer_started_at, transfer_finished_at, True)


def finish_recovered_iso(source: Optional[Path], target: Path, cfg: Dict, active: Dict) -> bool:
    if not recovered_iso_is_usable(target):
        return False
    if not source:
        log(f"检测到上次中断留下的完整ISO，但缺少源任务记录，保留文件等待人工处理: {target}")
        return False

    replacement_candidates = find_replacement_iso_candidates(source, target, cfg)
    source_size = recovered_source_size(source, target)
    transfer = recover_iso_transfer(source, target, cfg, active, source_size)
    if not transfer.ok:
        return True

    delete_source_error = delete_source_if_configured(source, cfg) if source.exists() else None
    finish_process_item_success(
        source,
        transfer.target,
        source_size,
        cfg,
        transfer.started_at,
        transfer.finished_at,
        delete_source_error,
    )
    cleanup_recovered_output_copy(active, source, target, transfer.target, cfg)
    cleanup_replaced_iso_candidates(source, transfer.target, replacement_candidates)
    log(f"检测到上次中断时ISO已生成，已从中断点恢复: {transfer.target}")
    return True


def mark_interrupted_source_for_rescan(source: Optional[str]) -> bool:
    if not source or not Path(source).exists():
        return False
    with lock:
        item = state.setdefault("items", {}).setdefault(source, {})
        if item.get("status") in TERMINAL_STATUSES:
            state["active"] = None
            save_state_locked()
            return False
        item["status"] = "waiting_stable"
        item["last_changed"] = now()
        state["active"] = None
        state["events"] = state.get("events", [])[-199:] + [f"[{now()}] 检测到上次任务中断，已恢复等待重新扫描"]
        save_state_locked()
    return True


def pop_interrupted_active() -> Dict:
    with lock:
        active = dict(state.get("active") or {})
        if not active:
            return {}
        state["active"] = None
        save_state_locked()
    return active


def cleanup_interrupted_task_partial(target: Path) -> None:
    partial = interrupted_partial_path(target)
    try:
        partial.unlink()
        log(f"清理上次中断任务临时ISO: {partial}")
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"清理上次中断任务临时ISO失败 {partial}: {exc}")


def interrupted_recovery_targets(target: Path, cfg: Dict):
    yield target
    final_path = interrupted_cd2_final_path(target, cfg)
    if final_path and final_path != target:
        yield final_path


def interrupted_existing_cd2_target(path: Optional[Path], cfg: Dict) -> Optional[Path]:
    if not path or not cfg.get("cd2_transfer_enabled"):
        return None
    target_dir = resolve_cd2_target_dir(cfg)
    if not target_dir:
        return None
    path = path.expanduser()
    if path_in_root(path, target_dir):
        return path if path.exists() else None
    final_path = target_dir / path.name
    return final_path if final_path.exists() else None


def add_recovery_target(targets: list[Path], seen: set[str], path: Optional[Path]) -> None:
    if not path:
        return
    try:
        resolved_key = str(path.expanduser().resolve())
    except Exception:
        resolved_key = str(path.expanduser())
    if resolved_key in seen:
        return
    seen.add(resolved_key)
    targets.append(path.expanduser())


def interrupted_output_target(active: Dict, source: Optional[Path], target: Optional[Path], cfg: Dict) -> Optional[Path]:
    output_target = active.get("output_target") or active.get("original_target")
    if output_target:
        return Path(output_target).expanduser()
    if target and target.name.endswith(".partial"):
        return Path(str(target)[:-len(".partial")]).expanduser()
    if not source:
        return None
    output_dir = Path(cfg["output_dir"]).expanduser()
    if target and target.suffix.lower() == ".iso":
        inferred = output_dir / target.name
        if inferred.exists():
            return inferred
    inferred = output_dir / f"{safe_filename(source.name)}.iso"
    return inferred if inferred.exists() else None


def interrupted_recovery_candidates(active: Dict, source: Optional[Path], target: Optional[Path], cfg: Dict) -> list[Path]:
    targets: list[Path] = []
    seen: set[str] = set()
    output_target = interrupted_output_target(active, source, target, cfg)
    add_recovery_target(targets, seen, interrupted_existing_cd2_target(target, cfg))
    add_recovery_target(targets, seen, interrupted_existing_cd2_target(output_target, cfg))
    add_recovery_target(targets, seen, output_target)
    add_recovery_target(targets, seen, target)
    for candidate in list(targets):
        for recovery_target in interrupted_recovery_targets(candidate, cfg):
            add_recovery_target(targets, seen, recovery_target)
    return targets


def cleanup_recovered_output_copy(
    active: Dict,
    source: Optional[Path],
    recovery_target: Path,
    final_target: Path,
    cfg: Dict,
) -> None:
    if not cfg.get("cd2_transfer_enabled"):
        return
    target_dir = resolve_cd2_target_dir(cfg)
    if not target_dir or not path_in_root(final_target, target_dir):
        return
    output_target = interrupted_output_target(active, source, recovery_target, cfg)
    if not output_target or output_target == final_target or not output_target.exists():
        return
    output_dir = Path(cfg["output_dir"]).expanduser()
    if output_target.suffix.lower() != ".iso" or not path_in_root(output_target, output_dir):
        return
    try:
        output_target.unlink()
        log(f"清理恢复后残留的输出目录ISO: {output_target}")
    except Exception as exc:
        log(f"清理恢复后残留的输出目录ISO失败 {output_target}: {exc}")


def recover_interrupted_task(cfg: Optional[Dict] = None) -> None:
    cfg = cfg or load_config()
    active = pop_interrupted_active()
    if not active:
        return

    source_text = active.get("source")
    target_text = active.get("target")
    source = Path(source_text) if source_text else None
    target = Path(target_text).expanduser() if target_text else None

    if target:
        cleanup_interrupted_task_partial(target)
    for recovery_target in interrupted_recovery_candidates(active, source, target, cfg):
        cleanup_interrupted_task_partial(recovery_target)
        if finish_recovered_iso(source, recovery_target, cfg, active):
            return

    mark_interrupted_source_for_rescan(source_text)


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
        cleanup_interrupted_output_partials(cfg)
        recover_interrupted_task(cfg)
        t = threading.Thread(target=scanner_loop, daemon=True)
        t.start()
        worker_started = True


@app.after_request
def add_no_cache_headers(response):
    """禁用所有页面缓存"""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response


@app.before_request
def before_request():
    start_worker_once()
    cfg = load_config()
    if not auth_enabled(cfg):
        return None
    if request.path in {"/login", "/healthz", "/favicon.ico", "/api/cd2/webhook"}:
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


@app.route("/favicon.ico")
def favicon():
    return "", 204


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
    return render_template(
        "login.html",
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
    context = ui_state_context(cfg)
    context["stats"] = dashboard_stats(context["history_items"])
    context["cached_movies"] = local_media_cards(context["history_items"], cfg=cfg)
    calendar_payload = release_calendar_payload()
    context["calendar_releases"] = calendar_payload["items"]
    context["calendar_source"] = calendar_payload
    context["calendar_month"] = release_calendar_month(calendar_payload["items"])
    return render_template("index.html", **context)


@app.route("/workspace")
def workspace():
    context = ui_state_context()
    context["last_failed_job"] = first_failed_job(context["history_items"])
    return render_template("workspace.html", **context)


@app.route("/files")
def files():
    context = ui_state_context()
    cd2_browser_root = resolve_cd2_browser_root(context["cfg"])
    context["browser_roots"] = {
        "watch": context["cfg"].get("watch_dir", ""),
        "output": context["cfg"].get("output_dir", ""),
        "cd2": str(cd2_browser_root),
        "cd2_default": str(Path(str(context["cfg"].get("cd2_target_dir") or DEFAULT_CONFIG["cd2_target_dir"])).expanduser()),
    }
    return render_template("files.html", **context)


@app.route("/logs")
def logs():
    context = ui_state_context()
    return render_template("logs.html", **context)


@app.route("/compare")
def compare():
    context = ui_state_context()
    cd2_browser_root = resolve_cd2_browser_root(context["cfg"])
    cd2_finished_root = Path(str(context["cfg"].get("cd2_target_dir") or DEFAULT_CONFIG["cd2_target_dir"])).expanduser()
    context["browser_roots"] = {
        "watch": context["cfg"].get("watch_dir", ""),
        "output": context["cfg"].get("output_dir", ""),
        "cd2": str(cd2_browser_root),
        "cd2_finished": str(cd2_finished_root),
    }
    return render_template("compare.html", **context)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    cfg = load_config()
    if request.method == "GET":
        context = ui_state_context(cfg)
        return render_template("settings.html", **context)
    old_cd2_key = cd2_client_key_from_cfg(cfg)
    cfg["watch_dir"] = request.form.get("watch_dir", cfg["watch_dir"]).strip()
    cfg["output_dir"] = request.form.get("output_dir", cfg["output_dir"]).strip()
    try:
        cfg["scan_interval_seconds"] = parse_int_form("scan_interval_seconds", cfg["scan_interval_seconds"], minimum=5)
        cfg["stable_seconds"] = parse_int_form("stable_seconds", cfg["stable_seconds"], minimum=30)
        cfg["min_free_space_gb"] = parse_int_form("min_free_space_gb", cfg["min_free_space_gb"], minimum=0)
        cfg["cd2_queue_poll_seconds"] = parse_int_form("cd2_queue_poll_seconds", cfg.get("cd2_queue_poll_seconds", 10), minimum=1)
        cfg["cd2_event_debounce_seconds"] = parse_int_form("cd2_event_debounce_seconds", cfg.get("cd2_event_debounce_seconds", 10), minimum=0)
        cfg["cd2_event_dedupe_ttl_seconds"] = parse_int_form("cd2_event_dedupe_ttl_seconds", cfg.get("cd2_event_dedupe_ttl_seconds", 600), minimum=0)
        cfg["cd2_confirm_delay_seconds"] = parse_int_form("cd2_confirm_delay_seconds", cfg.get("cd2_confirm_delay_seconds", 30), minimum=0)
        cfg["cd2_confirm_stable_checks"] = parse_int_form("cd2_confirm_stable_checks", cfg.get("cd2_confirm_stable_checks", 1), minimum=1)
        cfg["cd2_remote_scan_depth"] = parse_int_form("cd2_remote_scan_depth", cfg.get("cd2_remote_scan_depth", 1), minimum=1)
        cfg["cd2_auto_pull_max_tasks_per_scan"] = parse_int_form("cd2_auto_pull_max_tasks_per_scan", cfg.get("cd2_auto_pull_max_tasks_per_scan", 1), minimum=1)
        cfg["cd2_auto_pull_max_active_tasks"] = parse_int_form("cd2_auto_pull_max_active_tasks", cfg.get("cd2_auto_pull_max_active_tasks", 1), minimum=1)
        cfg["cd2_auto_pull_min_size_gb"] = parse_int_form("cd2_auto_pull_min_size_gb", cfg.get("cd2_auto_pull_min_size_gb", 0), minimum=0)
        cfg["cd2_auto_pull_failure_cooldown_seconds"] = parse_int_form("cd2_auto_pull_failure_cooldown_seconds", cfg.get("cd2_auto_pull_failure_cooldown_seconds", CD2_AUTO_PULL_FAILURE_COOLDOWN_SECONDS), minimum=0)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    cfg["enabled"] = "enabled" in request.form
    cfg["delete_source_after_success"] = "delete_source_after_success" in request.form
    cfg["cd2_transfer_enabled"] = "cd2_transfer_enabled" in request.form
    cfg["cd2_wait_upload_complete"] = "cd2_wait_upload_complete" in request.form
    cfg["cd2_require_mount"] = "cd2_require_mount" in request.form
    cfg["cd2_mount_root"] = request.form.get("cd2_mount_root", cfg.get("cd2_mount_root", "/CloudNAS/CloudDrive")).strip()
    cfg["cd2_target_dir"] = request.form.get("cd2_target_dir", cfg.get("cd2_target_dir", "/CloudNAS/CloudDrive/00-未整理/00-mkiso")).strip()
    aliases = parse_cd2_path_alias_lines(request.form.get("cd2_path_aliases_text", cfg.get("cd2_path_aliases_text", "")))
    cfg["cd2_path_aliases"] = aliases or cd2_path_aliases_from_cfg(DEFAULT_CONFIG)
    cfg["cd2_path_aliases_text"] = cd2_path_aliases_to_text(cfg)
    cfg["cd2_upload_match_mode"] = cd2_upload_match_mode_from_cfg({
        "cd2_upload_match_mode": request.form.get("cd2_upload_match_mode", cfg.get("cd2_upload_match_mode"))
    })
    cfg["cd2_remote_source_dirs"] = parse_cd2_remote_source_dirs(request.form.get("cd2_remote_source_dirs_text", cfg.get("cd2_remote_source_dirs_text", "")))
    cfg["cd2_remote_source_dirs_text"] = cd2_remote_source_dirs_to_text(cfg)
    cfg["cd2_manual_pull_enabled"] = "cd2_manual_pull_enabled" in request.form
    cfg["cd2_auto_pull_enabled"] = "cd2_auto_pull_enabled" in request.form
    cfg["cd2_auto_pull_include_keywords"] = request.form.get("cd2_auto_pull_include_keywords", cfg.get("cd2_auto_pull_include_keywords", "")).strip()
    cfg["cd2_auto_pull_exclude_keywords"] = request.form.get("cd2_auto_pull_exclude_keywords", cfg.get("cd2_auto_pull_exclude_keywords", "")).strip()
    cfg["cd2_local_pull_dir"] = cfg["watch_dir"]
    cfg["cd2_remote_pull_dest_dir"] = normalize_path_text(request.form.get("cd2_remote_pull_dest_dir", cfg.get("cd2_remote_pull_dest_dir", "")))
    cfg["cd2_api_enabled"] = "cd2_api_enabled" in request.form
    cfg["cd2_auth_mode"] = cd2_auth_mode_from_cfg({"cd2_auth_mode": request.form.get("cd2_auth_mode", cfg.get("cd2_auth_mode", "api_token"))})
    cfg["cd2_api_addr"] = normalize_cd2_api_addr(request.form.get("cd2_api_addr", cfg.get("cd2_api_addr", "host.docker.internal:19798")))
    cfg["cd2_api_username"] = request.form.get("cd2_api_username", cfg.get("cd2_api_username", "")).strip()
    apply_tmdb_form(cfg, request.form)
    cfg["cd2_webhook_enabled"] = "cd2_webhook_enabled" in request.form
    cfg["cd2_event_source"] = request.form.get("cd2_event_source", cfg.get("cd2_event_source", "cd2")).strip() or "cd2"
    cfg["cd2_refresh_enabled"] = "cd2_refresh_enabled" in request.form
    cfg["cd2_refresh_after_source_event"] = "cd2_refresh_after_source_event" in request.form
    cfg["cd2_refresh_after_transfer"] = "cd2_refresh_after_transfer" in request.form
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
    new_cd2_webhook_secret = (request.form.get("cd2_webhook_secret") or "").strip()
    if new_cd2_webhook_secret:
        cfg["cd2_webhook_secret"] = new_cd2_webhook_secret
    save_config(cfg)
    if old_cd2_key != cd2_client_key_from_cfg(cfg):
        close_cd2_client()
        reset_cd2_candidate_scan_controller()
    Path(cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg["output_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_local_pull_dir") or cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_mount_root", DEFAULT_CONFIG["cd2_mount_root"])).expanduser().mkdir(parents=True, exist_ok=True)
    log("设置已保存")
    if request.form.get("scan"):
        threading.Thread(target=scan_once, args=(cfg,), daemon=True).start()
    return redirect(url_for("settings", saved=1))


@app.route("/api/cd2/test", methods=["POST"])
def api_cd2_test():
    cfg = load_config()
    apply_cd2_api_form(cfg, request.form)
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


@app.route("/api/cd2/directories", methods=["POST"])
def api_cd2_directories():
    cfg = load_config()
    apply_cd2_api_form(cfg, request.form)
    raw_path = (request.args.get("path") or request.form.get("path") or "/").strip() or "/"
    path = "/" if raw_path in {DIRECTORY_PICKER_ROOT, "/"} else normalize_path_text(raw_path)
    if not cfg.get("cd2_api_enabled"):
        return jsonify({"ok": False, "message": "CD2 API 未启用"}), 400
    client = get_cd2_client(cfg)
    if client is None:
        return jsonify({"ok": False, "message": cd2_client_cache.get("last_error") or "CD2 API 未连接"}), 400
    if not hasattr(client, "get_sub_files"):
        return jsonify({"ok": False, "message": "当前 clouddrive2-client 不支持目录浏览"}), 400

    try:
        children = list_cd2_sub_files(client, path, force_refresh=False)
    except Exception as exc:
        return jsonify({"ok": False, "message": f"无法读取 CD2 目录: {cd2_error_message(exc)}"}), 400

    entries = []
    for child in children:
        if not cd2_file_is_dir(child):
            continue
        child_path = cd2_file_path(child, path)
        entries.append({
            "name": cd2_file_name(child) or child_path.rsplit("/", 1)[-1] or child_path,
            "path": child_path,
            "readable": True,
        })
    entries.sort(key=lambda item: item["name"].lower())
    return jsonify({
        "ok": True,
        "path": path,
        "display_path": path,
        "parent": cd2_directory_parent(path),
        "entries": entries,
    })


@app.route("/api/cd2/webhook", methods=["POST"])
def api_cd2_webhook():
    cfg = load_config()
    if not cfg.get("cd2_webhook_enabled"):
        return jsonify({"ok": False, "message": "CD2 Webhook 未启用"}), 404
    if not cd2_webhook_secret_matches(cfg):
        return jsonify({"ok": False, "message": "CD2 Webhook 密钥无效"}), 401
    payload = cd2_webhook_payload()
    result = record_cd2_webhook_event(cfg, payload)
    if result["should_scan"]:
        event_path = result["event"].get("path") or ""
        if cfg.get("cd2_refresh_enabled") and cfg.get("cd2_refresh_after_source_event") and event_path:
            refresh = refresh_cd2_directory(cfg, event_path, "webhook")
            if refresh.get("ok"):
                log(f"CD2 Webhook 源目录刷新完成: {refresh.get('path')}")
            else:
                log(f"CD2 Webhook 源目录刷新失败: {refresh.get('message')}")
        threading.Thread(target=scan_once, args=(cfg,), daemon=True).start()
        log(f"CD2 Webhook 已触发复查: {result['event'].get('event')} {result['event'].get('path')}".strip())
    return jsonify({
        "ok": True,
        "message": "CD2 Webhook 已记录",
        "scan_triggered": result["should_scan"],
        "duplicate": result["duplicate"],
        "debounced": result["debounced"],
    })


@app.route("/api/cd2/remote-candidates")
def api_cd2_remote_candidates():
    cfg = load_config()
    force_refresh = (request.args.get("force") or "").strip().lower() in {"1", "true", "yes", "on"}
    return jsonify(controlled_cd2_remote_candidates(cfg, force_refresh=force_refresh))


@app.route("/api/cd2/pull", methods=["POST"])
def api_cd2_pull():
    cfg = load_config()
    payload = request.get_json(silent=True) if request.is_json else request.form
    source_path = normalize_path_text((payload or {}).get("path"))
    if cd2_pull_disabled():
        return jsonify({"ok": False, "message": "本地测试已禁用真实 CD2 拉取"}), 400
    if not (cfg.get("cd2_manual_pull_enabled") or cfg.get("cd2_auto_pull_enabled")):
        return jsonify({"ok": False, "message": "CD2 拉取未启用，请先开启手动拉取或自动拉取"}), 400
    result, status_code = create_cd2_pull_task(cfg, source_path, mode="manual")
    if result.get("ok"):
        log(f"CD2 手动拉取已创建: {source_path} -> {result.get('dest_dir')}")
    return jsonify(result), status_code


@app.route("/api/cd2/pull-record", methods=["DELETE", "POST"])
def api_cd2_pull_record():
    cfg = load_config()
    payload = request.get_json(silent=True) if request.is_json else request.form
    source_path = normalize_path_text((payload or {}).get("path"))
    result, status_code = clear_cd2_pull_record(cfg, source_path)
    if result.get("ok") and (result.get("removed_item_count") or result.get("removed_recent_count")):
        log(f"CD2 候选记录已清除: {source_path}")
    return jsonify(result), status_code


@app.route("/api/tasks/action", methods=["POST"])
def api_task_action():
    cfg = load_config()
    payload = request.get_json(silent=True) if request.is_json else request.form
    source_text = str((payload or {}).get("source") or "").strip()
    action = str((payload or {}).get("action") or "").strip().lower()
    if not source_text:
        return jsonify({"ok": False, "message": "缺少源路径"}), 400
    if action == "recheck":
        result, status_code, mode = reset_task_for_recheck(source_text, cfg)
        if result.get("ok"):
            if mode == "upload":
                threading.Thread(target=recheck_waiting_cd2_uploads, args=(cfg,), daemon=True).start()
            else:
                threading.Thread(target=scan_once, args=(cfg,), daemon=True).start()
        return jsonify(result), status_code
    if action == "confirm_upload":
        result, status_code = confirm_cd2_upload_task(source_text, cfg)
        return jsonify(result), status_code
    return jsonify({"ok": False, "message": "不支持的任务操作"}), 400



@app.route("/rerun", methods=["POST"])
def rerun_item():
    cfg = load_config()
    source_text = (request.form.get("source") or "").strip()
    force_cd2 = (request.form.get("force_cd2") or "").strip().lower() in {"1", "true", "yes", "on"}
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
    wait_status, wait_reason, pending_task = source_readiness_blocker(source, source_size, cd2_status, cfg, ignore_cd2_tasks=force_cd2)
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
            "manual_force_cd2": force_cd2,
        })
        if force_cd2:
            item["manual_force_reason"] = "忽略 CD2 下载/复制队列门禁"
        else:
            item.pop("manual_force_reason", None)
        item.pop("done_at", None)
        item.pop("target", None)
        save_state_locked()
    if force_cd2:
        log(f"手动强制封装（忽略 CD2 队列门禁）: {source}")
    else:
        log(f"\u624b\u52a8\u91cd\u65b0\u5c01\u88c5: {source}")
    threading.Thread(target=process_item, args=(source, cfg, force_cd2), daemon=True).start()
    return jsonify({"ok": True, "message": "\u5df2\u5f00\u59cb\u624b\u52a8\u5c01\u88c5", "source": str(source)})


@app.route("/api/status")
def api_status():
    cfg = load_config()
    with lock:
        snapshot = json.loads(json.dumps(state, ensure_ascii=False))
    snapshot["items"] = visible_iso_items(snapshot.get("items", {}))
    if cd2_status_poll_disabled():
        snapshot_items = snapshot.get("items", {})
        snapshot_active = snapshot.get("active")
        cd2_status = base_cd2_upload_status(cfg)
        _, cd2_status = cd2_error_status(cfg, cd2_status, "本地预览已暂停 CD2 状态轮询")
    else:
        snapshot_items, snapshot_active, cd2_status = attach_cd2_uploads(cfg, snapshot.get("items", {}), snapshot.get("active"))
    snapshot["items"] = {key: apply_task_timings(item, snapshot_active if snapshot_active and snapshot_active.get("source") == key else None) for key, item in snapshot_items.items()}
    if snapshot_active:
        snapshot["active"] = apply_task_timings(dict(snapshot_active), snapshot_active)
    safe_cd2_status = ui_safe_cd2_status(cd2_status)
    snapshot["cd2_status"] = safe_cd2_status
    file_operations = file_operation_status_payload()
    history_items = ordered_visible_items(snapshot["items"], snapshot.get("active"))
    stats = dashboard_stats(history_items)
    stats["active"] = int(stats.get("active") or 0) + int(file_operations.get("active_count") or 0)
    safe_cfg = ui_safe_config(cfg)
    return jsonify({
        "config": safe_cfg,
        "state": snapshot,
        "cd2_status": safe_cd2_status,
        "file_operations": file_operations,
        "stats": stats,
    })


@app.route("/api/logs")
def api_logs():
    return jsonify(logs_payload())


@app.route("/api/compare")
def api_compare():
    payload, status_code = scan_media_compare_payload()
    return jsonify(payload), status_code


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
    roots = file_browser_roots_from_config(cfg)
    root_name = (request.args.get("root") or "watch").strip()
    root = roots.get(root_name)
    if not root:
        return jsonify({"ok": False, "message": "无效的根目录"}), 400
    raw_path = (request.args.get("path") or str(root)).strip() or str(root)
    if raw_path == "/":
        raw_path = str(root)
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
    fast_cd2_listing = root_name == "cd2"
    try:
        children = []
        with os.scandir(path) as scan:
            for child in scan:
                try:
                    is_dir = child.is_dir()
                    stat = child.stat()
                    children.append((child.name, Path(child.path), is_dir, stat))
                except OSError:
                    continue
        children.sort(key=lambda item: (not item[2], item[0].lower()))
    except PermissionError:
        children = []
    except OSError as exc:
        return jsonify({"ok": False, "message": f"无法读取目录: {exc}"}), 400
    entries = []
    pack_lookup = file_browser_pack_lookup(cfg, resolve_paths=not fast_cd2_listing, include_names=fast_cd2_listing)
    for child_name, child_path, is_dir, stat in children:
        try:
            disc_type = file_browser_listing_disc_type(child_path, path, root_name, is_dir)
            stat_size = stat.st_size if stat else 0
            stat_mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S") if stat else ""
            entry = {
                "name": child_name,
                "path": str(child_path),
                "type": "dir" if is_dir else "file",
                "disc_type": disc_type,
                "size": stat_size,
                "mtime": stat_mtime,
                "readable": True if fast_cd2_listing else os.access(child_path, os.R_OK | os.X_OK),
            }
            if disc_type:
                entry.update(file_browser_pack_payload(
                    child_path,
                    disc_type,
                    pack_lookup,
                    cfg,
                    check_existing=not fast_cd2_listing,
                    match_name=fast_cd2_listing,
                ))
            entries.append(entry)
        except OSError:
            continue
    parent = path.parent if path.parent != path and path_in_root(path.parent, root) else None
    return jsonify({
        "ok": True,
        "root": root_name,
        "root_path": str(root),
        "path": str(path),
        "parent": str(parent) if parent else None,
        "entries": entries,
    })


@app.route("/api/file-properties")
def api_file_properties():
    cfg = load_config()
    root_name = str(request.args.get("root") or "watch").strip()
    raw_path = str(request.args.get("path") or "").strip()
    if not raw_path:
        return jsonify({"ok": False, "message": "请选择文件或目录"}), 400
    try:
        path, root = resolve_file_browser_path(cfg, root_name, raw_path)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "message": f"路径无效: {exc}"}), 400
    if not path.exists():
        return jsonify({"ok": False, "message": "路径不存在"}), 404
    try:
        return jsonify(file_property_payload(path, root_name, root, cfg))
    except OSError as exc:
        return jsonify({"ok": False, "message": f"无法读取属性: {exc}"}), 400


@app.route("/api/file-actions", methods=["POST"])
def api_file_actions():
    cfg = load_config()
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"copy", "move", "delete", "rename"}:
        return jsonify({"ok": False, "message": "不支持的文件操作"}), 400
    root_name = str(payload.get("root") or "watch").strip()
    raw_paths = payload.get("paths") or []
    if not isinstance(raw_paths, list) or not raw_paths:
        return jsonify({"ok": False, "message": "请先选择文件或目录"}), 400
    if len(raw_paths) > 50:
        return jsonify({"ok": False, "message": "一次最多处理 50 项"}), 400

    sources = []
    try:
        for raw_path in raw_paths:
            source, _root = resolve_file_browser_path(cfg, root_name, str(raw_path or ""))
            if not source.exists():
                return jsonify({"ok": False, "message": f"路径不存在: {source}"}), 404
            if source.resolve() == _root.resolve():
                return jsonify({"ok": False, "message": "不能直接操作根目录"}), 400
            sources.append(source)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "message": f"路径无效: {exc}"}), 400

    destination = None
    destination_kind = str(payload.get("destination") or "").strip().lower()
    if action == "copy" and destination_kind == "watch":
        result, status_code = create_cd2_monitor_copy_tasks_for_browser_sources(cfg, sources)
        return jsonify(result), status_code

    if action == "rename":
        if len(sources) != 1:
            return jsonify({"ok": False, "message": "重命名一次只能处理一个条目"}), 400
        new_name = str(payload.get("new_name") or "").strip()
        if not new_name:
            return jsonify({"ok": False, "message": "请填写新名称"}), 400
        if new_name in {".", ".."} or Path(new_name).name != new_name or any(sep in new_name for sep in ("/", "\\")):
            return jsonify({"ok": False, "message": "新名称不能包含路径分隔符"}), 400
        destination = (sources[0].parent / new_name).resolve()
        _, source_root = resolve_file_browser_path(cfg, root_name, str(sources[0]))
        if not path_in_root(destination, source_root.resolve()):
            return jsonify({"ok": False, "message": "重命名目标不能越过当前根目录"}), 400

    if action in {"copy", "move"}:
        if destination_kind == "watch":
            destination = Path(cfg["watch_dir"]).expanduser()
        elif destination_kind == "output":
            destination = Path(cfg["output_dir"]).expanduser()
        elif destination_kind == "custom":
            custom_path = normalize_path_text(payload.get("destination_path") or "")
            if not custom_path:
                return jsonify({"ok": False, "message": "请填写目标目录"}), 400
            destination = Path(custom_path).expanduser()
        else:
            return jsonify({"ok": False, "message": "请选择目标目录"}), 400
        try:
            destination = destination.resolve()
        except Exception as exc:
            return jsonify({"ok": False, "message": f"目标目录无效: {exc}"}), 400
        for source in sources:
            if source.resolve() == destination or path_in_root(destination, source.resolve()):
                return jsonify({"ok": False, "message": "目标目录不能位于源目录内部"}), 400

    if action == "delete":
        confirm = str(payload.get("confirm") or "").strip()
        if confirm != "DELETE":
            return jsonify({"ok": False, "message": "删除操作需要确认"}), 400
    if action == "move":
        confirm = str(payload.get("confirm") or "").strip()
        if confirm != "MOVE":
            return jsonify({"ok": False, "message": "移动操作需要确认"}), 400

    task_id = secrets.token_hex(8)
    with file_operation_lock:
        file_operation_tasks[task_id] = {
            "id": task_id,
            "ok": True,
            "action": action,
            "status": "queued",
            "message": "已加入后台任务",
            "total": len(sources),
            "done": 0,
            "sources": [str(source) for source in sources],
            "destination": str(destination) if destination else "",
            "destination_kind": payload.get("destination") or "",
            "created_at": now(),
            "updated_at": now(),
            "results": [],
        }
    threading.Thread(
        target=run_file_operation_task,
        args=(task_id, action, sources, destination),
        daemon=True,
    ).start()
    return jsonify({"ok": True, "task_id": task_id, "task": file_operation_snapshot(task_id)})


@app.route("/api/file-actions/<task_id>")
def api_file_action_status(task_id: str):
    task = file_operation_snapshot(task_id)
    if not task:
        return jsonify({"ok": False, "message": "任务不存在"}), 404
    return jsonify({"ok": True, "task": task})


if __name__ == "__main__":
    start_worker_once()
    cfg = load_config()
    Path(cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg["output_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_local_pull_dir") or cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_mount_root", DEFAULT_CONFIG["cd2_mount_root"])).expanduser().mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=15865, threaded=True)
