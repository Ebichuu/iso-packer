"""Daily upload pause windows, always evaluated in current Beijing time."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
TIMEZONE_NAME = "Asia/Shanghai"


def beijing_now():
    return datetime.now(BEIJING)


def parse_pause_windows(value):
    if value is None or value == "":
        return []
    if isinstance(value, str):
        raw = []
        for line in value.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.fullmatch(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", line)
            if not match:
                raise ValueError("暂停窗口每行使用 HH:MM-HH:MM，例如 23:30-00:45")
            raw.append({"start": match[1], "end": match[2]})
    elif isinstance(value, list):
        raw = value
    else:
        raise ValueError("暂停窗口必须是列表或每行一个时间段")
    if len(raw) > 48:
        raise ValueError("每天最多设置 48 个暂停窗口")
    result = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("暂停窗口需要开始和结束时间")
        start, end = str(item.get("start") or ""), str(item.get("end") or "")
        for text in (start, end):
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
                raise ValueError("暂停时间应为 00:00 到 23:59 之间的 HH:MM")
        if start == end:
            raise ValueError("暂停窗口开始和结束时间不能相同")
        window = {"start": start, "end": end}
        if window not in result:
            result.append(window)
    return result


def pause_windows_text(windows):
    return "\n".join(f"{item['start']}-{item['end']}" for item in parse_pause_windows(windows))


def parse_manual_until(value, *, current=None, future_required=True):
    if not value:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", str(value).strip()):
        raise ValueError("恢复时间需要完整日期和时间，例如 2026-10-23T12:30")
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("恢复时间格式无效，请填写北京时间的日期和时间") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING)
    parsed = parsed.astimezone(BEIJING)
    if future_required and parsed <= (current or beijing_now()).astimezone(BEIJING):
        raise ValueError("恢复时间必须晚于当前北京时间")
    return parsed


def upload_control_status(cfg, *, current=None):
    current = (current or beijing_now()).astimezone(BEIJING)
    windows = parse_pause_windows(cfg.get("cd2_upload_pause_windows") or [])
    enabled = bool(cfg.get("cd2_upload_schedule_enabled"))
    until = parse_manual_until(cfg.get("cd2_upload_manual_until"), future_required=False)

    def scheduled(at):
        if not enabled:
            return False
        minute = at.hour * 60 + at.minute
        for window in windows:
            start = int(window["start"][:2]) * 60 + int(window["start"][3:])
            end = int(window["end"][:2]) * 60 + int(window["end"][3:])
            if (start <= minute < end) if start < end else (minute >= start or minute < end):
                return True
        return False

    def manually_paused(at):
        return bool(cfg.get("cd2_upload_manual_paused") and (until is None or at < until))

    manual, schedule = manually_paused(current), scheduled(current)
    effective = manual or schedule
    boundaries = []
    if until and until > current:
        boundaries.append(until)
    if enabled:
        days = {current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset) for offset in range(3)}
        if until and until > current:
            days.update(until.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset) for offset in range(3))
        for day in sorted(days):
            for window in windows:
                for field in ("start", "end"):
                    hours, minutes = map(int, window[field].split(":"))
                    boundary = day.replace(hour=hours, minute=minutes)
                    if boundary > current:
                        boundaries.append(boundary)
    next_transition = next((boundary for boundary in sorted(set(boundaries)) if (manually_paused(boundary) or scheduled(boundary)) != effective), None)
    reason = "manual_and_schedule" if manual and schedule else "manual" if manual else "schedule" if schedule else "none"
    return {
        "effective_paused": effective, "manual_paused": manual,
        "manual_until": until.isoformat(timespec="seconds") if until else None,
        "schedule_enabled": enabled, "windows": windows,
        "timezone": TIMEZONE_NAME, "reason": reason,
        "next_transition": next_transition.isoformat(timespec="seconds") if next_transition else None,
        "scope": "all_cd2_uploads",
    }
