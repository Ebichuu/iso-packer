"""Independent offline regressions for runtime and controller interleavings."""
from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from worker_runtime import ProcessWorker, WorkerLease, WorkerUnavailable


def install_orphan_fixture_routes(application):
    from flask import jsonify

    @application.app.route("/_test/orphan-tool", methods=["POST"])
    def spawn_fixture_tool():
        tool = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(120)"])
        with application._worker_subprocess_lock:
            application._worker_subprocesses.add(tool)
        return jsonify({"tool_pid": tool.pid})


def run_orphan_fixture_parent(data_dir):
    """A disposable Web-parent equivalent; this process is deliberately killed."""
    root = Path(data_dir)
    worker = ProcessWorker(root, initializer=install_orphan_fixture_routes)
    worker.start()
    deadline = time.monotonic() + 8
    while not worker.status()["startup_complete"]:
        if time.monotonic() >= deadline:
            raise RuntimeError("isolated orphan fixture worker did not become ready")
        time.sleep(0.02)
    response = worker.call(method="POST", path="/_test/orphan-tool", timeout=3)
    info = json.loads(response["body"])
    info["worker_pid"] = worker.process.pid
    (root / "orphan-ready.json").write_text(json.dumps(info), encoding="utf-8")
    time.sleep(120)


def fixture_process_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            result = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(result)) and result.value == 259)
        finally:
            kernel.CloseHandle(handle)
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.exists() and ") Z " in stat_path.read_text():
            return False
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, FileNotFoundError):
        return False


class ParentDeathAuditTests(unittest.TestCase):
    def test_killed_web_parent_does_not_leave_worker_tool_or_data_lease(self):
        with tempfile.TemporaryDirectory(prefix="iso-orphan-audit-") as temp:
            root = Path(temp)
            for name in ("watch", "output", "mount"):
                (root / name).mkdir()
            cfg = copy.deepcopy(app.DEFAULT_CONFIG)
            cfg.update({
                "watch_dir": str(root / "watch"), "output_dir": str(root / "output"),
                "cd2_mount_root": str(root / "mount"), "cd2_target_dir": str(root / "mount"),
                "cd2_local_pull_dir": str(root / "watch"), "cd2_api_enabled": False,
                "enabled": False, "web_secret_key": "disposable-orphan-fixture",
            })
            (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            env = dict(os.environ, ISO_PACKER_DISABLE_WORKER="1", ISO_PACKER_DISABLE_AUTH="1", ISO_PACKER_DISABLE_CD2_STATUS_POLL="1", ISO_PACKER_ENABLE_CD2_PUSH="0")
            helper = subprocess.Popen([sys.executable, "-c", "import sys;from test_logic_audit_runtime import run_orphan_fixture_parent;run_orphan_fixture_parent(sys.argv[1])", str(root)], cwd=Path(__file__).parent, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            info = {}
            try:
                ready = root / "orphan-ready.json"
                deadline = time.monotonic() + 10
                while not ready.exists() and helper.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), f"fixture startup failed: {helper.poll()}")
                info = json.loads(ready.read_text(encoding="utf-8"))
                helper.kill()
                helper.wait(timeout=3)
                deadline = time.monotonic() + 5
                lease = None
                while time.monotonic() < deadline:
                    if not any(fixture_process_alive(info[field]) for field in ("worker_pid", "tool_pid")):
                        try:
                            lease = WorkerLease(root / "worker.lock")
                        except WorkerUnavailable:
                            # On Linux the thread-group leader can be a zombie
                            # before its last killed thread closes shared FDs.
                            # Process state alone does not prove lease release.
                            pass
                        else:
                            lease.close()
                            break
                    time.sleep(0.03)
                self.assertFalse(fixture_process_alive(info["worker_pid"]), "orphan worker remained alive after its Web parent was killed")
                self.assertFalse(fixture_process_alive(info["tool_pid"]), "orphan packaging tool remained alive after its Web parent was killed")
                self.assertIsNotNone(lease, "data lease remained held after the parent, worker and tool exited")
            finally:
                if helper.poll() is None:
                    helper.kill()
                    helper.wait(timeout=3)
                for pid in info.values():
                    if isinstance(pid, int) and fixture_process_alive(pid):
                        try:
                            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
                        except ProcessLookupError:
                            pass


class RuntimeSnapshotAuditTests(unittest.TestCase):
    def test_response_and_background_snapshot_receivers_cannot_roll_back_config(self):
        old_comparison_entered = threading.Event()
        allow_old_comparison = threading.Event()

        class DelayedPreviousSnapshot(dict):
            def get(self, key, default=None):
                value = super().get(key, default)
                if key == "at" and threading.current_thread().name == "old-response":
                    old_comparison_entered.set()
                    if not allow_old_comparison.wait(2):
                        raise AssertionError("snapshot interleaving did not complete")
                return value

        worker = ProcessWorker.__new__(ProcessWorker)
        worker._snapshot_lock = threading.Lock()
        worker._snapshot = DelayedPreviousSnapshot(protocol=1, at=0, config={"cd2_upload_manual_paused": False})
        older = {"protocol": 1, "at": 1, "config": {"cd2_upload_manual_paused": False}}
        newer = {"protocol": 1, "at": 2, "config": {"cd2_upload_manual_paused": True}}
        errors = []

        def receive_old():
            try:
                worker._accept_snapshot(older)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=receive_old, name="old-response")
        newer_thread = threading.Thread(target=worker._accept_snapshot, args=(newer,), name="newer-background")
        thread.start()
        try:
            self.assertTrue(old_comparison_entered.wait(2), "response receiver did not reach comparison")
            newer_thread.start()
            newer_thread.join(0.05)
        finally:
            allow_old_comparison.set()
            thread.join(2)
            newer_thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(worker.snapshot()["at"], 2, "older HTTP response replaced a newer controller snapshot")
        self.assertTrue(worker.snapshot()["config"]["cd2_upload_manual_paused"])

    def test_clock_rollback_cannot_freeze_new_configuration_snapshots(self):
        worker = ProcessWorker.__new__(ProcessWorker)
        worker._snapshot_lock = threading.Lock()
        worker._snapshot = None
        worker._accept_snapshot({"protocol": 1, "revision": 1, "at": 200, "config": {"enabled": True}})
        worker._accept_snapshot({"protocol": 1, "revision": 2, "at": 100, "config": {"enabled": False}})
        self.assertFalse(worker.snapshot()["config"]["enabled"])
        worker._accept_snapshot({"protocol": 1, "revision": 1, "at": 300, "config": {"enabled": True}})
        self.assertFalse(worker.snapshot()["config"]["enabled"])


class UploadControllerInterleavingAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = str(self.root / "watch" / "Movie")
        self.target = "/115/finished/Movie.iso"
        self.cfg = copy.deepcopy(app.DEFAULT_CONFIG)
        self.cfg.update({
            "enabled": True, "cd2_api_enabled": True, "cd2_api_password": "offline-fixture",
            "cd2_upload_manual_paused": False, "cd2_upload_manual_until": "",
            "cd2_upload_schedule_enabled": False, "cd2_upload_pause_windows": [],
        })
        self.data = {"items": {}, "active": None, "events": [], "cd2": {}}
        for name, value in {
            "state": self.data, "_worker_process_child": True, "_process_config": self.cfg,
            "worker_started": True, "save_state_locked": lambda: None, "log": lambda *_: None,
        }.items():
            manager = patch.object(app, name, value)
            manager.start()
            self.addCleanup(manager.stop)

    def test_automatic_deferred_resume_rechecks_fresh_enabled_flag(self):
        stale = copy.deepcopy(self.cfg)
        app._process_config = dict(self.cfg, enabled=False)
        self.data["items"][self.source] = {"status": "waiting_upload_window", "target": self.target}
        with patch.object(app, "process_item") as process:
            app.resume_deferred_uploads(stale)
        process.assert_not_called()

    def test_pause_rechecks_latest_policy_and_binding_after_waiting_for_rpc_lock(self):
        for change in ("resume", "new-binding"):
            with self.subTest(change=change):
                self.cfg["cd2_upload_manual_paused"] = True
                app._process_config = self.cfg
                waiting = threading.Event()
                remote_lock = threading.RLock()

                class ObservableLock:
                    def __enter__(self):
                        waiting.set()
                        remote_lock.acquire()

                    def __exit__(self, *_args):
                        remote_lock.release()

                upload = {"key": "fixture-key", "path": self.target, "status": "Transfer", "status_enum": "3"}
                results = []

                def reconcile():
                    results.append(app.reconcile_upload_control(self.cfg))

                remote_lock.acquire()
                thread = threading.Thread(target=reconcile)
                with patch.object(app, "upload_control_rpc_lock", ObservableLock()), patch.object(app, "cd2_status_poll_disabled", return_value=False), patch.object(app, "get_cd2_client", return_value=object()), patch.object(app, "fetch_upload_control_queue", return_value={"fixture-key": upload}), patch.object(app, "call_upload_control_keys") as rpc:
                    thread.start()
                    try:
                        self.assertTrue(waiting.wait(2), "controller did not reach the occupied RPC lock")
                        app._process_config = dict(self.cfg, cd2_upload_manual_paused=False) if change == "resume" else dict(self.cfg, cd2_api_password="different-offline-binding")
                    finally:
                        remote_lock.release()
                        thread.join(2)
                    self.assertFalse(thread.is_alive())
                    rpc.assert_not_called()
                self.assertFalse(results[0].get("remote_pause_confirmed"))

    def test_manual_pause_takeover_during_reconcile_cannot_be_automatically_resumed(self):
        binding = app.upload_control_binding(self.cfg)
        self.data["items"][self.source] = {"status": "waiting_cd2_upload", "target": self.target}
        self.data["cd2"]["upload_control_owned"] = {
            binding: {"fixture-key": {"path": self.target, "paused_at": "2026-10-22T10:00:00+08:00"}}
        }
        upload = {"key": "fixture-key", "path": self.target, "status": "Pause", "status_enum": "4"}
        client = object()
        resume_calls = []
        manual_result = []

        def fetch_queue(_client):
            if not manual_result:
                # Interleave the real user-facing per-task pause while the
                # controller has already copied its durable ownership ledger.
                result, status = app.control_cd2_task(self.source, "pause_upload", self.cfg)
                manual_result.append((result, status))
                self.assertNotIn("fixture-key", self.data["cd2"]["upload_control_owned"][binding])
            return {"fixture-key": dict(upload)}

        def control_keys(_client, action, keys):
            if action == "resume":
                resume_calls.extend(keys)

        with patch.object(app, "cd2_status_poll_disabled", return_value=False), patch.object(app, "get_cd2_client", return_value=client), patch.object(app, "fetch_upload_control_queue", side_effect=fetch_queue), patch.object(app, "fetch_cd2_uploads", return_value=({self.target: upload}, {"connected": True, "upload_queue_complete": True})), patch.object(app, "cd2_control_task_with_api"), patch.object(app, "call_upload_control_keys", side_effect=control_keys):
            app.reconcile_upload_control(self.cfg)
        self.assertTrue(manual_result[0][0]["ok"])
        self.assertEqual(manual_result[0][1], 200)
        self.assertEqual(resume_calls, [], "controller resumed the task after the user took ownership of its pause")
        self.assertNotIn("fixture-key", self.data["cd2"]["upload_control_owned"][binding])

    def test_manual_pause_is_last_when_automatic_resume_rpc_is_already_in_flight(self):
        binding = app.upload_control_binding(self.cfg)
        self.data["items"][self.source] = {"status": "waiting_cd2_upload", "target": self.target}
        self.data["cd2"]["upload_control_owned"] = {binding: {"fixture-key": {"path": self.target, "token": "old-owner"}}}
        upload = {"key": "fixture-key", "path": self.target, "status": "Pause", "status_enum": "4"}
        resume_entered = threading.Event()
        finish_resume = threading.Event()
        manual_intent_saved = threading.Event()
        order = []
        errors = []
        result = []
        client = object()

        def save_state():
            user_pauses = self.data["cd2"].get("upload_control_user_pauses", {}).get(binding, {})
            if "fixture-key" in user_pauses:
                manual_intent_saved.set()

        def automatic_rpc(_client, action, keys):
            self.assertEqual(action, "resume")
            resume_entered.set()
            if not finish_resume.wait(2):
                raise AssertionError("manual pause did not publish its intent")
            order.append("resume")

        def controller():
            try:
                app.reconcile_upload_control(self.cfg)
            except BaseException as exc:
                errors.append(exc)

        def manual_pause():
            try:
                result.append(app.control_cd2_task(self.source, "pause_upload", self.cfg))
            except BaseException as exc:
                errors.append(exc)

        with patch.object(app, "save_state_locked", side_effect=save_state), patch.object(app, "cd2_status_poll_disabled", return_value=False), patch.object(app, "get_cd2_client", return_value=client), patch.object(app, "fetch_upload_control_queue", return_value={"fixture-key": upload}), patch.object(app, "fetch_cd2_uploads", return_value=({self.target: upload}, {"connected": True, "upload_queue_complete": True})), patch.object(app, "call_upload_control_keys", side_effect=automatic_rpc), patch.object(app, "cd2_control_task_with_api", side_effect=lambda *_: order.append("pause")):
            controller_thread = threading.Thread(target=controller)
            manual_thread = threading.Thread(target=manual_pause)
            controller_thread.start()
            try:
                self.assertTrue(resume_entered.wait(2))
                manual_thread.start()
                self.assertTrue(manual_intent_saved.wait(2), "slow RPC blocked persistence of the user's pause")
                self.assertNotIn("fixture-key", self.data["cd2"]["upload_control_owned"][binding])
            finally:
                finish_resume.set()
                controller_thread.join(2)
                if manual_thread.ident is not None:
                    manual_thread.join(2)
        self.assertFalse(controller_thread.is_alive())
        self.assertFalse(manual_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(order, ["resume", "pause"])
        self.assertTrue(result[0][0]["ok"])
        self.assertNotIn("fixture-key", self.data["cd2"]["upload_control_owned"][binding])

    def test_old_controller_snapshot_cannot_restore_user_owned_pause_after_readback(self):
        self.cfg["cd2_upload_manual_paused"] = True
        binding = app.upload_control_binding(self.cfg)
        self.data["items"][self.source] = {"status": "waiting_cd2_upload", "target": self.target}
        self.data["cd2"]["upload_control_owned"] = {binding: {"fixture-key": {"path": self.target, "token": "old-owner"}}}
        transferring = {"key": "fixture-key", "path": self.target, "status": "Transfer", "status_enum": "3"}
        paused = dict(transferring, status="Pause", status_enum="4")
        calls = []

        def queue(_client):
            calls.append("fetch")
            if len(calls) == 1:
                return {"fixture-key": transferring}
            result, status = app.control_cd2_task(self.source, "pause_upload", self.cfg)
            self.assertTrue(result["ok"])
            self.assertEqual(status, 200)
            return {"fixture-key": paused}

        with patch.object(app, "cd2_status_poll_disabled", return_value=False), patch.object(app, "get_cd2_client", return_value=object()), patch.object(app, "fetch_upload_control_queue", side_effect=queue), patch.object(app, "fetch_cd2_uploads", return_value=({self.target: paused}, {"connected": True, "upload_queue_complete": True})), patch.object(app, "call_upload_control_keys"), patch.object(app, "cd2_control_task_with_api"):
            app.reconcile_upload_control(self.cfg)
        self.assertNotIn("fixture-key", self.data["cd2"]["upload_control_owned"][binding])


if __name__ == "__main__":
    unittest.main()
