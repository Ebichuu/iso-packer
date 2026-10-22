"""Offline integration checks for CD2 upload push ownership and startup."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class ImmediateTimer:
    def __init__(self, _delay, callback):
        self.callback = callback

    def start(self):
        self.callback()

    def is_alive(self):
        return False


class CD2PushIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "watch" / "Movie"
        self.source.mkdir(parents=True)
        (self.source / "disc.bdmv").write_bytes(b"disc-source")
        self.local = self.root / "output" / "Movie.iso"
        self.local.parent.mkdir()
        self.local.write_bytes(b"placeholder-iso")
        self.cloud = self.root / "cloud"
        self.cloud.mkdir()
        self.target = self.cloud / self.local.name
        self.cfg = copy.deepcopy(app.DEFAULT_CONFIG)
        self.cfg.update({
            "enabled": True, "watch_dir": str(self.source.parent), "output_dir": str(self.local.parent),
            "cd2_local_pull_dir": str(self.source.parent),
            "cd2_mount_root": str(self.cloud), "cd2_target_dir": str(self.cloud),
            "cd2_require_mount": False, "cd2_transfer_enabled": True, "cd2_api_enabled": True,
            "cd2_wait_upload_complete": True, "delete_source_after_success": True,
            "cd2_upload_manual_paused": False, "cd2_upload_schedule_enabled": False,
        })
        self.data = {"items": {}, "active": None, "events": [], "cd2": {}}
        for name, value in {
            "state": self.data, "_process_config": self.cfg, "_worker_process_child": True,
            "worker_started": False, "save_state_locked": lambda: None, "log": lambda *_: None,
            "cd2_push_scan_timer": None, "cd2_push_listener": {"thread": None},
            "cd2_client_cache": {"upload_map": {}, "upload_status": None},
        }.items():
            manager = patch.object(app, name, value)
            manager.start()
            self.addCleanup(manager.stop)

    def push(self, enum, *, key="fixture-upload"):
        upload = app.cd2_pb2.UploadFileInfo(
            key=key, destPath=str(self.target), size=self.local.stat().st_size,
            statusEnum=enum, status="Finish" if enum == 5 else "Transfer",
        )
        message = app.cd2_pb2.CloudDrivePushMessage(
            messageType=1, transferTaskStatus=app.cd2_pb2.TransferTaskStatus(uploadFileStatusChanges=[upload]),
        )
        app.record_cd2_push_event(message, self.cfg)

    def test_claim_is_registered_before_copy_and_fast_finish_is_consumed_after_finalize(self):
        started = app.now()
        app.mark_transfer_started(self.source, self.local, started)

        def copy_with_push(source, target, total):
            claim = self.data["items"][str(self.source)]["cd2_upload_claim"]
            self.assertEqual(claim["expected_size"], total)
            target.write_bytes(source.read_bytes())
            self.push(3)
            self.push(5)
            self.assertTrue(self.local.exists())
            return True

        with patch.object(app, "validate_iso", return_value=True), patch.object(app, "copy_iso_to_mount", side_effect=copy_with_push), patch.object(app, "maybe_refresh_cd2_after_transfer"):
            result = app.transfer_iso_to_mount(self.local, self.cfg)
        self.assertEqual(result, self.target)
        app.finish_process_item_success(self.source, self.target, 11, self.cfg, started, app.now(), None, local_output_target=self.local)
        item = self.data["items"][str(self.source)]
        self.assertEqual(item["status"], "transfer_done")
        self.assertEqual(item["cd2_upload"]["evidence_source"], "push")
        self.assertEqual(item["cd2_upload"]["status_enum"], "5")
        self.assertFalse(self.local.exists())
        self.assertFalse(self.source.exists())

    def test_explicit_terminal_evidence_survives_state_json_round_trip(self):
        self.target.write_bytes(self.local.read_bytes())
        self.data["items"][str(self.source)] = {"status": "waiting_cd2_upload", "target": str(self.target)}
        app.begin_cd2_upload_claim(self.source, self.target, self.cfg, self.local.stat().st_size)
        self.push(3)
        self.push(5)
        app.state = json.loads(json.dumps(self.data))
        app.check_waiting_cd2_uploads(self.cfg, {}, {"connected": False})
        item = app.state["items"][str(self.source)]
        self.assertEqual(item["status"], "transfer_done")
        self.assertEqual(item["cd2_upload"]["claim_generation"], item["cd2_upload_claim"]["generation"])

    def test_unknown_enum_does_not_establish_an_observed_upload_key(self):
        self.data["items"][str(self.source)] = {"status": "waiting_cd2_upload", "target": str(self.target)}
        app.begin_cd2_upload_claim(self.source, self.target, self.cfg, self.local.stat().st_size)
        self.push(999)
        self.push(5)
        app.check_waiting_cd2_uploads(self.cfg, {}, {"connected": False})
        self.assertEqual(self.data["items"][str(self.source)]["status"], "waiting_cd2_upload")

    def test_file_push_does_not_bypass_preview_or_disabled_automatic_scanning(self):
        for preview, enabled in ((True, True), (False, False)):
            with self.subTest(preview=preview, enabled=enabled):
                self.cfg["enabled"] = enabled
                with patch.dict(os.environ, {"ISO_PACKER_DISABLE_WORKER": "1" if preview else "0"}), patch.object(app.threading, "Timer", ImmediateTimer), patch.object(app, "scan_once") as scan, patch.object(app, "refresh_cd2_directory") as refresh, patch.object(app, "recheck_waiting_cd2_uploads") as recheck:
                    app.schedule_cd2_push_recheck(self.cfg, {"type": "FILE_SYSTEM_CHANGE", "path": str(self.target)})
                scan.assert_not_called()
                refresh.assert_not_called()
                recheck.assert_called_once()

    def test_normal_startup_subscribes_after_state_load_and_before_recovery(self):
        order = []
        with patch.dict(os.environ, {"ISO_PACKER_DISABLE_WORKER": "0"}), patch.object(app, "load_config", return_value=self.cfg), patch.object(app, "load_state", side_effect=lambda: order.append("load")), patch.object(app, "start_upload_control_once"), patch.object(app, "start_cd2_push_listener", side_effect=lambda _cfg: order.append("subscribe")), patch.object(app, "cleanup_interrupted_output_partials"), patch.object(app, "recover_interrupted_task", side_effect=lambda _cfg: order.append("recover")), patch.object(app.threading, "Thread"):
            app.start_worker_once()
        self.assertEqual(order, ["load", "subscribe", "recover"])

    def test_preview_can_explicitly_subscribe_without_automatic_recovery(self):
        with patch.dict(os.environ, {"ISO_PACKER_DISABLE_WORKER": "1", "ISO_PACKER_ENABLE_CD2_PUSH": "1"}), patch.object(app, "load_config", return_value=self.cfg), patch.object(app, "load_state"), patch.object(app, "start_upload_control_once"), patch.object(app, "start_cd2_push_listener") as subscribe, patch.object(app, "recover_interrupted_task") as recover:
            app.start_worker_once()
        subscribe.assert_called_once_with(self.cfg)
        recover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
