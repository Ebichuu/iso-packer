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

try:
    from clouddrive2_client import CloudDriveClient
except Exception:
    CloudDriveClient = None

# 数据目录：优先使用 /data（持久化挂载），否则使用当前目录
APP_DIR = Path(os.getenv("DATA_DIR", "/data"))
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
LOG_PATH = APP_DIR / "iso-packer.log"


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "watch_dir": "/watch",
    "output_dir": "/output",
    "delete_source_after_success": True,
    "scan_interval_seconds": 20,
    "stable_seconds": 180,
    "min_free_space_gb": 5,
    "enabled": True,
    "cd2_transfer_enabled": False,
    "cd2_mount_root": "/CloudNAS",
    "cd2_target_dir": "/CloudNAS/CloudDrive/00-未整理/00-mkiso",
    "cd2_require_mount": True,
    "web_password_hash": "",
    "web_secret_key": "",
    "cd2_api_enabled": False,
    "cd2_api_addr": "http://host.docker.internal:19798",
    "cd2_api_username": "",
    "cd2_api_password": "",
    "cd2_queue_poll_seconds": 10,
}

PARTIAL_EXTENSIONS = {".part", ".tmp", ".download", ".crdownload", ".aria2", ".!qb"}
VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".vob", ".rmvb", ".3gp",
}
DISC_STRUCTURE_DIRS = {"bdmv", "video_ts"}

app = Flask(__name__)
lock = threading.RLock()
cd2_lock = threading.RLock()
cd2_client_cache = {"key": None, "client": None, "last_error": None, "checked_at": None, "upload_map": {}, "upload_status": None}
state = {"items": {}, "last_scan": None, "active": None, "events": [], "cd2": {}}
worker_started = False
last_log_prune = 0.0


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def seconds_between(start: Optional[str], end: Optional[str] = None) -> int:
    start_dt = parse_time(start)
    if not start_dt:
        return 0
    end_dt = parse_time(end) if end else datetime.now()
    if not end_dt:
        return 0
    return max(0, int((end_dt - start_dt).total_seconds()))


def format_duration(seconds: Optional[int]) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def duration_summary(timings: Dict) -> str:
    return (
        f"总 {format_duration(timings.get('total', 0))} / "
        f"封装 {format_duration(timings.get('pack', 0))} / "
        f"转移 {format_duration(timings.get('transfer', 0))}"
    )


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
        match = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
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
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitize_config(cfg: Dict) -> Dict:
    safe = dict(cfg or {})
    safe.pop("web_password_hash", None)
    safe.pop("web_secret_key", None)
    return safe


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
    return redirect(url_for("login", next=request.path or "/"))


def verify_login_password(cfg: Dict, password: str) -> bool:
    stored = (cfg or {}).get("web_password_hash") or ""
    return bool(stored and check_password_hash(stored, password or ""))


def update_password(cfg: Dict, password: str) -> None:
    cfg["web_password_hash"] = generate_password_hash(password)
    if not cfg.get("web_secret_key"):
        cfg["web_secret_key"] = secrets.token_urlsafe(32)
    save_config(cfg)
    set_app_secret(cfg)


def path_in_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def parse_int_form(name: str, fallback, minimum: Optional[int] = None) -> int:
    raw = request.form.get(name, fallback)
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是数字")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} 不能小于 {minimum}")
    return value


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "disc"


def safe_volume_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return cleaned or "DISC"


def status_label(status: str) -> str:
    labels = {
        "watching": "监控中",
        "receiving": "接收中",
        "waiting_stable": "等待稳定",
        "waiting_partial": "等待下载完成",
        "ready": "准备打包",
        "running": "\u6b63\u5728\u5c01\u88c5",
        "done": "已完成",
        "failed": "失败",
        "verify_failed": "验证失败",
        "transferring": "\u6b63\u5728\u79fb\u52a8\u5230 CD2",
        "transfer_done": "\u5df2\u79fb\u52a8\u5230 CD2",
        "transfer_failed": "转移失败",
        "removed": "源已移除",
    }
    return labels.get(status or "", status or "未知")




def badge_class(status: str) -> str:
    if status in {"done", "transfer_done"}:
        return "badge-green"
    if status in {"failed", "verify_failed", "transfer_failed"}:
        return "badge-red"
    if status in {"running", "transferring"}:
        return "badge-yellow"
    if status in {"skipped", "removed"}:
        return "badge-gray"
    return "badge-blue"


def format_size(value) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0
    gb = size / 1024**3
    if gb >= 0.01:
        return f"{gb:.2f} GB"
    mb = size / 1024**2
    if mb >= 0.01:
        return f"{mb:.2f} MB"
    kb = size / 1024
    if kb >= 0.01:
        return f"{kb:.2f} KB"
    return f"{int(size)} B"


def apply_task_timings(item: Dict, active: Optional[Dict] = None) -> Dict:
    source = dict(item or {})
    active = active or {}
    progress = active.get("progress") or {}
    phase = progress.get("phase")
    task_started_at = source.get("task_started_at") or active.get("task_started_at") or source.get("pack_started_at") or active.get("pack_started_at") or source.get("started_at") or active.get("started_at")
    task_finished_at = source.get("finished_at") or active.get("finished_at") or source.get("done_at") or active.get("done_at")
    pack_started_at = source.get("pack_started_at") or active.get("pack_started_at") or task_started_at
    pack_finished_at = source.get("pack_finished_at") or active.get("pack_finished_at")
    transfer_started_at = source.get("transfer_started_at") or active.get("transfer_started_at")
    transfer_finished_at = source.get("transfer_finished_at") or active.get("transfer_finished_at")
    pack_end = pack_finished_at or (now() if active and phase == "packing" else None)
    transfer_end = transfer_finished_at or (now() if active and phase == "transfer" else None)
    total_end = task_finished_at or (now() if active else None)
    durations = {
        "total": seconds_between(task_started_at, total_end),
        "pack": seconds_between(pack_started_at, pack_end),
        "transfer": seconds_between(transfer_started_at, transfer_end),
    }
    source["timings"] = {
        "started_at": task_started_at,
        "pack_started_at": pack_started_at,
        "pack_finished_at": pack_finished_at,
        "transfer_started_at": transfer_started_at,
        "transfer_finished_at": transfer_finished_at,
        "finished_at": task_finished_at,
        "duration": durations["total"],
        "seconds": durations["total"],
        "elapsed": durations["total"],
        "total_seconds": durations["total"],
        "human": duration_summary(durations),
        "duration_human": duration_summary(durations),
        "durations": durations,
        "summary": duration_summary(durations),
    }
    return source


def normalize_upload_path(path: str) -> str:
    return str(Path(str(path or "")).expanduser()).replace("\\", "/").rstrip("/")


def get_cd2_client(cfg: Dict):
    if not CloudDriveClient:
        return None
    if not cfg.get("cd2_api_enabled"):
        return None
    addr = str(cfg.get("cd2_api_addr") or "").strip()
    username = str(cfg.get("cd2_api_username") or "").strip()
    password = str(cfg.get("cd2_api_password") or "")
    if not addr or not username or not password:
        return None
    key = (addr, username, password)
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
            if not client.authenticate(username, password):
                client.close()
                cd2_client_cache.update({"key": None, "client": None, "last_error": "CD2 认证失败", "checked_at": now()})
                return None
        except Exception as exc:
            try:
                client.close()
            except Exception:
                pass
            cd2_client_cache.update({"key": None, "client": None, "last_error": str(exc), "checked_at": now()})
            return None
        cd2_client_cache.update({"key": key, "client": client, "last_error": None, "checked_at": now()})
        return client


def close_cd2_client() -> None:
    with cd2_lock:
        client = cd2_client_cache.get("client")
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        cd2_client_cache.update({"key": None, "client": None, "last_error": None, "checked_at": None, "upload_map": {}, "upload_status": None})


def extract_upload_status(upload) -> str:
    status = getattr(upload, "status", None)
    if status not in (None, ""):
        return str(status)
    enum_status = getattr(upload, "statusEnum", None)
    if enum_status not in (None, ""):
        return str(enum_status)
    return "unknown"


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
        "checked_at": cd2_client_cache.get("checked_at"),
        "last_error": cd2_client_cache.get("last_error"),
        "uploads": [],
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
        status["last_error"] = cd2_client_cache.get("last_error") or "CD2 API 未连接"
        status["human"] = status["last_error"]
        return {}, status
    try:
        result = client.get_upload_file_list(get_all=True)
    except Exception as exc:
        with cd2_lock:
            cd2_client_cache["last_error"] = str(exc)
            cd2_client_cache["checked_at"] = now()
            cd2_client_cache["upload_map"] = {}
            cd2_client_cache["upload_status"] = None
        status["checked_at"] = cd2_client_cache.get("checked_at")
        status["last_error"] = str(exc)
        status["human"] = str(exc)
        return {}, status

    upload_map = {}
    status.update({
        "connected": True,
        "checked_at": now(),
        "last_error": None,
        "upload_count": int(getattr(result, "totalCount", 0) or 0),
        "global_bytes_per_second": float(getattr(result, "globalBytesPerSecond", 0) or 0),
        "total_bytes": int(getattr(result, "totalBytes", 0) or 0),
        "finished_bytes": int(getattr(result, "finishedBytes", 0) or 0),
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
    status["human"] = f"{status['upload_count']} 项上传任务" if status["upload_count"] else "未发现上传任务"
    with cd2_lock:
        cd2_client_cache["checked_at"] = status["checked_at"]
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


def has_partial_files(path: Path) -> bool:
    if path.is_file():
        return path.suffix.lower() in PARTIAL_EXTENSIONS
    for root, _, files in os.walk(path):
        for filename in files:
            if Path(filename).suffix.lower() in PARTIAL_EXTENSIONS:
                return True
    return False


def has_disc_structure(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        children = list(path.iterdir())
    except FileNotFoundError:
        return False
    if any(child.is_dir() and child.name.lower() in DISC_STRUCTURE_DIRS for child in children):
        return True
    for child in children:
        if not child.is_dir():
            continue
        try:
            if any(grandchild.is_dir() and grandchild.name.lower() in DISC_STRUCTURE_DIRS for grandchild in child.iterdir()):
                return True
        except FileNotFoundError:
            continue
    return False


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


def get_candidates(watch_dir: Path):
    if not watch_dir.exists():
        watch_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(load_config()["output_dir"]).resolve()
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


def update_active_progress(phase: str, target: Path, percent: float, current: int, total: int, **extra) -> None:
    progress = {
        "phase": phase,
        "percent": max(0.0, min(100.0, float(percent or 0))),
        "current": int(current or 0),
        "total": int(total or 0),
        "updated_at": now(),
    }
    progress.update(extra)
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
                update_active_progress("packing", target, min(percent, 99.9), current, source_size)
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
    update_active_progress("packing", target, 100.0 if proc.returncode == 0 else min(current * 100 / max(source_size, 1), 99.9), current, source_size)
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
                    update_active_progress("transfer", final_path, min(percent, 99.9), copied, total)
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
        update_active_progress("transfer", final_path, 100.0, total, total, verified=True)
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
    if source_size <= 0:
        log(f"跳过 {source}: 无法读取大小或为空")
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
    with lock:
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
    log(f"开始生成 ISO: {source} -> {target}")

    if partial.exists():
        partial.unlink()
    result = run_iso(source, partial, source_size)
    if result.returncode != 0:
        log(f"生成失败 {source}: {result.stderr.strip()[-1000:]}")
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        with lock:
            state["active"] = None
            item = state["items"].setdefault(str(source), {})
            item["status"] = "failed"
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
        state["active"] = None
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
    stable_seconds = max(30, int(cfg.get("stable_seconds", 180)))
    current = set()
    with lock:
        state["last_scan"] = now()
        active = state.get("active")
        save_state_locked()
    if active:
        return

    for candidate in get_candidates(watch_dir):
        key = str(candidate.resolve())
        pack_iso, pack_reason = should_pack_iso(candidate)
        if not pack_iso:
            with lock:
                state.get("items", {}).pop(key, None)
                save_state_locked()
            continue
        current.add(key)
        size = size_of(candidate)
        if size < 0:
            continue
        partial = has_partial_files(candidate)
        with lock:
            item = state["items"].setdefault(key, {"first_seen": now(), "status": "watching"})
            item["pack_iso"] = True
            terminal_statuses = {"done", "transfer_done", "failed", "verify_failed", "transfer_failed"}
            active_statuses = {"running", "transferring"}
            if item.get("status") in terminal_statuses | active_statuses:
                item.setdefault("last_size", size)
                item["partial_files"] = partial
                save_state_locked()
                continue
            last_size = item.get("last_size")
            last_changed = item.get("last_changed", now())
            if last_size != size:
                item["last_size"] = size
                item["last_changed"] = now()
                item["status"] = "receiving"
                save_state_locked()
                continue
            item["last_size"] = size
            item["partial_files"] = partial
            elapsed = time.time() - time.mktime(time.strptime(last_changed, "%Y-%m-%d %H:%M:%S"))
            if partial:
                item["status"] = "waiting_partial"
            elif elapsed >= stable_seconds:
                item["status"] = "ready"
                save_state_locked()
            else:
                item["status"] = "waiting_stable"
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
        if target:
            try:
                Path(str(target) + ".partial").unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
        if source and Path(source).exists():
            item = state.setdefault("items", {}).setdefault(source, {})
            if item.get("status") not in {"done", "verify_failed"}:
                item["status"] = "waiting_stable"
                item["last_changed"] = now()
        state["events"] = state.get("events", [])[-199:] + [f"[{now()}] 检测到上次任务中断，已恢复等待重新扫描"]
        state["active"] = None
        save_state_locked()


def start_worker_once():
    global worker_started
    if not worker_started:
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
                return redirect(request.args.get("next") or url_for("index"))
        else:
            if verify_login_password(cfg, password):
                session["logged_in"] = True
                session["login_at"] = now()
                session["login_user"] = "admin"
                return redirect(request.args.get("next") or url_for("index"))
            error = "密码不正确"
    return render_template_string(
        PAGE_LOGIN,
        first_setup=not has_password,
        message=error,
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
    cfg["cd2_api_addr"] = request.form.get("cd2_api_addr", cfg.get("cd2_api_addr", "http://host.docker.internal:19798")).strip()
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
    Path(cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg["output_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_mount_root", "/CloudNAS")).expanduser().mkdir(parents=True, exist_ok=True)
    log("设置已保存")
    if request.form.get("scan"):
        threading.Thread(target=scan_once, args=(cfg,), daemon=True).start()
    return redirect(url_for("index"))



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
    if source_size <= 0:
        return jsonify({"ok": False, "message": "\u65e0\u6cd5\u8bfb\u53d6\u6e90\u5927\u5c0f\u6216\u6e90\u4e3a\u7a7a"}), 400
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
    raw_path = (request.args.get("path") or "/").strip() or "/"
    try:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path("/") / path
        path = path.resolve()
    except Exception as exc:
        return jsonify({"ok": False, "message": f"路径无效: {exc}"}), 400

    if not path.exists():
        return jsonify({"ok": False, "message": "目录不存在"}), 404
    if not path.is_dir():
        path = path.parent

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
        "parent": str(path.parent) if path.parent != path else None,
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
