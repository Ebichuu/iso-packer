"""Offline state-machine regression tests from the independent logic audit."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class LogicStateAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "watch" / "Movie"
        self.source.mkdir(parents=True)
        (self.source / "source.bdmv").write_bytes(b"source-disc")
        self.output = self.root / "output"
        self.output.mkdir()
        self.local = self.output / "Movie.iso"
        self.local.write_bytes(b"audit-iso")
        self.target = self.root / "cloud" / "finished" / "Movie.iso"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.local.read_bytes())
        self.remote = "/115/finished/Movie.iso"
        self.cfg = copy.deepcopy(app.DEFAULT_CONFIG)
        self.cfg.update({
            "watch_dir": str(self.source.parent), "output_dir": str(self.output),
            "cd2_local_pull_dir": str(self.source.parent), "cd2_remote_pull_dest_dir": "/pull",
            "cd2_mount_root": str(self.root / "cloud"), "cd2_target_dir": str(self.target.parent),
            "cd2_path_aliases": [{"local": str(self.root / "cloud"), "remote": "/115"}],
            "cd2_api_enabled": True, "cd2_api_password": "offline-test-password",
            "cd2_wait_upload_complete": True, "delete_source_after_success": True,
        })
        self.state = {"items": {}, "active": None, "events": [], "cd2": {}}
        for name, value in {
            "state": self.state, "_worker_process_child": True, "_process_config": self.cfg,
            "save_state_locked": lambda: None, "log": lambda *_args: None,
        }.items():
            manager = patch.object(app, name, value)
            manager.start()
            self.addCleanup(manager.stop)
        app.pack_cancel_event.clear()
        self.addCleanup(app.pack_cancel_event.clear)

    def begin_upload(self):
        item = self.state["items"].setdefault(str(self.source), {})
        item.update({"status": "waiting_cd2_upload", "target": str(self.target),
                     "target_size": self.target.stat().st_size, "local_output_target": str(self.local),
                     "delete_source_pending": True, "pack_iso": True})
        app.begin_cd2_upload_claim(self.source, self.target, self.cfg, self.target.stat().st_size)
        self.push_upload(3, "Transfer")
        return item

    def push_upload(self, enum, status):
        upload = app.cd2_pb2.UploadFileInfo(
            key="audit-upload", destPath=self.remote, statusEnum=enum, status=status,
            size=self.target.stat().st_size, transferedBytes=self.target.stat().st_size,
        )
        message = app.cd2_pb2.CloudDrivePushMessage(
            messageType=app.cd2_pb2.CloudDrivePushMessage.UPLOADER_COUNT,
            transferTaskStatus=app.cd2_pb2.TransferTaskStatus(uploadFileStatusChanges=[upload]),
        )
        app.record_cd2_push_event(message, self.cfg)

    def check_upload(self, status_enum=None, status="Transfer"):
        uploads = {} if status_enum is None else {
            self.remote: {"key": "audit-upload", "path": self.remote, "status_enum": str(status_enum),
                          "status": status, "total": self.target.stat().st_size},
        }
        app.check_waiting_cd2_uploads(self.cfg, uploads, {
            "connected": True, "checked_at": app.now(), "upload_queue_complete": True,
        })

    def test_recheck_drops_previous_failed_push_then_accepts_fresh_completion(self):
        item = self.begin_upload()
        self.push_upload(9, "Error")
        self.check_upload()
        self.assertEqual(item["status"], "transfer_failed")
        result, code, mode = app.reset_task_for_recheck(str(self.source), self.cfg)
        self.assertEqual((result["ok"], code, mode), (True, 200, "upload"))
        self.check_upload(3)
        self.assertEqual(item["status"], "waiting_cd2_upload", "An old push error must not override the fresh API Transfer state")
        self.push_upload(5, "Finish")
        self.check_upload()
        self.assertEqual(item["status"], "transfer_done")
        self.assertFalse(self.source.exists())
        self.assertFalse(self.local.exists())

    def test_recheck_still_requires_fresh_explicit_finish(self):
        item = self.begin_upload()
        self.push_upload(9, "Error")
        self.check_upload()
        app.reset_task_for_recheck(str(self.source), self.cfg)
        self.check_upload()
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertTrue(self.source.exists())
        self.assertTrue(self.local.exists())
        self.check_upload(9, "Error")
        self.assertEqual(item["status"], "transfer_failed")

    def seed_pull(self, *, actual_target="/pull/Movie"):
        remote_source = "/remote/Movie"
        key = app.cd2_auto_pull_claim_key(remote_source, "/pull")
        claim = {"source_path": remote_source, "dest_dir": "/pull", "status": "submitted",
                 "mode": "manual", "local_path": str(self.source), "result_paths": [actual_target],
                 "created_at": app.now(), "updated_at": app.now()}
        self.state["cd2"]["auto_pull_claims"] = {key: claim}
        self.state["items"][str(self.source)] = {
            "status": "waiting_cd2_pull", "cd2_pull_source": remote_source,
            "cd2_pull_dest": "/pull", "cd2_pull_mode": "manual",
        }
        return key

    def reconcile_pull(self, tasks):
        return app.reconcile_cd2_auto_pull_claims(self.cfg, {
            "connected": True, "copy_tasks_complete": True, "copy_tasks": tasks,
        })

    def test_finished_child_copy_does_not_complete_running_whole_disc(self):
        key = self.seed_pull()
        summary = self.reconcile_pull([
            {"source": "/remote/Movie/BDMV", "target": "/pull/Movie/BDMV", "status": "3"},
            {"source": "/remote/Movie", "target": "/pull/Movie", "status": "2"},
        ])
        self.assertEqual(summary["completed"], 0)
        self.assertEqual(self.state["cd2"]["auto_pull_claims"][key]["status"], "submitted")
        self.assertNotIn("cd2_pull_finished_at", self.state["items"][str(self.source)])

    def test_same_source_other_target_cannot_complete_pull(self):
        key = self.seed_pull()
        self.reconcile_pull([{"source": "/remote/Movie", "target": "/pull/Unrelated/Movie", "status": "3"}])
        self.assertEqual(self.state["cd2"]["auto_pull_claims"][key]["status"], "submitted")
        self.assertNotIn("cd2_pull_finished_at", self.state["items"][str(self.source)])

    def test_actual_rename_result_is_the_only_allowed_child_destination(self):
        key = self.seed_pull(actual_target="/pull/Movie (1)")
        self.reconcile_pull([{"source": "/remote/Movie", "target": "/pull/Movie", "status": "3"}])
        self.assertEqual(self.state["cd2"]["auto_pull_claims"][key]["status"], "submitted")
        self.reconcile_pull([{"source": "/remote/Movie", "target": "/pull/Movie (1)", "status": "3"}])
        self.assertEqual(self.state["cd2"]["auto_pull_claims"][key]["status"], "completed")

    def test_failed_current_copy_wins_over_completed_copy_for_same_claim(self):
        key = self.seed_pull()
        self.reconcile_pull([
            {"source": "/remote/Movie", "target": "/pull/Movie", "status": "3"},
            {"source": "/remote/Movie", "target": "/pull/Movie", "status": "4", "error": "copy failed"},
        ])
        self.assertEqual(self.state["cd2"]["auto_pull_claims"][key]["status"], "failed")
        self.assertNotIn("cd2_pull_finished_at", self.state["items"][str(self.source)])

    def test_accepted_cancel_at_process_exit_never_finishes_or_deletes_source(self):
        self.local.unlink()
        cfg = dict(self.cfg, cd2_transfer_enabled=False, cd2_api_enabled=False)
        cancellations = []

        class JustFinishedProcess:
            returncode = 0

            def __init__(fake_self, command, **_kwargs):
                Path(command[command.index("-o") + 1]).write_bytes(b"finished-iso")

            def poll(fake_self):
                cancellations.append(app.cancel_active_pack(str(self.source)))
                return 0

            def wait(fake_self, **_kwargs):
                return 0

        with patch.object(app, "fetch_cd2_uploads", return_value=({}, {"connected": False})), \
             patch.object(app, "source_readiness_blocker", return_value=(None, "", None)), \
             patch.object(app, "should_pack_iso", return_value=(True, "test-disc")), \
             patch.object(app, "enough_space", return_value=True), \
             patch.object(app, "validate_iso", return_value=True), \
             patch.object(app.subprocess, "Popen", JustFinishedProcess):
            app.process_item(self.source, cfg)
        self.assertEqual(cancellations[0][1], 200)
        self.assertTrue(self.source.exists(), "An accepted cancellation must retain the source")
        self.assertEqual(self.state["items"][str(self.source)].get("failure_code"), "pack_cancelled")
        self.assertFalse(self.local.exists(), "A cancelled partial must not be promoted to a finished ISO")

    def test_cancel_after_atomic_finalize_boundary_is_rejected(self):
        self.state["items"][str(self.source)] = {"status": "running", "pack_iso": True}
        self.state["active"] = {"source": str(self.source), "progress": {"phase": "packing"}}
        partial = self.local.with_suffix(".iso.partial")

        class FinishedProcess:
            returncode = 0

            def poll(fake_self):
                return 0

            def wait(fake_self):
                return 0

        with patch.object(app.subprocess, "Popen", return_value=FinishedProcess()):
            result = app.run_iso(self.source, partial, 10)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.cancelled)
        self.assertEqual(app.cancel_active_pack(str(self.source))[1], 409)
        self.assertFalse(app.pack_cancel_event.is_set())


if __name__ == "__main__":
    unittest.main()
