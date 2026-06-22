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
COPY_TASK_DONE_STATUSES = {"3", "completed", "complete", "done", "finish", "finished", "success", "succeeded", "已完成"}
CD2_UPLOAD_QUEUE_GRACE_POLLS = 3
CD2_UPLOAD_QUEUE_GRACE_MIN_SECONDS = 30
CD2_WEBHOOK_EVENT_LIMIT = 50
CD2_AUTO_PULL_FAILURE_COOLDOWN_SECONDS = 600
CD2_UPLOAD_MATCH_MODES = {"alias_then_suffix", "alias_only"}
FAILURE_LABELS = {
    "insufficient_space": "空间不足",
    "pack_failed": "封装失败",
    "verify_failed": "校验失败",
    "transfer_failed": "CD2 转移失败",
    "unexpected_error": "任务异常",
}
FAILURE_SUGGESTIONS = {
    "insufficient_space": "清理输出目录或降低最小空间阈值后等待下轮扫描。",
    "pack_failed": "查看系统日志里的 genisoimage 错误，确认原盘结构完整且路径可读。",
    "verify_failed": "保留源目录和 ISO，优先检查 xorriso 是否可用以及输出文件是否完整。",
    "transfer_failed": "检查 CD2 挂载目录、目标路径权限和磁盘空间后重新封装。",
    "unexpected_error": "查看系统日志里的异常堆栈，确认后可手动重新封装。",
}
WARNING_LABELS = {
    "delete_source_failed": "源文件删除失败",
}
WARNING_SUGGESTIONS = {
    "delete_source_failed": "ISO 已完成，手动检查源目录占用或权限后再删除。",
}
DIRECTORY_PICKER_ROOT = "@roots"
DIRECTORY_PICKER_SCOPES = {
    "watch_dir": ("watch_dir",),
    "output_dir": ("output_dir",),
    "cd2_mount_root": ("cd2_mount_root",),
    "cd2_target_dir": ("cd2_mount_root", "cd2_target_dir"),
    "cd2_local_pull_dir": ("watch_dir", "cd2_local_pull_dir"),
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
    migrate_legacy_cd2_pull_config(cfg, data)
    cfg["cd2_path_aliases"] = cd2_path_aliases_from_cfg(cfg)
    cfg["cd2_path_aliases_text"] = cd2_path_aliases_to_text(cfg)
    cfg["cd2_remote_source_dirs"] = parse_cd2_remote_source_dirs(cfg.get("cd2_remote_source_dirs"))
    cfg["cd2_remote_source_dirs_text"] = cd2_remote_source_dirs_to_text(cfg)
    if not cfg.get("web_secret_key"):
        cfg["web_secret_key"] = secrets.token_urlsafe(32)
        save_config(cfg)
    return cfg


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


def cd2_remote_source_allowed(path: str, cfg: Dict) -> bool:
    return any(remote_path_under(path, root) for root in cd2_remote_source_roots(cfg))


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
    return str(value or "")


def list_cd2_sub_files(client, path: str, force_refresh: bool = False):
    return list(client.get_sub_files(path, force_refresh=force_refresh))


def cd2_disc_type_for_remote_path(client, path: str) -> str:
    sub_files = list_cd2_sub_files(client, path, force_refresh=True)
    names = {cd2_file_name(item).lower() for item in sub_files if cd2_file_is_dir(item)}
    if "bdmv" in names:
        return "BDMV"
    if "video_ts" in names:
        return "VIDEO_TS"
    return ""


def scan_cd2_remote_candidates(cfg: Dict, force_refresh: bool = False) -> Dict:
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
        "pull_dest_dir": cd2_pull_dest_dir_from_cfg(cfg),
        "candidates": [],
        "errors": [],
    }
    if not roots:
        payload["message"] = "未配置 CD2 原盘监控路径（原盘来源目录）"
        return payload
    if not cfg.get("cd2_api_enabled"):
        payload["ok"] = False
        payload["message"] = "CD2 API 未启用"
        return payload
    client = get_cd2_client(cfg)
    if client is None:
        payload["ok"] = False
        payload["message"] = cd2_client_cache.get("last_error") or "CD2 API 未连接"
        return payload
    if not hasattr(client, "get_sub_files"):
        payload["ok"] = False
        payload["message"] = "当前 clouddrive2-client 不支持远程目录扫描"
        return payload
    for root, remote_root in zip(roots, remote_roots):
        stack = [(remote_root, 0, bool(force_refresh))]
        while stack:
            current_root, current_depth, current_force_refresh = stack.pop()
            try:
                children = list_cd2_sub_files(client, current_root, force_refresh=current_force_refresh)
            except Exception as exc:
                payload["errors"].append({"root": current_root, "message": cd2_error_message(exc)})
                continue
            for child in children:
                if not cd2_file_is_dir(child):
                    continue
                child_path = cd2_file_path(child, current_root)
                child_depth = current_depth + 1
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
    payload["candidate_count"] = len(payload["candidates"])
    payload["summary"] = cd2_remote_candidate_summary(payload["candidates"])
    payload["message"] = f"发现 {payload['candidate_count']} 个远程原盘候选"
    if payload["errors"] and not payload["candidates"]:
        payload["ok"] = False
        payload["message"] = "CD2 远程目录扫描失败"
    return payload


def record_cd2_pull_result(source_path: str, dest_dir: str, ok: bool, message: str, disc_type: str = "", result_paths=None) -> None:
    result = {
        "source_path": source_path,
        "dest_dir": dest_dir,
        "disc_type": disc_type,
        "ok": bool(ok),
        "message": message,
        "result_paths": list(result_paths or []),
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


def cd2_remote_candidate_status(cfg: Dict, source_path: str) -> Dict:
    source_path = normalize_path_text(source_path)
    local_source = cd2_local_pull_path_for_source(cfg, source_path)
    result = {
        "local_path": str(local_source),
        "pull_state": "new",
        "pull_status_label": "新候选",
    }
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
        items = list((state.get("items") or {}).values())
    count = 0
    for item in items:
        status = item.get("status") or ""
        if item.get("cd2_pull_mode") != "auto":
            continue
        if not item.get("cd2_pull_source") or item.get("cd2_pull_finished_at"):
            continue
        if status in TERMINAL_STATUSES:
            continue
        count += 1
    return count


def cd2_pull_already_tracked(source_path: str, local_source: Path, include_finished_source: bool = False) -> bool:
    source_path = normalize_path_text(source_path)
    local_key = str(local_source)
    with lock:
        items = dict(state.get("items", {}))
    for key, item in items.items():
        status = item.get("status")
        if status == "removed":
            continue
        if key == local_key and status not in TERMINAL_STATUSES:
            return True
        if include_finished_source and normalize_path_text(item.get("cd2_pull_source")) == source_path:
            return True
        if normalize_path_text(item.get("cd2_pull_source")) == source_path and status not in TERMINAL_STATUSES:
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
    removed_recent_count = 0
    removed_last_result = False

    with lock:
        active = state.get("active") or {}
        if active and (active.get("source") == local_key or normalize_path_text(active.get("cd2_pull_source")) == source_path):
            return {"ok": False, "message": "候选仍在运行中，不能清除记录"}, 409

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

        changed = bool(removed_items or removed_recent_count or removed_last_result)
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
    if not cd2_remote_source_allowed(source_path, cfg):
        return {"ok": False, "message": "远程源路径不在已配置的 CD2 源目录内"}, 403
    dest_dir = cd2_pull_dest_dir_from_cfg(cfg)
    if not dest_dir:
        return {"ok": False, "message": "请先配置 CD2 拉取到 /watch 的目标路径，或在路径别名里配置本地拉取目录到网盘路径的映射"}, 400
    if remote_path_under(dest_dir, source_path):
        return {"ok": False, "message": "CD2 拉取目标不能位于源目录内部"}, 400

    local_source = cd2_local_pull_path_for_source(cfg, source_path)
    include_finished = mode == "auto"
    if cd2_pull_already_tracked(source_path, local_source, include_finished_source=include_finished):
        return {"ok": False, "message": "该远程候选已经在拉取或封装流程中"}, 409
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
        record_cd2_pull_result(source_path, dest_dir, False, message)
        return {"ok": False, "message": message}, 400
    if not disc_type:
        message = "远程路径不是 BDMV / VIDEO_TS 原盘候选"
        record_cd2_pull_result(source_path, dest_dir, False, message)
        return {"ok": False, "message": message}, 400

    try:
        result = client.copy_file([source_path], dest_dir)
        ok, message, result_paths = cd2_result_success(result)
    except Exception as exc:
        ok, message, result_paths = False, cd2_error_message(exc), []
    record_cd2_pull_result(source_path, dest_dir, ok, message or "CD2 拉取任务已创建", disc_type, result_paths)
    if not ok:
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
                "message": "未配置 CD2 拉取到 /watch 的目标路径",
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

    payload = scan_cd2_remote_candidates(cfg, force_refresh=False)
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
    if not upload_map:
        return None
    direct = {normalize_upload_path(key): value for key, value in upload_map.items()}
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


def cd2_status_is_fresh_for_wait(cd2_status: Optional[Dict], wait_started_at: str) -> bool:
    checked_at = (cd2_status or {}).get("checked_at")
    checked_dt = parse_time(checked_at)
    started_dt = parse_time(wait_started_at)
    return bool(checked_dt and started_dt and checked_dt > started_dt)


def check_waiting_cd2_uploads(cfg: Dict, upload_map: Dict, cd2_status: Optional[Dict]) -> None:
    if not cfg.get("cd2_wait_upload_complete"):
        return
    now_value = now()
    connected = bool((cd2_status or {}).get("connected"))
    wait_error = (cd2_status or {}).get("human") or (cd2_status or {}).get("last_error") or "等待 CD2 API 连接"
    grace_seconds = cd2_upload_queue_grace_seconds(cfg)
    with lock:
        items = state.get("items", {})
        for key, item in items.items():
            if item.get("status") != "waiting_cd2_upload":
                continue
            wait_started_at = item.get("cd2_upload_wait_started_at") or item.get("transfer_finished_at") or now_value
            item["cd2_upload_wait_started_at"] = wait_started_at
            if not connected:
                item["error"] = f"等待 CD2 上传完成：{wait_error}"
                continue
            if not cd2_status_is_fresh_for_wait(cd2_status, wait_started_at):
                item["error"] = "等待 CD2 上传队列刷新"
                continue
            upload = find_upload_for_path(upload_map, item.get("target") or "", cfg)
            if upload:
                item["cd2_upload"] = upload
                item["cd2_upload_seen_at"] = item.get("cd2_upload_seen_at") or now_value
                if not cd2_upload_done(upload):
                    item["error"] = f"等待 CD2 上传完成：{upload.get('human') or upload.get('summary') or upload.get('status') or '上传中'}"
                    continue
            elif not item.get("cd2_upload_seen_at") and seconds_between(wait_started_at) < grace_seconds:
                item["error"] = f"等待 CD2 上传队列出现：{seconds_between(wait_started_at)}s / {grace_seconds}s"
                continue
            elif not item.get("cd2_upload_seen_at"):
                item["error"] = "未在 CD2 上传队列找到匹配任务，请检查路径别名或 CD2 上传状态"
                continue
            item["status"] = "transfer_done"
            item["finished_at"] = now_value
            item["done_at"] = now_value
            item["cd2_upload"] = upload or item.get("cd2_upload") or {}
            item["cd2_upload_done_at"] = now_value
            item.pop("error", None)
            if upload:
                log_message = f"CD2 上传完成: {item.get('target') or key}"
            else:
                log_message = f"CD2 上传队列已清理: {item.get('target') or key}"
            state.setdefault("events", []).append(f"[{now_value}] {log_message}")
            state["events"] = state["events"][-200:]
        save_state_locked()


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


def prepare_cd2_transfer_paths(target: Path, target_dir: Path) -> Optional[tuple[Path, Path]]:
    final_path = unique_destination_path(target_dir / target.name)
    tmp_path = final_path.with_name(final_path.name + ".partial")
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except Exception as exc:
            log(f"删除旧转移临时文件失败 {tmp_path}: {exc}")
            return None
    return final_path, tmp_path


def copy_iso_to_partial(source: Path, tmp_path: Path, final_path: Path, total: int) -> bool:
    copied = 0
    last_update = 0.0
    with source.open("rb") as src, tmp_path.open("wb") as dst:
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
        return False
    return True


def finalize_cd2_transfer(target: Path, tmp_path: Path, final_path: Path, total: int) -> bool:
    tmp_path.replace(final_path)
    if final_path.stat().st_size != total:
        log(f"CloudDrive2最终文件大小校验失败: {final_path.stat().st_size} != {total}")
        return False
    update_active_progress("transfer", final_path, {"percent": 100.0, "current": total, "total": total, "verified": True})
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
    target_dir = resolve_cd2_target_dir(cfg)
    if not target_dir:
        return None
    if not target.exists():
        log(f"待转移ISO不存在: {target}")
        return None

    total = target.stat().st_size
    prepared = prepare_cd2_transfer_paths(target, target_dir)
    if not prepared:
        return None
    final_path, tmp_path = prepared

    log(f"开始转移到CloudDrive2挂载目录: {target} -> {final_path}")
    try:
        if not copy_iso_to_partial(target, tmp_path, final_path, total):
            return None
        if not finalize_cd2_transfer(target, tmp_path, final_path, total):
            return None
        maybe_refresh_cd2_after_transfer(cfg, final_path)
        return final_path
    except Exception as exc:
        log(f"CloudDrive2转移失败: {exc}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
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
            "started_at": task_started_at,
            "task_started_at": task_started_at,
            "pack_started_at": task_started_at,
            "status": "running",
            "progress": {"phase": "packing", "percent": 0, "current": 0, "total": source_size, "updated_at": now()},
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
            "started_at": task_started_at,
            "task_started_at": task_started_at,
            "pack_started_at": task_started_at,
            "pack_finished_at": item["pack_finished_at"],
            "transfer_started_at": transfer_started_at,
            "status": "transferring",
            "progress": {"phase": "transfer", "percent": 0, "current": 0, "total": target.stat().st_size if target.exists() else 0, "updated_at": now()},
        }
        save_state_locked()
    return transfer_started_at


def record_transfer_failure(source: Path, target: Path, source_size: int, transfer_finished_at: str) -> None:
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
        set_failure(item, "transfer_failed", "移动到 CD2 挂载目录失败")
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


def finish_process_item_success(source: Path, final_target: Path, source_size: int, cfg: Dict, transfer_started_at, transfer_finished_at, delete_source_error: Optional[str]) -> None:
    with lock:
        item = state["items"].setdefault(str(source), {})
        if cfg.get("cd2_transfer_enabled"):
            status = "transfer_done"
            if cfg.get("cd2_wait_upload_complete"):
                status = "waiting_cd2_upload"
        else:
            status = "done"
        finished_at = now()
        update = {
            "status": status,
            "target": str(final_target),
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
            update["error"] = "等待 CD2 上传完成"
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

    if not enough_space(output_dir, source_size, float(cfg["min_free_space_gb"])):
        log(f"空间不足，暂停处理 {source}")
        record_insufficient_space(source)
        return

    target = iso_path_for(source, output_dir)
    partial = target.with_suffix(target.suffix + ".partial")
    task_started_at = now()
    skip_message = start_process_item_task(source, target, source_size, task_started_at)
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
            record_pack_failure(source, error)
            return

        partial.replace(target)
        if not validate_iso(target):
            log(f"ISO 验证失败，保留源文件: {target}")
            record_verify_failure(source)
            return

        log(f"ISO 完成并验证通过: {target}")
        final_target = target
        if cfg.get("cd2_transfer_enabled"):
            transfer_started_at = mark_transfer_started(source, target, task_started_at)
            moved_target = transfer_iso_to_mount(target, cfg)
            transfer_finished_at = now()
            if not moved_target:
                record_transfer_failure(source, target, source_size, transfer_finished_at)
                return
            final_target = moved_target
        else:
            transfer_started_at = None
            transfer_finished_at = None

        delete_source_error = delete_source_if_configured(source, cfg)
        finish_process_item_success(source, final_target, source_size, cfg, transfer_started_at, transfer_finished_at, delete_source_error)
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


from page import PAGE, PAGE_LOGIN
def visible_iso_items(items: Dict) -> Dict:
    return {key: with_issue_guidance(item) for key, item in (items or {}).items() if item.get("pack_iso") is True}


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
    if request.path in {"/login", "/healthz", "/api/cd2/webhook"}:
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
    safe_cfg["cd2_path_aliases_text"] = cd2_path_aliases_to_text(cfg)
    safe_cfg["cd2_remote_source_dirs_text"] = cd2_remote_source_dirs_to_text(cfg)
    return render_template_string(PAGE, cfg=safe_cfg, state=snapshot, items=items, history_items=history_items, events=events, status_label=status_label, badge_class=badge_class, format_size=format_size, issue_text=task_issue_text)


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
    cfg["cd2_mount_root"] = request.form.get("cd2_mount_root", cfg.get("cd2_mount_root", "/CloudNAS")).strip()
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
    cfg["cd2_local_pull_dir"] = request.form.get("cd2_local_pull_dir", cfg.get("cd2_local_pull_dir", cfg["watch_dir"])).strip() or cfg["watch_dir"]
    cfg["cd2_remote_pull_dest_dir"] = normalize_path_text(request.form.get("cd2_remote_pull_dest_dir", cfg.get("cd2_remote_pull_dest_dir", "")))
    cfg["cd2_api_enabled"] = "cd2_api_enabled" in request.form
    cfg["cd2_auth_mode"] = cd2_auth_mode_from_cfg({"cd2_auth_mode": request.form.get("cd2_auth_mode", cfg.get("cd2_auth_mode", "api_token"))})
    cfg["cd2_api_addr"] = normalize_cd2_api_addr(request.form.get("cd2_api_addr", cfg.get("cd2_api_addr", "host.docker.internal:19798")))
    cfg["cd2_api_username"] = request.form.get("cd2_api_username", cfg.get("cd2_api_username", "")).strip()
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
    Path(cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg["output_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_local_pull_dir") or cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
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
    return jsonify(scan_cd2_remote_candidates(cfg, force_refresh=force_refresh))


@app.route("/api/cd2/pull", methods=["POST"])
def api_cd2_pull():
    cfg = load_config()
    payload = request.get_json(silent=True) if request.is_json else request.form
    source_path = normalize_path_text((payload or {}).get("path"))
    if not cfg.get("cd2_manual_pull_enabled"):
        return jsonify({"ok": False, "message": "CD2 手动拉取未启用"}), 400
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
    snapshot_items, snapshot_active, cd2_status = attach_cd2_uploads(cfg, snapshot.get("items", {}), snapshot.get("active"))
    snapshot["items"] = {key: apply_task_timings(item, snapshot_active if snapshot_active and snapshot_active.get("source") == key else None) for key, item in snapshot_items.items()}
    if snapshot_active:
        snapshot["active"] = apply_task_timings(dict(snapshot_active), snapshot_active)
    snapshot["cd2_status"] = cd2_status
    safe_cfg = sanitize_config(cfg)
    safe_cfg["cd2_path_aliases_text"] = cd2_path_aliases_to_text(cfg)
    safe_cfg["cd2_remote_source_dirs_text"] = cd2_remote_source_dirs_to_text(cfg)
    return jsonify({"config": safe_cfg, "state": snapshot, "cd2_status": cd2_status})


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
    Path(cfg.get("cd2_local_pull_dir") or cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_mount_root", "/CloudNAS")).expanduser().mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=15865, threaded=True)
