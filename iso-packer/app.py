#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
LOG_PATH = APP_DIR / "iso-packer.log"

DEFAULT_CONFIG = {
    'watch_dir': '',
    'output_dir': '',
    'delete_source_after_success': False,
    'scan_interval_seconds': 20,
    'stable_seconds': 180,
    'min_free_space_gb': 5,
    'enabled': False,
    'upload_115_enabled': False,
    'upload_115_cookie': '',
    'upload_115_cookie_path': '',
    'upload_115_target_cid': '',
    'upload_115_fast_retries': 0,
    'upload_115_part_size_mb': 64,
    'upload_115_delete_local_iso_after_success': False,
    'upload_115_helper_python': '',
    'cd2_transfer_enabled': False,
    'cd2_mount_root': '',
    'cd2_target_dir': '',
    'cd2_require_mount': True,
}

PARTIAL_EXTENSIONS = {".part", ".tmp", ".download", ".crdownload", ".aria2", ".!qb"}
VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".vob", ".rmvb", ".3gp",
}
DISC_STRUCTURE_DIRS = {"bdmv", "video_ts"}

app = Flask(__name__)
lock = threading.RLock()
state = {"items": {}, "last_scan": None, "active": None, "events": []}
worker_started = False
last_log_prune = 0.0


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_config() -> Dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    cfg = DEFAULT_CONFIG.copy()
    cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    return cfg


def save_config(cfg: Dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


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
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


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
        "uploading": "\u6b63\u5728\u4e0a\u4f20",
        "upload_done": "115上传完成",
        "upload_failed": "115上传失败",
        "transferring": "\u6b63\u5728\u79fb\u52a8\u5230 CD2",
        "transfer_done": "\u5df2\u79fb\u52a8\u5230 CD2",
        "transfer_failed": "转移失败",
        "removed": "源已移除",
    }
    return labels.get(status or "", status or "未知")




def badge_class(status: str) -> str:
    if status in {"done", "upload_done", "transfer_done"}:
        return "badge-green"
    if status in {"failed", "verify_failed", "upload_failed", "transfer_failed"}:
        return "badge-red"
    if status in {"running", "uploading", "transferring"}:
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
        if phase == "uploading":
            active["upload_progress"] = {
                "percent": progress["percent"],
                "uploaded": progress["current"],
                "total": progress["total"],
                "updated_at": progress["updated_at"],
                **{k: v for k, v in extra.items() if k in {"verifying", "verified"}},
            }
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


def sanitize_115_result(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "无输出"
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return "无输出"
    last = lines[-1]
    try:
        data = json.loads(last)
    except Exception:
        return last[-1000:]
    if isinstance(data, dict):
        data.pop("cookie", None)
    return json.dumps(data, ensure_ascii=False)[:1200]


def update_upload_progress(target: Path, payload: Dict) -> None:
    percent = max(0.0, min(100.0, float(payload.get("percent") or 0)))
    uploaded = int(payload.get("uploaded") or 0)
    total = int(payload.get("total") or 0)
    update_active_progress("uploading", target, percent, uploaded, total)


def handle_115_event(target: Path, payload: Dict) -> Optional[Dict]:
    if payload.get("ok") is not None:
        return payload
    event = payload.get("event")
    if event == "progress":
        update_upload_progress(target, payload)
        return None
    if event == "fast_attempt":
        log(f"115秒传尝试 {payload.get('attempt')}/{payload.get('retries')}: {target}")
    elif event == "fast_result":
        response = payload.get("response") or {}
        log(f"115秒传结果 第{payload.get('attempt')}次: reuse={response.get('reuse')} status={response.get('status')}")
    elif event == "normal_start":
        log(f"115普通上传开始: {format_size(payload.get('size'))}, 分块 {format_size(payload.get('part_size'))}")
        update_upload_progress(target, {"percent": 0, "uploaded": 0, "total": int(payload.get("size") or 0)})
    elif event == "normal_init":
        response = payload.get("response") or {}
        log(f"115普通上传初始化: state={response.get('state')} errno={response.get('errno')} status={response.get('status')} data_keys={response.get('data_keys')}")
    elif event == "completing":
        with lock:
            active = state.get("active") or {}
            old = active.get("progress") or active.get("upload_progress") or {}
            percent = float(old.get("percent") or 100)
            current = int(old.get("current") or old.get("uploaded") or 0)
            total = int(old.get("total") or current)
            state["active"] = active
            save_state_locked()
        update_active_progress("uploading", target, percent, current, total, verifying=True)
        log("115上传完成，正在提交并确认完整性")
    return None


def upload_iso_to_115(target: Path, cfg: Dict) -> bool:
    if not cfg.get("upload_115_enabled"):
        return True
    cid = str(cfg.get("upload_115_target_cid") or "").strip()
    cookie = str(cfg.get("upload_115_cookie") or "").strip()
    cookie_path = str(cfg.get("upload_115_cookie_path") or "").strip()
    helper_python = Path(str(cfg.get("upload_115_helper_python") or DEFAULT_CONFIG["upload_115_helper_python"])).expanduser()
    helper_script = APP_DIR / "115_upload_helper.py"

    if not cid:
        log("115上传未配置目录 cid，跳过上传并标记失败")
        return False
    if not cookie and not cookie_path:
        log("115上传未配置 cookie 或 cookie 文件路径，跳过上传并标记失败")
        return False
    if not helper_python.exists():
        log(f"115上传 Python 环境不存在: {helper_python}")
        return False
    if not helper_script.exists():
        log(f"115上传 helper 不存在: {helper_script}")
        return False

    cmd = [
        str(helper_python),
        str(helper_script),
        "--file", str(target),
        "--cid", cid,
        "--retries", str(max(0, int(cfg.get("upload_115_fast_retries", 3)))),
        "--part-size-mb", str(max(10, int(cfg.get("upload_115_part_size_mb", 64)))),
    ]
    env = os.environ.copy()
    if cookie_path:
        cmd.extend(["--cookie-path", cookie_path])
    else:
        env["P115_COOKIE"] = cookie

    log(f"开始上传到115: {target} -> cid {cid}")
    final_payload = None
    output_lines = []
    proc = subprocess.Popen(
        cmd,
        cwd=str(APP_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        output_lines.append(line)
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        maybe_final = handle_115_event(target, payload)
        if maybe_final is not None:
            final_payload = maybe_final
    returncode = proc.wait()

    if final_payload is None:
        output = sanitize_115_result("\n".join(output_lines))
        log(f"115上传失败: {target}; {output}")
        return False
    output = json.dumps(final_payload, ensure_ascii=False)[:1200]
    if returncode == 0 and final_payload.get("ok"):
        method = final_payload.get("method") or "unknown"
        log(f"115上传成功并确认完整性: {target}; method={method}; {output}")
        with lock:
            active = state.get("active") or {}
            state["active"] = active
            save_state_locked()
        final_size = target.stat().st_size if target.exists() else 0
        update_active_progress("uploading", target, 100.0, final_size, final_size, verified=True)
        if cfg.get("upload_115_delete_local_iso_after_success"):
            try:
                target.unlink()
                log(f"115上传成功后已删除本地 ISO: {target}")
            except Exception as exc:
                log(f"删除本地 ISO 失败 {target}: {exc}")
        return True
    log(f"115上传失败: {target}; {output}")
    return False


def unique_destination_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.stem}-{suffix}{path.suffix}")


def resolve_cd2_target_dir(cfg: Dict) -> Optional[Path]:
    mount_root = Path(str(cfg.get("cd2_mount_root") or "/mnt/cd2")).expanduser()
    target_dir = Path(str(cfg.get("cd2_target_dir") or str(mount_root))).expanduser()
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
    with lock:
        state["active"] = {"source": str(source), "target": str(target), "started_at": now(), "status": "running", "progress": {"phase": "packing", "percent": 0, "current": 0, "total": source_size, "updated_at": now()}}
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
            item["last_changed"] = now()
            save_state_locked()
        return

    log(f"ISO 完成并验证通过: {target}")
    final_target = target
    if cfg.get("cd2_transfer_enabled"):
        with lock:
            state["active"] = {"source": str(source), "target": str(target), "started_at": now(), "status": "transferring", "progress": {"phase": "transfer", "percent": 0, "current": 0, "total": target.stat().st_size if target.exists() else 0, "updated_at": now()}}
            state["items"].setdefault(str(source), {})["status"] = "transferring"
            save_state_locked()
        moved_target = transfer_iso_to_mount(target, cfg)
        if not moved_target:
            with lock:
                item = state["items"].setdefault(str(source), {})
                item.update({"status": "transfer_failed", "target": str(target), "done_at": now(), "size": source_size})
                item["last_changed"] = now()
                state["active"] = None
                save_state_locked()
            return
        final_target = moved_target
    elif cfg.get("upload_115_enabled"):
        with lock:
            state["active"] = {"source": str(source), "target": str(target), "started_at": now(), "status": "uploading", "progress": {"phase": "uploading", "percent": 0, "current": 0, "total": target.stat().st_size if target.exists() else 0, "updated_at": now()}}
            state["items"].setdefault(str(source), {})["status"] = "uploading"
            save_state_locked()
        if not upload_iso_to_115(target, cfg):
            with lock:
                item = state["items"].setdefault(str(source), {})
                item.update({"status": "upload_failed", "target": str(target), "done_at": now(), "size": source_size})
                item["last_changed"] = now()
                state["active"] = None
                save_state_locked()
            return

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
        elif cfg.get("upload_115_enabled"):
            status = "upload_done"
        else:
            status = "done"
        item.update({"status": status, "target": str(final_target), "done_at": now(), "size": source_size})
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
            terminal_statuses = {"done", "upload_done", "transfer_done", "failed", "verify_failed", "upload_failed", "transfer_failed"}
            active_statuses = {"running", "uploading", "transferring"}
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
            if key not in current and item.get("status") not in {"done", "upload_done", "transfer_done", "failed", "verify_failed", "upload_failed", "transfer_failed"}:
                item["status"] = "removed"
        save_state_locked()


from page import PAGE
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
    progress = active.get("progress") or active.get("upload_progress") or {}
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
        load_state()
        recover_interrupted_task()
        t = threading.Thread(target=scanner_loop, daemon=True)
        t.start()
        worker_started = True


@app.before_request
def before_request():
    start_worker_once()


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


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
    return render_template_string(PAGE, cfg=cfg, state=snapshot, items=items, history_items=history_items, events=events, status_label=status_label, badge_class=badge_class, format_size=format_size)


@app.route("/settings", methods=["POST"])
def settings():
    cfg = load_config()
    cfg["watch_dir"] = request.form.get("watch_dir", cfg["watch_dir"]).strip()
    cfg["output_dir"] = request.form.get("output_dir", cfg["output_dir"]).strip()
    cfg["scan_interval_seconds"] = int(request.form.get("scan_interval_seconds", cfg["scan_interval_seconds"]))
    cfg["stable_seconds"] = int(request.form.get("stable_seconds", cfg["stable_seconds"]))
    cfg["min_free_space_gb"] = int(float(request.form.get("min_free_space_gb", cfg["min_free_space_gb"])))
    cfg["enabled"] = "enabled" in request.form
    cfg["delete_source_after_success"] = "delete_source_after_success" in request.form
    cfg["cd2_transfer_enabled"] = "cd2_transfer_enabled" in request.form
    cfg["cd2_require_mount"] = "cd2_require_mount" in request.form
    cfg["cd2_mount_root"] = request.form.get("cd2_mount_root", cfg.get("cd2_mount_root", "/mnt/cd2")).strip()
    cfg["cd2_target_dir"] = request.form.get("cd2_target_dir", cfg.get("cd2_target_dir", "/mnt/cd2")).strip()
    cfg["upload_115_enabled"] = False
    cfg["upload_115_delete_local_iso_after_success"] = False
    cfg["upload_115_target_cid"] = ""
    cfg["upload_115_cookie"] = ""
    cfg["upload_115_cookie_path"] = ""
    cfg["upload_115_fast_retries"] = 0
    cfg["upload_115_part_size_mb"] = 64
    cfg["upload_115_helper_python"] = cfg.get("upload_115_helper_python") or DEFAULT_CONFIG["upload_115_helper_python"]
    save_config(cfg)
    Path(cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg["output_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_mount_root", "/mnt/cd2")).expanduser().mkdir(parents=True, exist_ok=True)
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
    if cfg.get("upload_115_cookie"):
        cfg["upload_115_cookie"] = "***"
    with lock:
        snapshot = json.loads(json.dumps(state, ensure_ascii=False))
        snapshot["items"] = visible_iso_items(snapshot.get("items", {}))
    return jsonify({"config": cfg, "state": snapshot})


if __name__ == "__main__":
    start_worker_once()
    cfg = load_config()
    Path(cfg["watch_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg["output_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
    Path(cfg.get("cd2_mount_root", "/mnt/cd2")).expanduser().mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=15865, threaded=True)
