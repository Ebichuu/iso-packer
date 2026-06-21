#!/usr/bin/env python3
"""Read-only CloudDrive2 API probe for iso-packer.

The probe reuses iso-packer's existing CD2 queue parsing logic. It only reads
upload/download/copy queues and optional path matches; it never creates CD2
copy tasks and never writes project state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


ENTRY_FIELDS = (
    "kind",
    "path",
    "source",
    "target",
    "status",
    "percent",
    "human",
    "summary",
    "error",
    "errors",
    "done",
)


def app_import_dir() -> Path:
    root = Path(__file__).resolve().parents[1]
    if (root / "app.py").is_file() and (root / "core.py").is_file():
        return root
    return root / "iso-packer"


def load_app_module(data_dir: Path):
    import_dir = app_import_dir()
    if not (import_dir / "app.py").is_file():
        raise RuntimeError(f"iso-packer app.py not found under {import_dir}")
    os.environ["DATA_DIR"] = str(data_dir)
    sys.path.insert(0, str(import_dir))
    import app as app_module  # type: ignore
    return app_module


def read_config(path: Path | None) -> Dict[str, Any]:
    if not path:
        return {}
    if not path.exists():
        raise RuntimeError(f"config file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("config file must contain a JSON object")
    return data


def compact_entry(entry: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not entry:
        return None
    result = {}
    for key in ENTRY_FIELDS:
        value = entry.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    return result


def ascii_text(value: Any) -> str:
    return str(value if value is not None else "-").encode("ascii", "backslashreplace").decode("ascii")


def limited_entries(entries: list[Dict[str, Any]], limit: int) -> list[Dict[str, Any]]:
    return [compact_entry(entry) or {} for entry in entries[:max(0, limit)]]


def build_config(app_module, file_config: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    cfg = app_module.DEFAULT_CONFIG.copy()
    cfg.update({key: value for key, value in file_config.items() if key in app_module.DEFAULT_CONFIG})
    cfg["cd2_api_enabled"] = True
    if args.addr:
        cfg["cd2_api_addr"] = args.addr
    if args.auth_mode:
        cfg["cd2_auth_mode"] = args.auth_mode
    if args.username:
        cfg["cd2_api_username"] = args.username
    if args.token:
        cfg["cd2_auth_mode"] = "api_token"
        cfg["cd2_api_password"] = args.token
    if args.password:
        cfg["cd2_auth_mode"] = "password"
        cfg["cd2_api_password"] = args.password
    if args.alias:
        cfg["cd2_path_aliases"] = app_module.parse_cd2_path_alias_lines("\n".join(args.alias))
    cfg["cd2_queue_poll_seconds"] = 1
    cfg["cd2_auth_mode"] = app_module.cd2_auth_mode_from_cfg(cfg)
    cfg["cd2_api_addr"] = app_module.normalize_cd2_api_addr(cfg.get("cd2_api_addr"))
    return cfg


def validate_config(cfg: Dict[str, Any]) -> None:
    if not cfg.get("cd2_api_addr"):
        raise RuntimeError("missing CD2 API address; pass --addr or --config")
    if not cfg.get("cd2_api_password"):
        raise RuntimeError("missing CD2 token/password; pass --token, --password, or --config")
    if cfg.get("cd2_auth_mode") == "password" and not cfg.get("cd2_api_username"):
        raise RuntimeError("password auth requires --username or config cd2_api_username")


def path_matches(app_module, upload_map: Dict[str, Any], status: Dict[str, Any], cfg: Dict[str, Any], paths: list[str]):
    matches = []
    for raw_path in paths:
        upload = app_module.find_upload_for_path(upload_map, raw_path, cfg)
        pending = app_module.cd2_pending_source_task(Path(raw_path), status, cfg)
        matches.append({
            "path": raw_path,
            "upload": compact_entry(upload),
            "pending_task": compact_entry(pending),
        })
    return matches


def make_payload(status: Dict[str, Any], matches: list[Dict[str, Any]], limit: int) -> Dict[str, Any]:
    return {
        "connected": bool(status.get("connected")),
        "available": bool(status.get("available")),
        "auth_mode": status.get("auth_mode"),
        "human": status.get("human"),
        "last_error": status.get("last_error"),
        "checked_at": status.get("checked_at"),
        "upload_count": int(status.get("upload_count") or 0),
        "download_count": int(status.get("download_count") or 0),
        "copy_task_count": int(status.get("copy_task_count") or 0),
        "uploads": limited_entries(status.get("uploads") or [], limit),
        "downloads": limited_entries(status.get("downloads") or [], limit),
        "copy_tasks": limited_entries(status.get("copy_tasks") or [], limit),
        "matches": matches,
    }


def print_payload(payload: Dict[str, Any]) -> None:
    print("CD2 readonly probe")
    print(f"connected: {payload['connected']}")
    print(f"available: {payload['available']}")
    print(f"auth_mode: {ascii_text(payload.get('auth_mode') or '-')}")
    print(f"summary: {ascii_text(payload.get('human') or '-')}")
    if payload.get("last_error"):
        print(f"last_error: {ascii_text(payload['last_error'])}")
    print(
        "counts: "
        f"uploads={payload['upload_count']} "
        f"downloads={payload['download_count']} "
        f"copy_tasks={payload['copy_task_count']}"
    )
    for name in ("uploads", "downloads", "copy_tasks"):
        entries = payload.get(name) or []
        if not entries:
            continue
        print(f"{name}:")
        for entry in entries:
            label = entry.get("human") or entry.get("summary") or entry.get("status") or "-"
            path = entry.get("path") or entry.get("source") or entry.get("target") or "-"
            print(f"  - {ascii_text(label)} | {ascii_text(path)}")
    for match in payload.get("matches") or []:
        print(f"match: {ascii_text(match['path'])}")
        print(f"  upload: {ascii_text((match.get('upload') or {}).get('human') or '-')}")
        print(f"  pending_task: {ascii_text((match.get('pending_task') or {}).get('human') or '-')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read CD2 API queues without creating tasks.")
    parser.add_argument("--config", type=Path, help="optional iso-packer config.json to read")
    parser.add_argument("--addr", help="CD2 API address, for example 127.0.0.1:19798")
    parser.add_argument("--auth-mode", choices=("api_token", "password"), help="CD2 auth mode")
    parser.add_argument("--username", help="CD2 username for password auth")
    parser.add_argument("--token", help="CD2 API token; never printed")
    parser.add_argument("--password", help="CD2 password for password auth; never printed")
    parser.add_argument("--alias", action="append", default=[], help="path alias, for example /CloudNAS/CloudDrive=/115")
    parser.add_argument("--path", action="append", default=[], help="optional local/remote path to match against queues")
    parser.add_argument("--limit", type=int, default=5, help="number of queue entries to print per queue")
    parser.add_argument("--json", action="store_true", help="print JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        file_config = read_config(args.config)
        with tempfile.TemporaryDirectory(prefix="iso-packer-cd2-probe-") as data_dir:
            app_module = load_app_module(Path(data_dir))
            cfg = build_config(app_module, file_config, args)
            validate_config(cfg)
            upload_map, status = app_module.fetch_cd2_uploads(cfg)
            matches = path_matches(app_module, upload_map, status, cfg, args.path)
            payload = make_payload(status, matches, args.limit)
            if args.json:
                print(json.dumps(payload, ensure_ascii=True, indent=2))
            else:
                print_payload(payload)
            if not status.get("available"):
                return 2
            if not status.get("connected") or status.get("last_error"):
                return 1
            return 0
    except Exception as exc:
        print(f"ERROR: {ascii_text(exc)}", file=sys.stderr)
        return 2
    finally:
        try:
            if "app_module" in locals():
                app_module.close_cd2_client()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
