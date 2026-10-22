"""Independent regressions for pause boundaries; never contact a CD2 server."""
from __future__ import annotations

import copy
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import app
import upload_control


class UploadPauseBoundaryAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = copy.deepcopy(app.DEFAULT_CONFIG)
        self.cfg.update({
            "enabled": True,
            "watch_dir": str(self.root / "watch"),
            "output_dir": str(self.root / "output"),
            "cd2_mount_root": str(self.root / "cloud"),
            "cd2_target_dir": str(self.root / "cloud" / "finished"),
            "cd2_api_enabled": True,
            "cd2_api_password": "test-account-a",
            "cd2_transfer_enabled": True,
            "cd2_wait_upload_complete": False,
            "cd2_upload_manual_paused": False,
            "cd2_upload_manual_until": "",
            "cd2_upload_schedule_enabled": False,
            "cd2_upload_pause_windows": [],
            "delete_source_after_success": True,
        })
        self.test_state = {"items": {}, "active": None, "events": [], "cd2": {}}
        for name, value in {
            "state": self.test_state,
            "_worker_process_child": True,
            "_process_config": self.cfg,
            "upload_transfer_context": threading.local(),
            "save_state_locked": lambda: None,
            "log": lambda *_args: None,
        }.items():
            manager = patch.object(app, name, value)
            manager.start()
            self.addCleanup(manager.stop)
        for key in ("watch_dir", "output_dir", "cd2_target_dir"):
            Path(self.cfg[key]).mkdir(parents=True, exist_ok=True)

    def seed_owned_upload(self):
        binding = app.upload_control_binding(self.cfg)
        upload = {"key": "owned-key", "path": "/115/Movie.iso", "status": "Pause", "status_enum": "4"}
        self.test_state["cd2"]["upload_control_owned"] = {
            binding: {"owned-key": {"path": upload["path"], "paused_at": "2026-10-21T23:00:00+08:00"}}
        }
        return upload

    def reconcile_with_queue(self, queue_function):
        with patch.object(app, "cd2_status_poll_disabled", return_value=False), \
             patch.object(app, "get_cd2_client", return_value=object()), \
             patch.object(app, "fetch_upload_control_queue", side_effect=queue_function), \
             patch.object(app, "call_upload_control_keys") as rpc:
            app.reconcile_upload_control(self.cfg)
        return [entry.args[1] for entry in rpc.call_args_list]

    def test_manual_pause_during_queue_fetch_prevents_owned_resume(self):
        upload = self.seed_owned_upload()

        def queue(_client):
            # A settings request publishes a new config while this RPC was waiting.
            fresh_cfg = copy.deepcopy(self.cfg)
            fresh_cfg["cd2_upload_manual_paused"] = True
            app._process_config = fresh_cfg
            return {upload["key"]: upload}

        self.assertNotIn("resume", self.reconcile_with_queue(queue))

    def test_window_start_during_queue_fetch_prevents_owned_resume(self):
        upload = self.seed_owned_upload()
        self.cfg.update(cd2_upload_schedule_enabled=True,
                        cd2_upload_pause_windows=[{"start": "23:30", "end": "00:45"}])
        clock = [datetime(2026, 10, 21, 23, 29, 59, tzinfo=upload_control.BEIJING)]

        def queue(_client):
            clock[0] = datetime(2026, 10, 21, 23, 30, tzinfo=upload_control.BEIJING)
            return {upload["key"]: upload}

        with patch.object(upload_control, "beijing_now", side_effect=lambda: clock[0]):
            self.assertNotIn("resume", self.reconcile_with_queue(queue))

    def test_confirmation_does_not_cross_account_or_clock_rollback(self):
        self.cfg["cd2_upload_manual_paused"] = True
        self.test_state["cd2"]["upload_control"] = {
            "binding": app.upload_control_binding(self.cfg),
            "remote_pause_confirmed": True,
            "checked_timestamp": 100,
        }
        with patch.object(app.time, "time", return_value=101):
            self.assertTrue(app.upload_control_payload(self.cfg)["remote_pause_confirmed"])
            new_cfg = copy.deepcopy(self.cfg)
            new_cfg["cd2_api_password"] = "test-account-b"
            self.assertNotEqual(app.upload_control_binding(self.cfg), app.upload_control_binding(new_cfg))
            self.assertFalse(app.upload_control_payload(new_cfg)["remote_pause_confirmed"])
        with patch.object(app.time, "time", return_value=99):
            self.assertFalse(app.upload_control_payload(self.cfg)["remote_pause_confirmed"])

    def test_long_manual_pause_ending_inside_daily_window_has_next_transition(self):
        self.cfg.update({
            "cd2_upload_schedule_enabled": True,
            "cd2_upload_pause_windows": [{"start": "23:30", "end": "00:45"}],
            "cd2_upload_manual_paused": True,
            "cd2_upload_manual_until": "2026-10-26T23:40:00+08:00",
        })
        status = upload_control.upload_control_status(
            self.cfg, current=datetime(2026, 10, 21, 12, tzinfo=upload_control.BEIJING)
        )
        self.assertTrue(status["effective_paused"])
        self.assertEqual(status["next_transition"], "2026-10-27T00:45:00+08:00")

    def seed_identical_outputs(self):
        source = Path(self.cfg["watch_dir"]) / "Movie"
        (source / "BDMV").mkdir(parents=True)
        (source / "BDMV" / "index.bdmv").write_bytes(b"disc-data")
        output = app.iso_path_for(source, Path(self.cfg["output_dir"]))
        output.write_bytes(b"identical-iso-placeholder")
        cloud = Path(self.cfg["cd2_target_dir"]) / output.name
        cloud.write_bytes(output.read_bytes())
        app.record_output_provenance(source, output)
        return source, output, cloud

    def pause_after_comparison(self, *_args):
        self.cfg["cd2_upload_manual_paused"] = True
        return True

    def test_process_deduplication_cannot_delete_local_files_after_pause(self):
        source, output, cloud = self.seed_identical_outputs()
        with patch.object(app, "fetch_cd2_uploads", return_value=({}, {"connected": True})), \
             patch.object(app, "check_waiting_cd2_uploads"), \
             patch.object(app, "source_readiness_blocker", return_value=(None, None, None)), \
             patch.object(app, "should_pack_iso", return_value=(True, "BDMV")), \
             patch.object(app, "classify_existing_output_iso", return_value=("complete", "valid")), \
             patch.object(app, "find_replacement_iso_candidates", return_value=[]), \
             patch.object(app, "resolve_cd2_target_dir", return_value=cloud.parent), \
             patch.object(app, "cd2_transfer_target_is_complete", side_effect=self.pause_after_comparison):
            app.process_item(source, self.cfg)
        self.assertTrue(output.exists(), "Entering a pause during comparison must retain the local ISO")
        self.assertTrue(source.exists(), "Entering a pause during comparison must retain the source directory")
        self.assertEqual(self.test_state["items"][str(source)]["status"], "waiting_upload_window")

    def test_transfer_deduplication_cannot_delete_local_iso_after_pause(self):
        _source, output, cloud = self.seed_identical_outputs()
        with patch.object(app, "validate_iso", return_value=True), \
             patch.object(app, "resolve_cd2_target_dir", return_value=cloud.parent), \
             patch.object(app, "cd2_transfer_target_is_complete", side_effect=self.pause_after_comparison):
            with self.assertRaises(app.UploadPaused):
                app.transfer_iso_to_mount(output, self.cfg)
        self.assertTrue(output.exists())

    def test_transfer_finalization_cannot_delete_local_iso_after_pause(self):
        _source, output, cloud = self.seed_identical_outputs()
        cloud.unlink()
        with patch.object(app, "validate_iso", return_value=True), \
             patch.object(app, "resolve_cd2_target_dir", return_value=cloud.parent), \
             patch.object(app, "copy_iso_to_mount", return_value=True), \
             patch.object(app, "finalize_cd2_transfer", side_effect=self.pause_after_comparison):
            with self.assertRaises(app.UploadPaused):
                app.transfer_iso_to_mount(output, self.cfg)
        self.assertTrue(output.exists())

    def test_browser_copy_cannot_return_success_to_move_after_pause(self):
        _source, output, cloud = self.seed_identical_outputs()
        cloud.unlink()
        with patch.object(app.shutil, "copystat", side_effect=self.pause_after_comparison):
            with self.assertRaises(app.UploadPaused):
                app.guarded_file_copy(output, cloud)
        self.assertTrue(output.exists(), "A caller must retain the move source after a pause")

    def test_restart_recovery_retains_local_iso_until_cd2_reports_finished(self):
        source, output, cloud = self.seed_identical_outputs()
        self.cfg["cd2_wait_upload_complete"] = True
        active = {"source": str(source), "target": str(cloud), "output_target": str(output)}
        with patch.object(app, "recovered_iso_is_usable", return_value=True), \
             patch.object(app, "validate_iso", return_value=True), \
             patch.object(app, "find_replacement_iso_candidates", return_value=[]), \
             patch.object(app, "resolve_cd2_target_dir", return_value=cloud.parent):
            self.assertTrue(app.finish_recovered_iso(source, cloud, self.cfg, active))
        item = self.test_state["items"][str(source)]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertTrue(source.exists())
        self.assertTrue(output.exists(), "Recovery must retain the local backup while cloud upload is unconfirmed")
        self.assertEqual(item.get("local_output_target"), str(output))

    def test_restart_same_name_different_iso_cannot_delete_source_or_local_output(self):
        source, output, cloud = self.seed_identical_outputs()
        cloud.write_bytes(b"x" * output.stat().st_size)
        active = {"source": str(source), "target": str(cloud), "output_target": str(output)}
        with patch.object(app, "recovered_iso_is_usable", return_value=True), \
             patch.object(app, "validate_iso", return_value=True), \
             patch.object(app, "find_replacement_iso_candidates", return_value=[]), \
             patch.object(app, "resolve_cd2_target_dir", return_value=cloud.parent):
            app.finish_recovered_iso(source, cloud, self.cfg, active)
        self.assertTrue(source.exists(), "A different cloud ISO must never authorize deleting this source")
        self.assertTrue(output.exists(), "Recovery must retain the actual local output on a same-name conflict")
        item = self.test_state["items"][str(source)]
        self.assertEqual(item.get("failure_code"), "target_exists")

    def test_startup_does_not_resume_deferred_work_before_recovery(self):
        recovered = [False]
        resumed_after_recovery = []
        source = Path(self.cfg["watch_dir"]) / "Movie"
        self.test_state["items"][str(source)] = {"status": "waiting_upload_window"}

        class EndFirstControllerTick(BaseException):
            pass

        class ImmediateControllerThread:
            def __init__(self, target, args=(), **_kwargs):
                self.target, self.args = target, args

            def start(self):
                if self.target in (app.upload_control_loop, app.resume_deferred_uploads):
                    try:
                        self.target(*self.args)
                    except EndFirstControllerTick:
                        pass

        with patch.object(app, "worker_started", False), \
             patch.object(app, "upload_control_started", False), \
             patch.object(app, "load_config", return_value=self.cfg), \
             patch.object(app, "set_app_secret"), patch.object(app, "load_state"), \
             patch.object(app, "env_flag_enabled", return_value=False), \
             patch.object(app, "cleanup_interrupted_output_partials"), \
             patch.object(app, "recover_interrupted_task", side_effect=lambda _cfg: recovered.__setitem__(0, True)), \
             patch.object(app, "start_cd2_push_listener"), \
             patch.object(app, "reconcile_upload_control", return_value={"effective_paused": False}), \
             patch.object(app, "process_item", side_effect=lambda *_args: resumed_after_recovery.append(recovered[0])), \
             patch.object(app.threading, "Thread", ImmediateControllerThread), \
             patch.object(app.time, "sleep", side_effect=EndFirstControllerTick):
            app.start_worker_once()
        self.assertTrue(recovered[0])
        self.assertTrue(all(resumed_after_recovery), "Deferred work must not become active before recovery has completed")


if __name__ == "__main__":
    unittest.main()
