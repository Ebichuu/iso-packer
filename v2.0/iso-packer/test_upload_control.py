from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app
from upload_control import BEIJING, parse_manual_until, parse_pause_windows, upload_control_status


class UploadScheduleTests(unittest.TestCase):
    def at(self, value):
        return datetime.fromisoformat(value).replace(tzinfo=BEIJING)

    def test_default_off_and_no_implicit_daily_windows(self):
        status = upload_control_status(app.DEFAULT_CONFIG, current=self.at("2026-10-22T00:00"))
        self.assertFalse(status["effective_paused"])
        self.assertEqual(status["windows"], [])

    def test_multiple_overlap_and_cross_midnight_windows(self):
        cfg = {"cd2_upload_schedule_enabled": True, "cd2_upload_pause_windows": parse_pause_windows("23:30-00:45\n00:30-01:15\n06:00-08:30")}
        status = upload_control_status(cfg, current=self.at("2026-10-22T23:45"))
        self.assertTrue(status["effective_paused"])
        self.assertEqual(status["next_transition"], "2026-10-23T01:15:00+08:00")
        self.assertFalse(upload_control_status(cfg, current=self.at("2026-10-23T01:15"))["effective_paused"])

    def test_utc_host_time_is_converted_to_beijing(self):
        cfg = {"cd2_upload_schedule_enabled": True, "cd2_upload_pause_windows": [{"start": "06:00", "end": "06:45"}]}
        status = upload_control_status(cfg, current=datetime(2026, 10, 21, 22, 10, tzinfo=timezone.utc))
        self.assertTrue(status["effective_paused"])
        self.assertEqual(status["next_transition"], "2026-10-22T06:45:00+08:00")

    def test_manual_until_and_schedule_use_union(self):
        cfg = {"cd2_upload_manual_paused": True, "cd2_upload_manual_until": "2026-10-22T07:30:00+08:00", "cd2_upload_schedule_enabled": True, "cd2_upload_pause_windows": [{"start": "07:00", "end": "08:00"}]}
        status = upload_control_status(cfg, current=self.at("2026-10-22T07:15"))
        self.assertEqual(status["reason"], "manual_and_schedule")
        self.assertEqual(status["next_transition"], "2026-10-22T08:00:00+08:00")
        status = upload_control_status(cfg, current=self.at("2026-10-22T07:45"))
        self.assertFalse(status["manual_paused"])
        self.assertTrue(status["effective_paused"])

    def test_manual_until_validation_and_naive_beijing(self):
        current = self.at("2026-10-22T12:00")
        self.assertEqual(parse_manual_until("2026-10-22T13:00", current=current).isoformat(), "2026-10-22T13:00:00+08:00")
        for invalid in ("bad", "2026-10-22", "2026-10-22T11:59", "2026-10-22T12:00"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_manual_until(invalid, current=current)

    def test_invalid_or_ambiguous_windows_are_rejected(self):
        for invalid in ("24:00-01:00", "11:60-12:30", "06:00-06:00", "6:00-07:00", [{"start": "00:00"}], [None]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_pause_windows(invalid)


class FakeUploadClient:
    def __init__(self):
        self.uploads = {
            "project": {"destPath": "/115/Movie.iso", "statusEnum": 3},
            "other": {"destPath": "/115/Document.zip", "statusEnum": 7},
            "user-paused": {"destPath": "/115/Paused.iso", "statusEnum": 4},
            "finished": {"destPath": "/115/Done.iso", "statusEnum": 5},
        }
        self.pause_calls = []
        self.resume_calls = []
        self.confirm_pause = True
        self.offline = False

    def get_upload_file_list(self, **kwargs):
        if self.offline:
            raise OSError("offline")
        return SimpleNamespace(totalCount=len(self.uploads), uploadFiles=[SimpleNamespace(key=key, status="", transferedBytes=0, size=100, **info) for key, info in self.uploads.items()])

    def pause_upload_files(self, keys):
        self.pause_calls.append(list(keys))
        if self.confirm_pause:
            for key in keys:
                self.uploads[key]["statusEnum"] = 4

    def resume_upload_files(self, keys):
        self.resume_calls.append(list(keys))
        for key in keys:
            self.uploads[key]["statusEnum"] = 3


class UploadControllerTests(unittest.TestCase):
    def setUp(self):
        self.original = {name: getattr(app, name) for name in ("state", "APP_DIR", "CONFIG_PATH", "STATE_PATH", "LOG_PATH", "_process_config", "_worker_process_child", "worker_started")}
        self.directory = tempfile.TemporaryDirectory(prefix="iso-upload-control-")
        self.root = Path(self.directory.name)
        app.APP_DIR = self.root
        app.CONFIG_PATH = self.root / "config.json"
        app.STATE_PATH = self.root / "state.json"
        app.LOG_PATH = self.root / "test.log"
        app.state = {"items": {}, "active": None, "events": [], "cd2": {}}
        app._worker_process_child = False
        self.cfg = copy.deepcopy(app.DEFAULT_CONFIG)
        self.cfg.update({"cd2_api_enabled": True, "cd2_upload_manual_paused": True, "cd2_mount_root": str(self.root / "mount"), "output_dir": str(self.root / "output"), "watch_dir": str(self.root / "watch"), "web_secret_key": "test-secret", "enabled": False})
        for directory in ("mount", "output", "watch"):
            (self.root / directory).mkdir()
        app._process_config = self.cfg
        self.client = FakeUploadClient()
        self.environment = patch.dict(os.environ, {"ISO_PACKER_DISABLE_CD2_STATUS_POLL": "0", "ISO_PACKER_DISABLE_AUTH": "1"})
        self.environment.start()
        self.mock_client = patch.object(app, "get_cd2_client", return_value=self.client)
        self.mock_client.start()

    def tearDown(self):
        self.mock_client.stop()
        self.environment.stop()
        for name, value in self.original.items():
            setattr(app, name, value)
        self.directory.cleanup()

    def test_pause_all_visible_upload_types_and_preserve_user_pauses(self):
        result = app.reconcile_upload_control(self.cfg)
        self.assertEqual(set(self.client.pause_calls[0]), {"project", "other"})
        self.assertTrue(result["remote_pause_confirmed"])
        self.assertEqual(result["owned_paused_count"], 2)
        self.cfg["cd2_upload_manual_paused"] = False
        result = app.reconcile_upload_control(self.cfg)
        self.assertEqual(set(self.client.resume_calls[0]), {"project", "other"})
        self.assertEqual(self.client.uploads["user-paused"]["statusEnum"], 4)
        self.assertEqual(result["owned_paused_count"], 0)

    def test_rpc_return_is_not_pause_confirmation(self):
        self.client.confirm_pause = False
        result = app.reconcile_upload_control(self.cfg)
        self.assertFalse(result["remote_pause_confirmed"])
        self.assertEqual(result["pending_upload_count"], 2)

    def test_new_uploads_are_paused_during_next_reconciliation(self):
        app.reconcile_upload_control(self.cfg)
        self.client.uploads["later"] = {"destPath": "/115/Later.mkv", "statusEnum": 3}
        app.reconcile_upload_control(self.cfg)
        self.assertEqual(self.client.pause_calls[-1], ["later"])

    def test_owned_pause_survives_state_reload(self):
        app.reconcile_upload_control(self.cfg)
        saved = json.loads(app.STATE_PATH.read_text(encoding="utf-8"))
        app.state = {"items": {}, "cd2": {}}
        app.load_state()
        self.assertEqual(app.state["cd2"]["upload_control_owned"], saved["cd2"]["upload_control_owned"])
        self.cfg["cd2_upload_manual_paused"] = False
        app.reconcile_upload_control(self.cfg)
        self.assertEqual(set(self.client.resume_calls[-1]), {"project", "other"})

    def test_missing_or_reused_key_never_resumes_an_unrelated_upload(self):
        app.reconcile_upload_control(self.cfg)
        self.client.uploads.pop("project")
        self.client.uploads["other"]["destPath"] = "/115/Unrelated.zip"
        self.cfg["cd2_upload_manual_paused"] = False
        result = app.reconcile_upload_control(self.cfg)
        self.assertEqual(self.client.resume_calls, [])
        self.assertEqual(result["owned_paused_count"], 1)
        self.assertIn("确认", result["last_error"])

    def test_disconnect_keeps_local_gate_and_never_claims_confirmed(self):
        self.client.offline = True
        result = app.reconcile_upload_control(self.cfg)
        self.assertTrue(result["effective_paused"])
        self.assertFalse(result["remote_pause_confirmed"])
        self.assertIn("offline", result["last_error"])

    def test_paused_transfer_preserves_iso_without_touching_mount(self):
        source = self.root / "output" / "Movie.iso"
        source.write_bytes(b"local-iso")
        with patch.object(app, "resolve_cd2_target_dir", side_effect=AssertionError("touched mount")):
            with self.assertRaises(app.UploadPaused):
                app.transfer_iso_to_mount(source, self.cfg)
        self.assertTrue(source.exists())

    def test_pause_between_copy_chunks_keeps_local_and_removes_partial_mount_file(self):
        source, target = self.root / "output" / "Movie.iso", self.root / "mount" / "Movie.iso"
        source.write_bytes(b"x" * 1024)
        self.cfg["cd2_upload_manual_paused"] = False
        calls = 0
        original = app.require_upload_allowed

        def check(cfg):
            nonlocal calls
            calls += 1
            if calls == 3:
                self.cfg["cd2_upload_manual_paused"] = True
            original(self.cfg)

        with patch.object(app, "require_upload_allowed", side_effect=check):
            with self.assertRaises(app.UploadPaused):
                app.copy_iso_to_mount(source, target, source.stat().st_size)
        self.assertTrue(source.exists())
        self.assertFalse(target.exists())

    def test_manual_control_persists_and_rejects_past_until(self):
        app.save_config(self.cfg)
        app.worker_started = True
        client = app.app.test_client()
        response = client.post("/api/cd2/upload-control", json={"action": "pause", "until": "2000-01-01T00:00"})
        self.assertEqual(response.status_code, 400)
        response = client.post("/api/cd2/upload-control", json={"action": "pause"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))["cd2_upload_manual_paused"])
        self.assertTrue(response.json["upload_control"]["remote_pause_confirmed"])


if __name__ == "__main__":
    unittest.main()
