"""Real spawn-process regressions; all IO stays in a temporary local directory."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from worker_runtime import ProcessWorker, WorkerBusy, WorkerLease, WorkerTimeout, WorkerUnavailable


def install_test_routes(application):
    """Runs inside spawned child; never creates a CloudDrive client."""
    from flask import jsonify

    application._test_hold = threading.Event()

    @application.app.route("/_test/hold", methods=["POST"])
    def hold_state_writer():
        with application.lock:
            application._test_hold.set()
            time.sleep(1.5)
        return jsonify({"ok": True, "pid": os.getpid()})

    @application.app.route("/_test/probe")
    def probe():
        return jsonify({"pid": os.getpid(), "held": application._test_hold.is_set()})

    @application.app.route("/_test/seed", methods=["POST"])
    def seed():
        source = str(application.APP_DIR / "watch" / "Movie")
        with application.lock:
            application.state["items"][source] = {"pack_iso": True, "status": "running"}
            application.state["active"] = {"source": source, "status": "running", "progress": {"phase": "packing"}}
            application.save_state_locked()
        return jsonify({"source": source})

    @application.app.route("/_test/spawn", methods=["POST"])
    def spawn_subprocess():
        proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
        with application._worker_subprocess_lock:
            application._worker_subprocesses.add(proc)
        return jsonify({"pid": proc.pid})

    @application.app.route("/_test/side-effect", methods=["POST"])
    def side_effect():
        (application.APP_DIR / "side-effect.txt").write_text("executed", encoding="utf-8")
        return jsonify({"ok": True})


def install_blocked_recovery(application):
    install_test_routes(application)
    application.cleanup_interrupted_output_partials = lambda cfg: time.sleep(1.5)


class ProcessWorkerTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory(prefix="iso-worker-test-")
        self.root = Path(self.data.name)
        for name in ("watch", "output", "mount"):
            (self.root / name).mkdir()
        cfg = dict(app.DEFAULT_CONFIG)
        cfg.update({
            "watch_dir": str(self.root / "watch"), "output_dir": str(self.root / "output"),
            "cd2_mount_root": str(self.root / "mount"), "cd2_target_dir": str(self.root / "mount"),
            "cd2_local_pull_dir": str(self.root / "watch"), "enabled": False,
            "cd2_api_enabled": False, "cd2_auto_pull_enabled": False,
            "web_secret_key": "test-worker-secret", "delete_source_after_success": False,
        })
        (self.root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.environment = patch.dict(os.environ, {
            "ISO_PACKER_DISABLE_WORKER": "1", "ISO_PACKER_DISABLE_CD2_PULL": "1",
            "ISO_PACKER_DISABLE_CD2_STATUS_POLL": "1", "ISO_PACKER_DISABLE_AUTH": "1",
        })
        self.environment.start()
        self.worker = ProcessWorker(self.root, initializer=install_test_routes)
        self.worker.start()
        self.addCleanup(self.data.cleanup)
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.worker.close)
        self.wait_until(lambda: self.worker.status()["startup_complete"], "worker failed to start")

    def wait_until(self, condition, message, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.03)
        self.fail(message)

    def call(self, path, method="GET", payload=None, headers=(), timeout=3):
        body = json.dumps(payload).encode() if payload is not None else b""
        if payload is not None:
            headers = [*headers, ("Content-Type", "application/json")]
        return self.worker.call(method=method, path=path, headers=headers, body=body, timeout=timeout)

    def test_worker_owns_http_commands_config_and_state(self):
        response = self.call("/_test/probe")
        self.assertNotEqual(json.loads(response["body"])["pid"], os.getpid())
        seeded = json.loads(self.call("/_test/seed", "POST")["body"])
        cancelled = self.call("/api/tasks/action", "POST", {"source": seeded["source"], "action": "cancel_pack"})
        self.assertEqual(cancelled["status"], 200)
        saved = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertIn("已请求取消", saved["items"][seeded["source"]]["error"])
        headers = [("Content-Type", "application/x-www-form-urlencoded")]
        response = self.worker.call(method="POST", path="/settings", headers=headers, body=b"stable_seconds=91", timeout=3)
        self.assertEqual(response["status"], 302)
        self.assertTrue(any(key == "Location" and value == "/settings?saved=1" for key, value in response["headers"]))
        saved_config = json.loads((self.root / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(saved_config["stable_seconds"], 91)
        self.assertEqual(self.worker.snapshot()["config"]["stable_seconds"], 91)
        pull = self.call("/api/cd2/pull", "POST", {"path": "/never-contact-cd2"})
        self.assertEqual(pull["status"], 400)
        self.assertIn("禁用", json.loads(pull["body"])["message"])

    def test_file_operation_runs_in_worker_and_publishes_progress(self):
        source = self.root / "watch" / "sample.txt"
        source.write_text("isolated-file-operation", encoding="utf-8")
        response = self.call("/api/file-actions", "POST", {
            "root": "watch", "action": "copy", "paths": [str(source)], "destination": "output",
        })
        self.assertEqual(response["status"], 200)
        task_id = json.loads(response["body"])["task_id"]
        self.wait_until(lambda: (self.root / "output" / "sample.txt").exists(), "file copy did not finish")
        self.wait_until(lambda: any(task["id"] == task_id and task["status"] == "done" for task in self.worker.snapshot()["file_operations"]["items"]), "file progress missing")
        status = self.call(f"/api/file-actions/{task_id}")
        self.assertEqual(json.loads(status["body"])["task"]["status"], "done")

    def test_stuck_state_writer_cannot_block_web_health_or_status(self):
        errors = []

        def hold():
            try:
                self.call("/_test/hold", "POST", timeout=0.4)
            except WorkerTimeout as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=hold)
        thread.start()
        self.wait_until(lambda: json.loads(self.call("/_test/probe")["body"])["held"], "blocked route not entered")
        # These sentinels prove the Web paths never re-enter disk/network/worker
        # requests, even while the child owns a blocked state lock.
        with patch.object(app, "_process_worker", self.worker), patch.object(app, "load_config", side_effect=AssertionError("Web read config")), patch.object(app, "fetch_cd2_uploads", side_effect=AssertionError("Web contacted CD2")):
            client = app.app.test_client()
            started = time.monotonic()
            health = client.get("/healthz")
            status = client.get("/api/status")
            elapsed = time.monotonic() - started
        self.assertEqual(health.status_code, 200)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json["worker"]["mode"], "process")
        self.assertLess(elapsed, 0.35)
        with patch.object(app, "_process_worker", self.worker):
            self.assertEqual(app.app.test_client().get("/workspace").status_code, 200)
        thread.join(timeout=2)
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.worker._pending, {})
        self.wait_until(lambda: (self.worker.status()["snapshot_age_seconds"] or 0) < 0.5, "snapshots did not recover", timeout=4)

    def test_cookie_session_round_trip_and_status_auth(self):
        with patch.dict(os.environ, {"ISO_PACKER_DISABLE_AUTH": "0"}), patch.object(app, "_process_worker", self.worker):
            self.worker.close()
            self.worker = ProcessWorker(self.root, initializer=install_test_routes)
            self.worker.start()
            self.addCleanup(self.worker.close)
            app._process_worker = self.worker
            self.wait_until(lambda: self.worker.status()["startup_complete"], "authenticated worker failed to start")
            client = app.app.test_client()
            response = client.post("/login", data={"web_password": "test-password", "web_password_confirm": "test-password"})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(any(header.startswith("session=") for header in response.headers.getlist("Set-Cookie")))
            self.assertEqual(client.get("/api/status").status_code, 200)
            self.assertEqual(app.app.test_client().get("/api/status").status_code, 401)
            self.assertEqual(client.get("/workspace").status_code, 200)
            self.assertEqual(client.post("/_test/side-effect").status_code, 200)
            self.assertEqual(app.app.test_client().post("/settings").status_code, 401)
            self.assertEqual(client.get("/logout").status_code, 302)
            self.assertEqual(client.get("/api/status").status_code, 401)

    def test_worker_exit_retains_status_and_rejects_commands(self):
        self.worker.process.terminate()
        self.worker.process.join(timeout=2)
        with self.assertRaises(WorkerUnavailable):
            self.call("/_test/probe")
        with patch.object(app, "_process_worker", self.worker):
            client = app.app.test_client()
            health = client.get("/healthz")
            self.assertEqual(health.status_code, 503)
            self.assertFalse(health.json["ok"])
            status = client.get("/api/status")
            self.assertEqual(status.status_code, 200)
            self.assertFalse(status.json["worker"]["alive"])
            self.assertEqual(client.post("/settings").status_code, 503)

    def test_request_capacity_and_snapshot_are_bounded(self):
        for _ in range(8):
            self.worker._slots.acquire()
        try:
            with self.assertRaises(WorkerBusy):
                self.call("/_test/probe")
        finally:
            for _ in range(8):
                self.worker._slots.release()
        snapshot = self.worker.snapshot()
        snapshot["config"]["stable_seconds"] = -1
        self.assertNotEqual(self.worker.snapshot()["config"]["stable_seconds"], -1)

    def test_status_upload_matching_never_stats_or_resolves_mounts(self):
        snapshot = self.worker.snapshot()
        snapshot["state"]["items"] = {"/watch/Movie": {"pack_iso": True, "status": "waiting_cd2_upload", "target": "/CloudNAS/CloudDrive/Movie.iso"}}
        snapshot["upload_map"] = {"/CloudNAS/CloudDrive/Movie.iso": {"path": "/CloudNAS/CloudDrive/Movie.iso", "status": "Uploading"}}
        with patch.object(app, "_process_worker", self.worker), patch.object(self.worker, "snapshot", return_value=snapshot), patch.object(app.Path, "resolve", side_effect=AssertionError("Web resolved FUSE path")), patch.object(app.os, "stat", side_effect=AssertionError("Web stat FUSE path")):
            response = app.app.test_client().get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("cd2_upload", response.json["state"]["items"]["/watch/Movie"])

    def test_normal_close_terminates_worker_subprocess(self):
        pid = json.loads(self.call("/_test/spawn", "POST")["body"])["pid"]
        self.worker.close()
        if os.name != "nt":
            self.wait_until(lambda: not Path(f"/proc/{pid}").exists() or ") Z " in Path(f"/proc/{pid}/stat").read_text(), "worker left a live subprocess")
        else:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                ctypes.windll.kernel32.CloseHandle(handle)
                self.assertNotEqual(code.value, 259, "worker left a live subprocess")

    def test_expired_command_is_not_executed(self):
        self.worker._commands.put({
            "protocol": 1, "id": "expired-test", "deadline": time.monotonic() - 1,
            "method": "POST", "path": "/_test/side-effect", "body": b"", "headers": [], "base_url": "http://localhost",
        })
        self.call("/_test/probe")
        self.assertFalse((self.root / "side-effect.txt").exists())

    def test_slow_startup_recovery_still_publishes_readonly_web_state(self):
        self.worker.close()
        with patch.dict(os.environ, {"ISO_PACKER_DISABLE_WORKER": "0"}):
            self.worker = ProcessWorker(self.root, initializer=install_blocked_recovery)
            self.worker.start()
            self.addCleanup(self.worker.close)
            self.wait_until(lambda: self.worker.status()["ready"], "initial recovery snapshot missing")
            self.assertFalse(self.worker.status()["startup_complete"])
            with patch.object(app, "_process_worker", self.worker):
                client = app.app.test_client()
                self.assertEqual(client.get("/api/status").status_code, 200)
                self.assertEqual(client.get("/workspace").status_code, 200)
                self.assertEqual(client.post("/settings").status_code, 503)
            self.wait_until(lambda: self.worker.status()["startup_complete"], "recovery did not finish")

    @unittest.skipIf(os.name == "nt", "Linux process-group crash cleanup")
    def test_linux_worker_crash_kills_its_subprocess_group(self):
        pid = json.loads(self.call("/_test/spawn", "POST")["body"])["pid"]
        self.worker.process.kill()
        self.worker.process.join(timeout=2)
        self.wait_until(lambda: not Path(f"/proc/{pid}").exists() or ") Z " in Path(f"/proc/{pid}/stat").read_text(), "crashed worker left a live subprocess")


class WorkerBoundaryTests(unittest.TestCase):
    def test_data_directory_has_only_one_worker_lease(self):
        with tempfile.TemporaryDirectory(prefix="iso-worker-lease-") as root:
            path = Path(root) / "worker.lock"
            lease = WorkerLease(path)
            try:
                with self.assertRaises(WorkerUnavailable):
                    WorkerLease(path)
            finally:
                lease.close()
            WorkerLease(path).close()

    def test_importing_app_does_not_create_or_modify_data(self):
        with tempfile.TemporaryDirectory(prefix="iso-worker-import-") as root:
            environment = dict(os.environ, DATA_DIR=root)
            result = subprocess.run([sys.executable, "-c", "import app"], cwd=Path(__file__).parent, env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(root).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
