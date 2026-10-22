"""Independent, offline checks for task-bound CD2 upload push evidence."""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class CD2PushEvidenceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "watch" / "Movie"
        self.source.mkdir(parents=True)
        (self.source / "source.bdmv").write_bytes(b"disc-data")
        self.local = self.root / "output" / "Movie.iso"
        self.local.parent.mkdir()
        self.local.write_bytes(b"test-iso-content")
        self.target = self.root / "cloud" / "finished" / self.local.name
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.local.read_bytes())
        self.remote = "/115/finished/Movie.iso"
        self.claim_counter = 0
        self.current_key = "unclaimed-upload"
        self.cfg = copy.deepcopy(app.DEFAULT_CONFIG)
        self.cfg.update({
            "watch_dir": str(self.source.parent),
            "output_dir": str(self.local.parent),
            "cd2_mount_root": str(self.root / "cloud"),
            "cd2_target_dir": str(self.target.parent),
            "cd2_api_enabled": True,
            "cd2_api_password": "fake-account-a",
            "cd2_path_aliases": [{"local": str(self.root / "cloud"), "remote": "/115"}],
            "cd2_wait_upload_complete": True,
            "delete_source_after_success": True,
        })
        self.test_state = {"items": {}, "active": None, "events": [], "cd2": {}}
        for name, value in {
            "state": self.test_state,
            "_worker_process_child": True,
            "_process_config": self.cfg,
            "save_state_locked": lambda: None,
            "log": lambda *_args: None,
        }.items():
            manager = patch.object(app, name, value)
            manager.start()
            self.addCleanup(manager.stop)

    def begin(self, *, status="waiting_cd2_upload", observe=True):
        self.claim_counter += 1
        self.current_key = f"upload-{self.claim_counter}"
        item = self.test_state["items"].setdefault(str(self.source), {})
        item.update({
            "status": "transferring", "target": str(self.target), "target_size": self.target.stat().st_size,
            "local_output_target": str(self.local), "delete_source_pending": True, "pack_iso": True,
        })
        app.begin_cd2_upload_claim(self.source, self.target, self.cfg, self.target.stat().st_size)
        if observe:
            self.push(self.upload(enum=3, status="Transfer"))
        item["status"] = status
        return item

    def upload(self, *, key=None, path=None, enum=5, status="Finish", size=None):
        return app.cd2_pb2.UploadFileInfo(
            key=key or self.current_key, destPath=path or self.remote, statusEnum=enum, status=status,
            size=self.target.stat().st_size if size is None else size,
            transferedBytes=self.target.stat().st_size,
        )

    def push(self, *uploads, cfg=None):
        message = app.cd2_pb2.CloudDrivePushMessage(
            messageType=app.cd2_pb2.CloudDrivePushMessage.UPLOADER_COUNT,
            transferTaskStatus=app.cd2_pb2.TransferTaskStatus(uploadFileStatusChanges=uploads),
        )
        app.record_cd2_push_event(message, self.cfg if cfg is None else cfg)

    def check(self, uploads=None, *, connected=True):
        app.check_waiting_cd2_uploads(
            self.cfg, uploads or {},
            {"connected": connected, "checked_at": "audit-check", "upload_queue_complete": True},
        )
        return self.test_state["items"][str(self.source)]

    def assert_retained(self):
        self.assertTrue(self.source.exists(), "Unconfirmed upload must retain its source")
        self.assertTrue(self.local.exists(), "Unconfirmed upload must retain its local ISO")

    def test_exact_aliased_finish_before_waiting_survives_queue_removal(self):
        item = self.begin(status="transferring")
        self.push(self.upload())
        self.assert_retained()
        item["status"] = "waiting_cd2_upload"
        self.assertEqual(self.check()["status"], "transfer_done")
        self.assertFalse(self.source.exists())
        self.assertFalse(self.local.exists())

    def test_missing_event_and_disconnection_do_not_infer_completion(self):
        self.begin()
        self.assertEqual(self.check(connected=False)["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_finish_as_first_frame_does_not_prove_current_upload_identity(self):
        self.begin(observe=False)
        self.push(self.upload())
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_queue_finish_as_first_frame_cannot_bypass_push_identity_guard(self):
        self.begin(observe=False)
        upload = {"key": self.current_key, "path": self.remote, "status_enum": "5", "status": "Finish",
                  "total": self.target.stat().st_size}
        self.assertEqual(self.check({self.remote: upload})["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_queue_finish_with_wrong_size_cannot_bypass_claim_validation(self):
        self.begin()
        upload = {"key": self.current_key, "path": self.remote, "status_enum": "5", "status": "Finish",
                  "total": self.target.stat().st_size + 1}
        self.assertEqual(self.check({self.remote: upload})["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_same_batch_nonterminal_then_finish_proves_current_upload(self):
        self.begin(observe=False)
        self.push(self.upload(enum=3, status="Transfer"), self.upload())
        self.assertEqual(self.check()["status"], "transfer_done")

    def test_new_finish_is_consumed_even_when_queue_snapshot_timestamp_is_unchanged(self):
        self.begin()
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.push(self.upload())
        self.assertEqual(self.check()["status"], "transfer_done")

    def test_non_iso_and_same_filename_in_other_directory_cannot_finish(self):
        for path in ("/115/finished/Movie.iso.partial", "/115/finished/Movie.iso..partial", "/115/other/Movie.iso"):
            with self.subTest(path=path):
                self.begin()
                self.push(self.upload(path=path))
                self.assertEqual(self.check()["status"], "waiting_cd2_upload")
                self.assert_retained()

    def test_size_mismatch_cannot_finish(self):
        self.begin()
        self.push(self.upload(size=self.target.stat().st_size + 1))
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_explicit_pause_or_unknown_enum_overrides_finish_text(self):
        for enum in (0, 4, 999):
            with self.subTest(enum=enum):
                self.begin()
                self.push(self.upload(enum=enum))
                self.assertEqual(self.check()["status"], "waiting_cd2_upload")
                self.assert_retained()

    def test_failure_in_same_batch_wins_in_either_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                self.begin()
                messages = [self.upload(), self.upload(enum=9, status="Error")]
                self.push(*(messages[::-1] if reverse else messages))
                item = self.check()
                self.assertEqual(item["status"], "transfer_failed")
                self.assertEqual(item.get("failure_code"), "cd2_upload_failed")
                self.assert_retained()

    def test_text_failure_overrides_finish_enum(self):
        self.begin()
        self.push(self.upload(enum=5, status="Error"))
        self.assertEqual(self.check()["status"], "transfer_failed")
        self.assert_retained()

    def test_current_queue_failure_wins_over_bound_finish_event(self):
        self.begin()
        self.push(self.upload())
        failed = {"key": self.current_key, "path": self.remote, "status_enum": "9", "status": "Error"}
        self.assertEqual(self.check({self.remote: failed})["status"], "transfer_failed")
        self.assert_retained()

    def test_event_from_another_api_binding_cannot_finish(self):
        self.begin()
        other_cfg = copy.deepcopy(self.cfg)
        other_cfg["cd2_api_password"] = "fake-account-b"
        self.push(self.upload(), cfg=other_cfg)
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_claim_for_another_source_cannot_authorize_cleanup(self):
        item = self.begin()
        item["cd2_upload_claim"]["source"] = str(self.source.parent / "AnotherMovie")
        self.push(self.upload())
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_retargeted_task_cannot_consume_the_previous_targets_finish(self):
        item = self.begin()
        item["target"] = str(self.target.parent / "AnotherMovie.iso")
        self.push(self.upload())
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_finish_received_before_claim_cannot_be_replayed_to_new_task(self):
        self.push(self.upload(key="old-upload"))
        self.begin()
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_replacing_claim_invalidates_its_old_finish(self):
        item = self.begin(observe=False)
        first_generation = item["cd2_upload_claim"]["generation"]
        self.push(self.upload(key="old-upload", enum=3, status="Transfer"))
        self.push(self.upload(key="old-upload"))
        item = self.begin()
        self.assertNotEqual(item["cd2_upload_claim"]["generation"], first_generation)
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_known_old_key_cannot_bind_delayed_finish_to_new_generation(self):
        self.begin(observe=False)
        self.push(self.upload(key="old-upload", enum=3, status="Transfer"))
        self.begin(observe=False)
        self.push(self.upload(key="old-upload"))
        self.assertEqual(self.check()["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_different_current_queue_key_blocks_old_finish(self):
        self.begin(observe=False)
        self.push(self.upload(key="old-upload", enum=3, status="Transfer"))
        self.push(self.upload(key="old-upload"))
        current = {"key": "new-upload", "path": self.remote, "status_enum": "3", "status": "Transfer"}
        self.assertEqual(self.check({self.remote: current})["status"], "waiting_cd2_upload")
        self.assert_retained()

    def test_changed_source_is_retained_after_an_old_upload_finishes(self):
        self.begin()
        (self.source / "new-generation.bdmv").write_bytes(b"new source data")
        self.push(self.upload())
        self.check()
        self.assert_retained()

    def test_replaced_local_iso_is_retained_after_an_old_upload_finishes(self):
        self.begin()
        old_stat = self.local.stat()
        self.local.write_bytes(b"x" * old_stat.st_size)
        os.utime(self.local, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 2_000_000_000))
        self.push(self.upload())
        self.check()
        self.assert_retained()

    def test_generation_changed_before_deferred_cleanup_cannot_delete_new_task(self):
        item = self.begin()
        self.push(self.upload())
        replaced = [False]

        def commit_new_generation():
            if not replaced[0] and item.get("status") == "transfer_done":
                replaced[0] = True
                # Reproduce a newly committed task between finishing the old
                # queue record and applying its deferred path-based cleanup.
                replacement = copy.deepcopy(item)
                replacement["status"] = "running"
                replacement["cd2_upload_claim"]["generation"] = "new-task-generation"
                self.test_state["items"][str(self.source)] = replacement

        with patch.object(app, "save_state_locked", side_effect=commit_new_generation):
            self.check()
        self.assertTrue(replaced[0])
        self.assertEqual(self.test_state["items"][str(self.source)]["status"], "running")
        self.assert_retained()


if __name__ == "__main__":
    unittest.main()
