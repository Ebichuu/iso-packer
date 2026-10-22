"""Exercise real ISO tools and the process worker with disposable synthetic data.

Run inside an isolated Linux container. No cloud service is contacted unless an
operator explicitly supplies --cloud-config. That mode copies configuration into
the disposable data directory and writes only to a new, unique acceptance folder
below its configured CD2 output directory; production state is never loaded.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size-mib", type=int, default=256)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--cloud-config", type=Path)
    args = parser.parse_args()
    if not 1 <= args.size_mib <= 4096 or not 10 <= args.timeout <= 1800:
        parser.error("size must be 1..4096 MiB; timeout must be 10..1800 seconds")
    for executable in ("genisoimage", "xorriso"):
        if shutil.which(executable) is None:
            parser.error(f"missing required executable: {executable}")

    os.environ.update({
        "ISO_PACKER_DISABLE_AUTH": "1", "ISO_PACKER_DISABLE_WORKER": "1",
        "ISO_PACKER_DISABLE_CD2_PULL": "1",
        "ISO_PACKER_DISABLE_CD2_STATUS_POLL": "0" if args.cloud_config else "1",
        "ISO_PACKER_ENABLE_CD2_PUSH": "1" if args.cloud_config else "0",
    })
    import app
    from worker_runtime import ProcessWorker

    run_root = Path(tempfile.mkdtemp(prefix="iso-packer-acceptance-"))
    source = run_root / "watch" / "Synthetic.Acceptance.2026"
    output_dir = run_root / "output"
    mount_dir = run_root / "mount"
    disc = source / "BDMV"
    for name in ("PLAYLIST", "CLIPINF", "STREAM"):
        (disc / name).mkdir(parents=True, exist_ok=True)
    for name in ("index.bdmv", "MovieObject.bdmv"):
        (disc / name).write_bytes(b"SYNTHETIC ACCEPTANCE FIXTURE\n")
    with (disc / "STREAM" / "00001.m2ts").open("wb") as stream:
        stream.write(b"SYNTHETIC ACCEPTANCE FIXTURE\n" + uuid.uuid4().hex.encode("ascii"))
        stream.truncate(args.size_mib * 1024 * 1024)
    output_dir.mkdir()
    mount_dir.mkdir()
    cfg = dict(app.DEFAULT_CONFIG)
    if args.cloud_config:
        cfg.update(json.loads(args.cloud_config.read_text(encoding="utf-8")))
        if not cfg.get("cd2_api_enabled"):
            raise SystemExit("cloud acceptance requires an enabled CD2 API")
        cloud_base = Path(str(cfg["cd2_target_dir"])).expanduser().resolve()
        cloud_mount = Path(str(cfg["cd2_mount_root"])).expanduser().resolve()
        if not app.path_in_root(cloud_base, cloud_mount):
            raise SystemExit("configured CD2 output is outside the mounted root")
        cloud_dir = cloud_base / (".iso-packer-acceptance-" + uuid.uuid4().hex)
        cfg["cd2_target_dir"] = str(cloud_dir)
    else:
        cfg.update({"cd2_api_enabled": False, "cd2_mount_root": str(mount_dir), "cd2_target_dir": str(mount_dir)})
        cloud_dir = None
    cfg.update({
        "enabled": False, "watch_dir": str(source.parent), "output_dir": str(output_dir),
        "cd2_local_pull_dir": str(source.parent), "delete_source_after_success": False,
        "cd2_auto_pull_enabled": False, "cd2_manual_pull_enabled": False,
        "cd2_remote_source_dirs": [], "cd2_remote_pull_dest_dir": "",
        "cd2_transfer_enabled": bool(args.cloud_config), "cd2_wait_upload_complete": True,
        "cd2_upload_schedule_enabled": False, "cd2_upload_pause_windows": [],
        "cd2_upload_manual_paused": False, "cd2_upload_manual_until": None,
        "web_password_hash": "", "web_secret_key": uuid.uuid4().hex,
        "min_free_space_gb": 0,
    })
    (run_root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    worker = ProcessWorker(run_root)
    previous_worker = app._process_worker
    app._process_worker = worker
    samples = {path: [] for path in ("/healthz", "/api/status", "/workspace")}
    started = time.monotonic()
    success = False
    stage = "worker_start"
    status = None
    failure_code = None
    http_status = None
    try:
        worker.start()
        deadline = started + args.timeout
        while not worker.status()["startup_complete"]:
            if time.monotonic() >= deadline or not worker.status()["alive"]:
                raise RuntimeError("worker did not start")
            time.sleep(0.05)
        if args.cloud_config:
            stage = "cloud_push_subscription"
            while True:
                snapshot = worker.snapshot() or {}
                push = (snapshot.get("state", {}).get("cd2") or {}).get("push") or {}
                if push.get("connected") and push.get("last_event"):
                    break
                if time.monotonic() >= deadline or not worker.status()["alive"] or push.get("supported") is False:
                    raise RuntimeError("CD2 did not confirm a live push subscription")
                time.sleep(0.05)
        client = app.app.test_client()
        stage = "manual_packaging"
        result = client.post("/rerun", data={"source": str(source)})
        http_status = result.status_code
        if result.status_code != 200:
            raise RuntimeError(f"manual packaging request returned HTTP {result.status_code}")
        last_recheck = 0.0
        stage = "wait_terminal_confirmation"
        while time.monotonic() < deadline:
            for path in samples:
                request_started = time.monotonic()
                response = client.get(path)
                samples[path].append(time.monotonic() - request_started)
                if response.status_code != 200:
                    raise RuntimeError(f"{path} returned HTTP {response.status_code}")
                if path == "/api/status":
                    item = (response.json.get("state", {}).get("items") or {}).get(str(source), {})
            status = item.get("status")
            if status in {"done", "transfer_done"}:
                break
            if status in {"failed", "verify_failed", "transfer_failed"}:
                failure_code = item.get("failure_code")
                raise RuntimeError("packaging failed: " + str(item.get("failure_code") or status))
            if args.cloud_config and status == "waiting_cd2_upload" and time.monotonic() - last_recheck >= 2:
                checked = client.post("/api/tasks/action", json={"source": str(source), "action": "recheck"})
                # A push can finish the task between the snapshot and POST.
                # Confirm its terminal state on the next iteration.
                if checked.status_code not in {200, 409}:
                    raise RuntimeError(f"upload recheck returned HTTP {checked.status_code}")
                last_recheck = time.monotonic()
            time.sleep(0.1)
        else:
            raise TimeoutError("terminal API confirmation was not received before the acceptance deadline")
        target = Path(item["target"])
        stage = "validate_iso_and_retention"
        validated = subprocess.run(["xorriso", "-indev", str(target), "-toc"], capture_output=True, timeout=30)
        if validated.returncode != 0 or not source.exists():
            raise RuntimeError("ISO validation or source retention failed")
        if any(output_dir.glob("*.partial")):
            raise RuntimeError("completed packaging left a partial file")
        report = {
            "ok": True, "python": sys.version.split()[0], "input_mib": args.size_mib,
            "iso_bytes": target.stat().st_size, "worker_pid": worker.process.pid,
            "parent_pid": os.getpid(), "terminal_status": status,
            "cloud_api_confirmed": status == "transfer_done" if args.cloud_config else None,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "max_response_ms": {path: round(max(values) * 1000, 2) for path, values in samples.items()},
            "request_count": sum(len(values) for values in samples.values()),
        }
        if args.cloud_config:
            snapshot = worker.snapshot() or {}
            persisted = snapshot.get("state", {}).get("items", {}).get(str(source), {})
            evidence = persisted.get("cd2_upload") or {}
            if str(evidence.get("status_enum")) != "5" or not evidence.get("key"):
                raise RuntimeError("cloud completion has no explicit matched Finish record")
            report["cloud_evidence"] = {
                "source": evidence.get("evidence_source", "queue"),
                "status_enum": evidence.get("status_enum"),
                "matched_task_key": bool(evidence.get("key")),
                "claim_generation": evidence.get("claim_generation"),
            }
        if any(max(values) > 1 for values in samples.values()):
            raise RuntimeError("Web response exceeded the one-second acceptance bound")
        # Remove only the fixture created by this invocation, after explicit
        # cloud completion. Unknown/pending upload state retains all fixtures.
        if cloud_dir:
            stage = "remove_confirmed_fixture"
            if target.parent != cloud_dir or target.name != "Synthetic.Acceptance.2026.iso":
                raise RuntimeError("unexpected cloud fixture path; refusing cleanup")
            target.unlink()
            cloud_dir.rmdir()
        print(json.dumps(report, ensure_ascii=False))
        success = True
        return 0
    except Exception as exc:
        # Upstream RPC errors can echo credentials. Keep the public report to
        # a safe stage/type and retain isolated data for operator inspection.
        safe_code = str(failure_code or "")
        if not safe_code.replace("_", "").isalnum():
            safe_code = None
        diagnostics = {}
        if cloud_dir:
            snapshot = worker.snapshot() or {}
            cloud_state = snapshot.get("state", {}).get("cd2") or {}
            claim = snapshot.get("state", {}).get("items", {}).get(str(source), {}).get("cd2_upload_claim") or {}
            diagnostics = {
                "claim_has_observed_key": bool(claim.get("upload_key")),
                "matched_push_updates": [
                    {"status_enum": upload.get("status_enum"), "bytes": upload.get("total"), "has_key": bool(upload.get("key"))}
                    for event in (cloud_state.get("push") or {}).get("recent_events", [])
                    for upload in event.get("upload_changes", [])
                    if cloud_dir.name in str(upload.get("path") or "")
                ],
            }
        print(json.dumps({"ok": False, "stage": stage, "error_type": type(exc).__name__, "http_status": http_status, "terminal_status": status, "failure_code": safe_code, "retained_data_dir": str(run_root), "cloud_fixture_dir": str(cloud_dir) if cloud_dir else None, **diagnostics}, ensure_ascii=False))
        return 1
    finally:
        worker.close()
        app._process_worker = previous_worker
        if success:
            shutil.rmtree(run_root)


if __name__ == "__main__":
    raise SystemExit(main())
