import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

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
    "cd2_api_addr": "host.docker.internal:19798",
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
TERMINAL_STATUSES = {"done", "transfer_done", "failed", "verify_failed", "transfer_failed"}


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


def sanitize_config(cfg: Dict) -> Dict:
    safe = dict(cfg or {})
    safe.pop("web_password_hash", None)
    safe.pop("web_secret_key", None)
    return safe


def safe_next_path(value: Optional[str]) -> str:
    path = str(value or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        return "/"
    return path


def path_in_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def normalize_cd2_api_addr(value: str) -> str:
    addr = str(value or "").strip()
    if not addr:
        return ""
    addr = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", addr)
    addr = addr.split("/", 1)[0].rstrip("/")
    return addr


def cd2_client_key_from_cfg(cfg: Dict):
    cfg = cfg or {}
    return (
        bool(cfg.get("cd2_api_enabled")),
        normalize_cd2_api_addr(cfg.get("cd2_api_addr")),
        str(cfg.get("cd2_api_username") or "").strip(),
        str(cfg.get("cd2_api_password") or ""),
    )


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
        "running": "正在封装",
        "done": "已完成",
        "failed": "失败",
        "verify_failed": "验证失败",
        "transferring": "正在移动到 CD2",
        "transfer_done": "已移动到 CD2",
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
    task_started_at = (
        source.get("task_started_at") or active.get("task_started_at")
        or source.get("pack_started_at") or active.get("pack_started_at")
        or source.get("started_at") or active.get("started_at")
    )
    task_finished_at = (
        source.get("finished_at") or active.get("finished_at")
        or source.get("done_at") or active.get("done_at")
    )
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
