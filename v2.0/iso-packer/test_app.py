from __future__ import annotations

import copy
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app


class FakePullClient:
    def __init__(self) -> None:
        self.copy_calls = []

    def get_sub_files(self, path: str, force_refresh: bool = False):
        return [
            SimpleNamespace(
                name="BDMV",
                fullPathName=f"{path.rstrip('/')}/BDMV",
                isDirectory=True,
            )
        ]

    def copy_file_safe(self, source_paths, dest_dir, **_kwargs):
        self.copy_calls.append((list(source_paths or []), dest_dir))
        return SimpleNamespace(
            success=True,
            errorMessage="",
            resultFilePaths=[f"{dest_dir.rstrip('/')}/{Path(source).name}" for source in source_paths],
        )


class RevisionRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_state = copy.deepcopy(app.state)
        self.state_dir = tempfile.TemporaryDirectory()
        self.original_paths = {
            name: getattr(app, name)
            for name in ("APP_DIR", "CONFIG_PATH", "STATE_PATH", "LOG_PATH")
        }
        self.original_cd2_cache = app.cd2_client_cache
        self.original_functions = {
            name: getattr(app, name)
            for name in (
                "save_state_locked",
                "get_cd2_client",
                "cd2_disc_type_for_remote_path",
                "fetch_cd2_uploads",
                "source_readiness_blocker",
                "should_pack_iso",
                "enough_space",
                "run_iso",
                "validate_iso",
                "transfer_iso_to_mount",
            )
        }
        test_data_dir = Path(self.state_dir.name)
        app.APP_DIR = test_data_dir
        app.CONFIG_PATH = test_data_dir / "config.json"
        app.STATE_PATH = test_data_dir / "state.json"
        app.LOG_PATH = test_data_dir / "iso-packer.log"
        app.state = {"items": {}, "last_scan": None, "active": None, "events": [], "cd2": {}}
        app.pack_cancel_event.clear()
        app.cd2_client_cache = {
            "key": None,
            "client": None,
            "auth_mode": "api_token",
            "last_error": None,
            "checked_at": None,
            "last_success_at": None,
            "upload_map": {},
            "upload_status": None,
        }
        app.save_state_locked = lambda: None
        os.environ.pop("ISO_PACKER_DISABLE_CD2_PULL", None)

    def tearDown(self) -> None:
        app.state = self.original_state
        for name, function in self.original_functions.items():
            setattr(app, name, function)
        for name, path in self.original_paths.items():
            setattr(app, name, path)
        app.cd2_client_cache = self.original_cd2_cache
        app.pack_cancel_event.clear()
        self.state_dir.cleanup()

    def test_release_identity_requires_explicit_version_and_site(self) -> None:
        cases = [
            {
                "name": "same film site v1",
                "value": "Mercy.2026.V1.2160p.BluRay@CHDBits",
                "version": 1,
                "status": "versioned",
                "site": "chdbits",
            },
            {
                "name": "same film site v2",
                "value": "Mercy.2026.V2.2160p.BluRay@CHDBits",
                "version": 2,
                "status": "versioned",
                "site": "chdbits",
            },
            {
                "name": "version before year v1",
                "value": "Mercy V1 2026 2160p BluRay@CHDBits",
                "version": 1,
                "status": "versioned",
                "site": "chdbits",
            },
            {
                "name": "version before year v2",
                "value": "Mercy V2 2026 2160p BluRay@CHDBits",
                "version": 2,
                "status": "versioned",
                "site": "chdbits",
            },
            {
                "name": "unversioned coexists",
                "value": "Mercy.2026.2160p.BluRay@CHDBits",
                "version": None,
                "status": "unversioned",
                "site": "chdbits",
            },
            {
                "name": "different site",
                "value": "Mercy.2026.V1.2160p.BluRay@OurBits",
                "version": 1,
                "status": "versioned",
                "site": "ourbits",
            },
            {
                "name": "zero version is ambiguous",
                "value": "Mercy.2026.V0.2160p.BluRay@CHDBits",
                "version": None,
                "status": "ambiguous",
                "site": "chdbits",
            },
            {
                "name": "conflicting versions are ambiguous",
                "value": "Mercy.2026.V1.V2.2160p.BluRay@CHDBits",
                "version": None,
                "status": "ambiguous",
                "site": "chdbits",
            },
            {
                "name": "unparseable version is ambiguous",
                "value": "Mercy.2026.Vfinal.2160p.BluRay@CHDBits",
                "version": None,
                "status": "ambiguous",
                "site": "chdbits",
            },
        ]
        identities = {}
        for case in cases:
            with self.subTest(case["name"]):
                identity = app.parse_release_identity(case["value"])
                identities[case["name"]] = identity
                self.assertEqual(identity["version"], case["version"])
                self.assertEqual(identity["version_status"], case["status"])
                self.assertEqual(identity["site_key"], case["site"])
        self.assertEqual(
            identities["same film site v1"]["identity_key"],
            identities["same film site v2"]["identity_key"],
        )
        self.assertEqual(
            identities["version before year v1"]["identity_key"],
            identities["version before year v2"]["identity_key"],
        )
        self.assertNotEqual(
            identities["same film site v1"]["identity_key"],
            identities["different site"]["identity_key"],
        )
        self.assertEqual(identities["unversioned coexists"]["identity_key"], identities["same film site v1"]["identity_key"])

    def test_failed_cd2_tasks_never_count_as_complete_at_100_percent(self) -> None:
        failed_copy = {
            "status": "4",
            "failed_files": 0,
            "total_files": 10,
            "done_files": 10,
            "total": 100,
            "current": 100,
            "percent": 100,
        }
        failed_download = {"status": "failed", "total": 100, "current": 100}
        completed_copy = {"status": "3", "total": 0, "current": 0}
        active_copy_at_full_progress = {"status": "2", "total": 100, "current": 100}

        self.assertFalse(app.is_copy_task_done(failed_copy))
        self.assertFalse(app.is_download_done(failed_download))
        self.assertTrue(app.is_copy_task_done(completed_copy))
        self.assertFalse(app.is_copy_task_done(active_copy_at_full_progress))

    def test_manual_pull_disappearing_from_queue_stays_pending(self) -> None:
        item = {
            "cd2_pull_source": "/remote/Movie",
            "cd2_pull_dest": "/mnt/watch",
            "cd2_pull_mode": "manual",
            "cd2_pull_created_at": app.now(),
        }
        pending = app.cd2_recorded_pull_pending(
            item,
            {"connected": True, "copy_tasks": [], "downloads": []},
        )

        self.assertIsNotNone(pending)
        self.assertFalse(item.get("cd2_pull_finished_at"))

    def test_upload_missing_from_api_stays_waiting(self) -> None:
        source = "/watch/Movie 2025"
        target = "/CloudNAS/CloudDrive/finished/Movie 2025.iso"
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "target": target,
            "pack_iso": True,
            "cd2_upload_seen_at": app.now(),
        }

        app.check_waiting_cd2_uploads(
            dict(app.DEFAULT_CONFIG),
            {},
            {"connected": True, "checked_at": app.now(), "human": "connected"},
        )

        item = app.state["items"][source]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertNotIn("done_at", item)
        self.assertIn("当前未返回对应任务", item["error"])

    def test_incomplete_cd2_task_queue_blocks_packaging(self) -> None:
        with patch.object(app, "disc_structure_ready", return_value=(True, "")):
            status, reason, pending = app.source_readiness_blocker(
                Path("/watch/Movie 2025"),
                1024,
                {
                    "connected": True,
                    "copy_tasks_complete": False,
                    "download_tasks_complete": True,
                },
                dict(app.DEFAULT_CONFIG),
            )

        self.assertEqual(status, "waiting_partial")
        self.assertIn("读取不完整", reason)
        self.assertIsNone(pending)

    def test_replacement_candidates_only_match_lower_version_same_site(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_dir = base / "output"
            cd2_dir = base / "cd2"
            output_dir.mkdir()
            cd2_dir.mkdir()
            names = {
                "old_output": "Mercy.2026.V1.2160p.BluRay@CHDBits.iso",
                "old_cd2": "Mercy.2026.V2.2160p.BluRay@CHDBits.iso",
                "different_site": "Mercy.2026.V1.2160p.BluRay@OurBits.iso",
                "unversioned": "Mercy.2026.2160p.BluRay@CHDBits.iso",
                "higher": "Mercy.2026.V4.2160p.BluRay@CHDBits.iso",
            }
            old_output = output_dir / names["old_output"]
            old_cd2 = cd2_dir / names["old_cd2"]
            old_output.write_bytes(b"old")
            old_cd2.write_bytes(b"old")
            (output_dir / names["different_site"]).write_bytes(b"other")
            (output_dir / names["unversioned"]).write_bytes(b"unversioned")
            (output_dir / names["higher"]).write_bytes(b"higher")

            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "output_dir": str(output_dir),
                "cd2_transfer_enabled": True,
                "cd2_target_dir": str(cd2_dir),
            })
            source = base / "Mercy.2026.V3.2160p.BluRay@CHDBits"
            target = output_dir / f"{source.name}.iso"
            candidates = app.find_replacement_iso_candidates(source, target, cfg)

            self.assertEqual({path.name for path in candidates}, {names["old_output"], names["old_cd2"]})

    def test_workspace_recovery_card_wraps_long_failure_content(self) -> None:
        template = Path(__file__).parent / "templates" / "workspace.html"
        markup = template.read_text(encoding="utf-8")
        for marker in (
            "<section class=\"min-w-0 rounded-2xl",
            "<div class=\"flex min-w-0 items-start",
            "min-w-0 flex-1 space-y-1",
            "[overflow-wrap:anywhere]",
            "max-w-[42%] shrink truncate",
        ):
            self.assertIn(marker, markup)

    def test_pack_failure_keeps_lower_version_iso(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_dir = base / "output"
            source = base / "Mercy.2026.V2.2160p.BluRay@CHDBits"
            (source / "BDMV").mkdir(parents=True)
            old_iso = output_dir / "Mercy.2026.V1.2160p.BluRay@CHDBits.iso"
            output_dir.mkdir()
            old_iso.write_bytes(b"old")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "output_dir": str(output_dir),
                "cd2_transfer_enabled": False,
                "delete_source_after_success": False,
            })

            app.fetch_cd2_uploads = lambda _cfg: ({}, {"connected": False})
            app.source_readiness_blocker = lambda *_args, **_kwargs: (None, None, None)
            app.should_pack_iso = lambda _source: (True, "ready")
            app.enough_space = lambda *_args: True
            app.run_iso = lambda *_args: SimpleNamespace(returncode=1, stderr="pack failed")
            app.process_item(source, cfg)

            self.assertTrue(old_iso.exists())
            self.assertEqual(app.state["items"][str(source)]["status"], "failed")

    def test_success_removes_lower_versions_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_dir = base / "output"
            source = base / "Mercy.2026.V2.2160p.BluRay@CHDBits"
            (source / "BDMV").mkdir(parents=True)
            output_dir.mkdir()
            old_iso = output_dir / "Mercy.2026.V1.2160p.BluRay@CHDBits.iso"
            old_iso.write_bytes(b"old")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "output_dir": str(output_dir),
                "cd2_transfer_enabled": False,
                "delete_source_after_success": False,
            })

            app.fetch_cd2_uploads = lambda _cfg: ({}, {"connected": False})
            app.source_readiness_blocker = lambda *_args, **_kwargs: (None, None, None)
            app.should_pack_iso = lambda _source: (True, "ready")
            app.enough_space = lambda *_args: True

            def fake_run_iso(_source, target, _source_size):
                target.write_bytes(b"new")
                return SimpleNamespace(returncode=0, stderr="")

            app.run_iso = fake_run_iso
            app.validate_iso = lambda _target: True
            app.process_item(source, cfg)

            new_iso = output_dir / f"{source.name}.iso"
            self.assertTrue(new_iso.exists())
            self.assertFalse(old_iso.exists())
            self.assertEqual(app.state["items"][str(source)]["replaced_iso_count"], 1)

    def test_valid_existing_output_iso_is_reused_and_transferred(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_dir = base / "output"
            cd2_dir = base / "cd2"
            source = base / "Mercy.2026.V2.2160p.BluRay@CHDBits"
            (source / "BDMV").mkdir(parents=True)
            output_dir.mkdir()
            target = output_dir / f"{source.name}.iso"
            target.write_bytes(b"valid-iso")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "output_dir": str(output_dir),
                "cd2_transfer_enabled": True,
                "cd2_wait_upload_complete": False,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
                "delete_source_after_success": False,
            })
            transfer_calls = []

            app.fetch_cd2_uploads = lambda _cfg: ({}, {"connected": False})
            app.source_readiness_blocker = lambda *_args, **_kwargs: (None, None, None)
            app.validate_iso = lambda _target: True
            app.enough_space = lambda *_args: (_ for _ in ()).throw(AssertionError("不应为复用 ISO 检查生成空间"))
            app.run_iso = lambda *_args: (_ for _ in ()).throw(AssertionError("不应重复封装"))

            def fake_transfer(path, _cfg):
                transfer_calls.append(path)
                return cd2_dir / path.name

            app.transfer_iso_to_mount = fake_transfer
            app.process_item(source, cfg)

            self.assertEqual(transfer_calls, [target.resolve()])
            self.assertEqual(app.state["items"][str(source)]["status"], "transfer_done")
            self.assertTrue(app.state["items"][str(source)]["iso_reused"])

    def test_valid_existing_output_iso_without_cd2_is_marked_done(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_dir = base / "output"
            source = base / "Mercy.2026.V2.2160p.BluRay@CHDBits"
            (source / "BDMV").mkdir(parents=True)
            output_dir.mkdir()
            target = output_dir / f"{source.name}.iso"
            target.write_bytes(b"valid-iso")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "output_dir": str(output_dir),
                "cd2_transfer_enabled": False,
                "delete_source_after_success": False,
            })

            app.fetch_cd2_uploads = lambda _cfg: ({}, {"connected": False})
            app.source_readiness_blocker = lambda *_args, **_kwargs: (None, None, None)
            app.validate_iso = lambda _target: True
            app.enough_space = lambda *_args: (_ for _ in ()).throw(AssertionError("不应为复用 ISO 检查生成空间"))
            app.run_iso = lambda *_args: (_ for _ in ()).throw(AssertionError("不应重复封装"))
            app.process_item(source, cfg)

            item = app.state["items"][str(source)]
            self.assertEqual(item["status"], "done")
            self.assertEqual(item["target"], str(target.resolve()))

    def test_existing_cd2_target_is_delivered_when_upload_is_known_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_dir = base / "output"
            cd2_dir = base / "cd2"
            source = base / "Mercy.2026.V2.2160p.BluRay@CHDBits"
            (source / "BDMV").mkdir(parents=True)
            output_dir.mkdir()
            cd2_dir.mkdir()
            target = output_dir / f"{source.name}.iso"
            existing_target = cd2_dir / target.name
            target.write_bytes(b"valid-iso")
            existing_target.write_bytes(target.read_bytes())
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "output_dir": str(output_dir),
                "cd2_transfer_enabled": True,
                "cd2_wait_upload_complete": True,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
                "delete_source_after_success": False,
            })
            upload = {
                "path": str(existing_target),
                "status": "completed",
                "current": len(b"valid-iso"),
                "total": len(b"valid-iso"),
                "percent": 100.0,
            }

            app.fetch_cd2_uploads = lambda _cfg: ({str(existing_target): upload}, {"connected": True})
            app.source_readiness_blocker = lambda *_args, **_kwargs: (None, None, None)
            app.validate_iso = lambda _target: True
            app.run_iso = lambda *_args: (_ for _ in ()).throw(AssertionError("不应重复封装"))
            app.transfer_iso_to_mount = lambda *_args: (_ for _ in ()).throw(AssertionError("不应重复转存"))
            app.process_item(source, cfg)

            item = app.state["items"][str(source)]
            self.assertEqual(item["status"], "transfer_done")
            self.assertEqual(item["target"], str(existing_target))
            self.assertFalse(target.exists())

    def test_invalid_existing_cd2_target_keeps_manual_conflict_protection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_dir = base / "output"
            cd2_dir = base / "cd2"
            source = base / "Mercy.2026.V2.2160p.BluRay@CHDBits"
            (source / "BDMV").mkdir(parents=True)
            output_dir.mkdir()
            cd2_dir.mkdir()
            target = output_dir / f"{source.name}.iso"
            existing_target = cd2_dir / target.name
            target.write_bytes(b"valid-iso")
            existing_target.write_bytes(b"not-the-same")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "output_dir": str(output_dir),
                "cd2_transfer_enabled": True,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
                "delete_source_after_success": False,
            })

            app.fetch_cd2_uploads = lambda _cfg: ({}, {"connected": False})
            app.source_readiness_blocker = lambda *_args, **_kwargs: (None, None, None)
            app.validate_iso = lambda candidate: candidate.name == target.name and candidate.parent == target.parent.resolve()
            app.run_iso = lambda *_args: (_ for _ in ()).throw(AssertionError("不应重复封装"))
            app.process_item(source, cfg)

            item = app.state["items"][str(source)]
            self.assertEqual(item["status"], "transfer_failed")
            self.assertEqual(item["failure_code"], "target_exists")
            self.assertTrue(target.exists())
            self.assertTrue(existing_target.exists())

    def test_transfer_reuses_complete_existing_cd2_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_dir = base / "output"
            cd2_dir = base / "cd2"
            output_dir.mkdir()
            cd2_dir.mkdir()
            target = output_dir / "Mercy.2026.V2.2160p.BluRay@CHDBits.iso"
            existing_target = cd2_dir / target.name
            target.write_bytes(b"valid-iso")
            existing_target.write_bytes(target.read_bytes())
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_transfer_enabled": True,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
            })

            app.validate_iso = lambda _target: True
            result = app.transfer_iso_to_mount(target, cfg)

            self.assertEqual(result, existing_target)
            self.assertTrue(target.exists())
            self.assertTrue(existing_target.exists())

    def test_transfer_writes_only_final_iso_name_to_cd2_mount(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            cd2_dir = base / "cd2"
            cd2_dir.mkdir()
            target = base / "Movie.2026.iso"
            target.write_bytes(b"valid-iso")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_transfer_enabled": True,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
            })

            app.validate_iso = lambda _target: True
            result = app.transfer_iso_to_mount(target, cfg)

            self.assertEqual(result, cd2_dir / target.name)
            self.assertEqual([path.name for path in cd2_dir.iterdir()], [target.name])
            self.assertTrue(target.exists())

    def test_transfer_removes_local_iso_when_upload_wait_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            cd2_dir = base / "cd2"
            cd2_dir.mkdir()
            target = base / "Movie.2026.iso"
            target.write_bytes(b"valid-iso")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_transfer_enabled": True,
                "cd2_wait_upload_complete": False,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
            })

            app.validate_iso = lambda _target: True
            result = app.transfer_iso_to_mount(target, cfg)

            self.assertEqual(result, cd2_dir / target.name)
            self.assertFalse(target.exists())
            self.assertEqual([path.name for path in cd2_dir.iterdir()], [target.name])

    def test_cd2_target_must_stay_under_mounted_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            mount_root = base / "CloudDrive"
            outside = base / "outside"
            mount_root.mkdir()
            outside.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_require_mount": True,
                "cd2_mount_root": str(mount_root),
                "cd2_target_dir": str(outside),
            })

            with patch.object(Path, "is_mount", return_value=True):
                self.assertIsNone(app.resolve_cd2_target_dir(cfg))

    def test_file_operation_destination_stays_in_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            watch_dir = base / "watch"
            output_dir = base / "output"
            mount_root = base / "CloudDrive"
            outside = base / "outside"
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "watch_dir": str(watch_dir),
                "output_dir": str(output_dir),
                "cd2_mount_root": str(mount_root),
            })

            self.assertEqual(
                app.resolve_file_operation_destination(cfg, str(watch_dir / "archive")),
                (watch_dir / "archive").resolve(),
            )
            with self.assertRaises(ValueError):
                app.resolve_file_operation_destination(cfg, str(outside))

    def test_iso_validation_timeout_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "Movie.iso"
            target.write_bytes(b"iso")
            with patch.object(app.subprocess, "run", side_effect=app.subprocess.TimeoutExpired("xorriso", 1)):
                self.assertFalse(app.validate_iso(target))

    def test_iso_packing_timeout_terminates_genisoimage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "Movie"
            source.mkdir()
            target = Path(temp_dir) / "Movie.iso.partial"

            class HangingProcess:
                returncode = None

                def poll(self):
                    return self.returncode

                def terminate(self):
                    self.returncode = -15

                def wait(self, timeout=None):
                    return self.returncode

            process = HangingProcess()
            with (
                patch.object(app.subprocess, "Popen", return_value=process),
                patch.object(app, "ISO_PACK_TIMEOUT_SECONDS", 1),
                patch.object(app, "ISO_PACK_STALL_SECONDS", 999),
                patch.object(app.time, "monotonic", side_effect=[0.0, 2.0]),
            ):
                result = app.run_iso(source, target, 100)

            self.assertEqual(result.returncode, -15)
            self.assertIn("超过", result.stderr)

    def test_deferred_cleanup_runs_after_cd2_upload_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            watch_dir = base / "watch"
            output_dir = base / "output"
            target_dir = base / "cd2"
            source = watch_dir / "Movie 2026"
            local_iso = output_dir / "Movie 2026.iso"
            remote_iso = target_dir / local_iso.name
            source.mkdir(parents=True)
            output_dir.mkdir()
            target_dir.mkdir()
            local_iso.write_bytes(b"local")
            remote_iso.write_bytes(b"remote")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "watch_dir": str(watch_dir),
                "output_dir": str(output_dir),
                "cd2_target_dir": str(target_dir),
                "cd2_wait_upload_complete": True,
                "delete_source_after_success": True,
            })
            app.state["items"][str(source)] = {
                "status": "waiting_cd2_upload",
                "target": str(remote_iso),
                "local_output_target": str(local_iso),
                "delete_source_pending": True,
                "pack_iso": True,
                "cd2_upload_wait_started_at": app.now(),
            }

            app.check_waiting_cd2_uploads(
                cfg,
                {str(remote_iso): {"path": str(remote_iso), "status": "5", "status_enum": "5"}},
                {"connected": True, "checked_at": app.now(), "upload_queue_complete": True},
            )

            item = app.state["items"][str(source)]
            self.assertEqual(item["status"], "transfer_done")
            self.assertFalse(local_iso.exists())
            self.assertFalse(source.exists())
            self.assertNotIn("delete_source_pending", item)

    def test_transfer_rejects_non_iso_source_without_touching_mount(self) -> None:
        for filename in ("Movie.2026.iso.partial", "Movie.2026.iso..partial", "Movie.2026.mkv"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp_dir:
                base = Path(temp_dir)
                cd2_dir = base / "cd2"
                cd2_dir.mkdir()
                target = base / filename
                target.write_bytes(b"not-an-iso")
                cfg = dict(app.DEFAULT_CONFIG)
                cfg.update({
                    "cd2_transfer_enabled": True,
                    "cd2_require_mount": False,
                    "cd2_target_dir": str(cd2_dir),
                })

                app.validate_iso = lambda _target: True
                result = app.transfer_iso_to_mount(target, cfg)

                self.assertIsNone(result)
                self.assertTrue(target.exists())
                self.assertEqual(list(cd2_dir.iterdir()), [])

    def test_transfer_accepts_uppercase_iso_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            cd2_dir = base / "cd2"
            cd2_dir.mkdir()
            target = base / "Movie.2026.ISO"
            target.write_bytes(b"valid-iso")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_transfer_enabled": True,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
            })

            app.validate_iso = lambda _target: True
            result = app.transfer_iso_to_mount(target, cfg)

            self.assertEqual(result, cd2_dir / target.name)
            self.assertTrue(result.exists())

    def test_transfer_rejects_iso_when_source_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            cd2_dir = base / "cd2"
            cd2_dir.mkdir()
            target = base / "Movie.2026.iso"
            target.write_bytes(b"not-an-iso")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_transfer_enabled": True,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
            })

            app.validate_iso = lambda _target: False
            result = app.transfer_iso_to_mount(target, cfg)

            self.assertIsNone(result)
            self.assertTrue(target.exists())
            self.assertEqual(list(cd2_dir.iterdir()), [])

    def test_transfer_removes_target_when_destination_iso_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            cd2_dir = base / "cd2"
            cd2_dir.mkdir()
            target = base / "Movie.2026.iso"
            target.write_bytes(b"valid-iso")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_transfer_enabled": True,
                "cd2_require_mount": False,
                "cd2_target_dir": str(cd2_dir),
            })

            app.validate_iso = lambda candidate: candidate == target
            result = app.transfer_iso_to_mount(target, cfg)

            self.assertIsNone(result)
            self.assertTrue(target.exists())
            self.assertFalse((cd2_dir / target.name).exists())

    def test_cd2_upload_queue_ignores_non_iso_paths(self) -> None:
        status = {"uploads": []}
        result = SimpleNamespace(uploadFiles=[
            SimpleNamespace(
                key="valid",
                destPath="/115/00-mkiso/Movie.2026.iso",
                status="uploading",
                transferedBytes=50,
                size=100,
                errorMessage="",
            ),
            SimpleNamespace(
                key="partial",
                destPath="/115/00-mkiso/Movie.2026.iso..partial",
                status="uploading",
                transferedBytes=20,
                size=100,
                errorMessage="",
            ),
        ])

        upload_map = app.attach_cd2_upload_entries(status, result)

        self.assertEqual(list(upload_map), ["/115/00-mkiso/Movie.2026.iso"])
        self.assertEqual([item["path"] for item in status["uploads"]], ["/115/00-mkiso/Movie.2026.iso"])
        self.assertIsNone(app.find_upload_for_path(upload_map, "/115/00-mkiso/Movie.2026.iso..partial"))

    def test_cd2_upload_done_requires_finish_status(self) -> None:
        uploading = {
            "status": "3",
            "status_enum": "3",
            "current": 100,
            "total": 100,
            "percent": 100.0,
        }
        finished = {
            "status": "5",
            "status_enum": "5",
            "current": 100,
            "total": 100,
            "percent": 100.0,
        }
        status_missing = {
            "status": "unknown",
            "current": 100,
            "total": 100,
            "percent": 100.0,
        }

        self.assertFalse(app.cd2_upload_done(uploading))
        self.assertTrue(app.cd2_upload_done(finished))
        self.assertFalse(app.cd2_upload_done(status_missing))
        for terminal_failure in ("2", "6", "8", "9", "10", "Cancelled", "Skipped", "Ignored", "Error", "FatalError"):
            with self.subTest(status=terminal_failure):
                self.assertFalse(app.cd2_upload_done({"status": terminal_failure, "status_enum": terminal_failure}))

    def test_cd2_upload_info_preserves_numeric_status_enum(self) -> None:
        info = app.build_cd2_upload_info(SimpleNamespace(
            key="upload-key",
            destPath="/115/00-mkiso/Movie.2026.iso",
            status="Transfer",
            statusEnum=3,
            transferedBytes=100,
            size=100,
            errorMessage="",
        ))

        self.assertEqual(info["status"], "Transfer")
        self.assertEqual(info["status_enum"], "3")
        self.assertFalse(app.cd2_upload_done(info))

    def test_cd2_copy_uses_rename_policy_and_recursive_conflict_handling(self) -> None:
        requests = []

        class Stub:
            def CopyFile(self, request, metadata=None):
                requests.append((request, metadata))
                return SimpleNamespace(success=True, errorMessage="", resultFilePaths=["/remote/target/Movie (1)"])

        class StubClient:
            stub = Stub()

            def _create_authorized_metadata(self):
                return [("authorization", "Bearer test")]

        result = app.cd2_copy_file(StubClient(), ["/remote/source/Movie"], "/remote/target")

        self.assertTrue(result.success)
        self.assertEqual(len(requests), 1)
        request, metadata = requests[0]
        self.assertEqual(request.conflictPolicy, 1)
        self.assertTrue(request.handleConflictRecursively)
        self.assertEqual(list(request.theFilePaths), ["/remote/source/Movie"])
        self.assertEqual(metadata, [("authorization", "Bearer test")])
        self.assertEqual(app.cd2_result_success(result)[2], ["/remote/target/Movie (1)"])

    def test_cd2_rename_result_maps_to_actual_local_pull_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = Path(temp_dir) / "watch"
            fallback = local_dir / "Movie"
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({"cd2_local_pull_dir": str(local_dir), "watch_dir": str(local_dir)})

            actual = app.cd2_local_pull_path_from_result(
                cfg,
                "/remote/target",
                ["/remote/target/Movie (1)"],
                fallback,
            )

            self.assertEqual(actual, (local_dir / "Movie (1)").resolve())

    def test_upload_matching_does_not_fallback_to_same_basename(self) -> None:
        upload_map = {
            "/remote/site-b/Movie.iso": {
                "path": "/remote/site-b/Movie.iso",
                "status": "Transfer",
            },
        }

        self.assertIsNone(app.find_upload_for_path(upload_map, "/remote/site-a/Movie.iso", {"cd2_path_aliases": []}))

    def test_cd2_local_pull_path_disambiguates_same_basename_sources(self) -> None:
        cfg = dict(app.DEFAULT_CONFIG)
        cfg.update({"cd2_local_pull_dir": "/watch", "watch_dir": "/watch"})
        source_a = "/remote/Site A/Movie"
        source_b = "/remote/Site B/Movie"
        first = app.cd2_local_pull_path_for_source(cfg, source_a)
        app.state["items"][str(first)] = {
            "status": "waiting_cd2_pull",
            "cd2_pull_source": source_a,
        }
        second = app.cd2_local_pull_path_for_source(cfg, source_b)

        self.assertEqual(first.name, "Movie")
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.startswith("Movie__CD2-"))

    def test_cd2_copy_task_control_matches_source_and_destination(self) -> None:
        requests = []

        class Stub:
            def PauseCopyTask(self, request, metadata=None):
                requests.append(("pause", request, metadata))
                return SimpleNamespace()

        class Client:
            stub = Stub()

            def _create_authorized_metadata(self):
                return [("authorization", "Bearer test")]

        source = "/watch/Site A/Movie"
        app.state["items"][source] = {
            "status": "waiting_cd2_pull",
            "pack_iso": True,
            "cd2_pull_source": "/remote/Site A/Movie",
            "cd2_pull_dest": "/watch-pull",
        }
        app.get_cd2_client = lambda _cfg: Client()
        app.fetch_cd2_uploads = lambda _cfg: ({}, {
            "connected": True,
            "copy_tasks_complete": True,
            "upload_queue_complete": True,
            "copy_tasks": [{
                "kind": "copy",
                "source": "/remote/Site A/Movie",
                "target": "/watch-pull",
                "done": False,
                "paused": False,
            }],
            "downloads": [],
        })

        result, status_code = app.control_cd2_task(source, "pause_copy", dict(app.DEFAULT_CONFIG))

        self.assertTrue(result["ok"])
        self.assertEqual(status_code, 200)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][0], "pause")
        self.assertEqual(requests[0][1].sourcePath, "/remote/Site A/Movie")
        self.assertEqual(requests[0][1].destPath, "/watch-pull")
        self.assertTrue(requests[0][1].pause)

        app.fetch_cd2_uploads = lambda _cfg: ({}, {
            "connected": True,
            "copy_tasks_complete": True,
            "upload_queue_complete": True,
            "copy_tasks": [{
                "kind": "copy",
                "source": "/remote/Site B/Movie",
                "target": "/watch-pull",
                "done": False,
            }],
            "downloads": [],
        })
        rejected, rejected_code = app.control_cd2_task(source, "restart_copy", dict(app.DEFAULT_CONFIG))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected_code, 409)
        self.assertEqual(len(requests), 1)

    def test_cd2_upload_task_control_uses_exact_upload_key(self) -> None:
        requests = []

        class Stub:
            def PauseUploadFiles(self, request, metadata=None):
                requests.append((request, metadata))
                return SimpleNamespace()

        class Client:
            stub = Stub()

            def _create_authorized_metadata(self):
                return []

        source = "/watch/Movie"
        target = "/CloudNAS/CloudDrive/finished/Movie.iso"
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "pack_iso": True,
            "target": target,
        }
        upload = {
            "key": "upload-key-1",
            "path": "/115/finished/Movie.iso",
            "status": "Transfer",
            "status_enum": "3",
            "current": 10,
            "total": 100,
            "percent": 10,
        }
        app.get_cd2_client = lambda _cfg: Client()
        app.fetch_cd2_uploads = lambda _cfg: ({upload["path"]: upload}, {
            "connected": True,
            "copy_tasks_complete": True,
            "upload_queue_complete": True,
            "copy_tasks": [],
            "downloads": [],
        })

        result, status_code = app.control_cd2_task(source, "pause_upload", dict(app.DEFAULT_CONFIG))

        self.assertTrue(result["ok"])
        self.assertEqual(status_code, 200)
        self.assertEqual(list(requests[0][0].keys), ["upload-key-1"])

    def test_cd2_push_event_and_diagnostics_are_observable(self) -> None:
        event = app.record_cd2_push_event(SimpleNamespace(
            messageType=4,
            fileSystemChange=SimpleNamespace(path="/remote/Movie", newPath=""),
        ))
        self.assertEqual(event["type"], "FILE_SYSTEM_CHANGE")
        self.assertEqual(app.state["cd2"]["push"]["last_event"]["path"], "/remote/Movie")

        class Stub:
            def GetRuntimeInfo(self, _request, metadata=None):
                return SimpleNamespace(productName="CloudDrive2", productVersion="0.9", CloudAPIVersion="1.0", osInfo="Linux")

            def GetRunningInfo(self, _request, metadata=None):
                return SimpleNamespace(cpuUsage=12.5, memUsageKB=2048, totalMemoryKB=4096, uptime=100, fhTableCount=3, dirCacheCount=4, tempFileCount=5, dbDirCacheCount=6, downloadBytesPerSecond=7, uploadBytesPerSecond=8)

            def GetAllTasksCount(self, _request, metadata=None):
                return SimpleNamespace(downloadCount=1, uploadCount=2, copyTaskCount=3)

            def GetOpenFileHandles(self, _request, metadata=None):
                return SimpleNamespace(openFileHandles=[SimpleNamespace(fileHandle=1, processId=2, processPath="/cd2", filePath="/CloudNAS/Movie.iso", isDirectory=False, specialCommand="")])

            def GetFileDetailProperties(self, request, metadata=None):
                return SimpleNamespace(totalFileCount=10, totalFolderCount=2, totalSize=999, originalPath=request.path)

        class Client:
            stub = Stub()

            def _create_authorized_metadata(self):
                return []

        app.get_cd2_client = lambda _cfg: Client()
        cfg = dict(app.DEFAULT_CONFIG)
        cfg.update({"cd2_api_enabled": True})
        diagnostics = app.cd2_diagnostics(cfg, "/CloudNAS/Movie.iso")

        self.assertTrue(diagnostics["ok"])
        self.assertEqual(diagnostics["runtime"]["product_version"], "0.9")
        self.assertEqual(diagnostics["task_counts"]["copy"], 3)
        self.assertEqual(diagnostics["file_detail"]["total_size"], 999)
        self.assertEqual(len(diagnostics["open_file_handles"]), 1)

    def test_cd2_upload_queue_uses_documented_pagination(self) -> None:
        class PagedUploadClient:
            def __init__(self) -> None:
                self.calls = []

            def get_upload_file_list(self, get_all=True, items_per_page=0, page_number=0):
                self.calls.append((get_all, items_per_page, page_number))
                pages = {
                    0: SimpleNamespace(
                        totalCount=3,
                        globalBytesPerSecond=12.5,
                        totalBytes=300,
                        finishedBytes=50,
                        uploadFiles=[
                            SimpleNamespace(
                                key="one",
                                destPath="/115/00-mkiso/One.iso",
                                status="uploading",
                                transferedBytes=50,
                                size=100,
                                errorMessage="",
                            ),
                            SimpleNamespace(
                                key="partial",
                                destPath="/115/00-mkiso/Partial.iso..partial",
                                status="uploading",
                                transferedBytes=20,
                                size=100,
                                errorMessage="",
                            ),
                        ],
                    ),
                    1: SimpleNamespace(
                        totalCount=3,
                        globalBytesPerSecond=12.5,
                        totalBytes=300,
                        finishedBytes=50,
                        uploadFiles=[
                            SimpleNamespace(
                                key="two",
                                destPath="/115/00-mkiso/Two.iso",
                                status="completed",
                                transferedBytes=200,
                                size=200,
                                errorMessage="",
                            ),
                        ],
                    ),
                }
                return pages[page_number]

            def get_download_file_list(self):
                return SimpleNamespace(downloadFiles=[])

            def get_copy_tasks(self):
                return SimpleNamespace(copyTasks=[])

        client = PagedUploadClient()
        app.get_cd2_client = lambda _cfg: client
        cfg = dict(app.DEFAULT_CONFIG)
        cfg.update({
            "cd2_api_enabled": True,
            "cd2_api_password": "token",
            "cd2_queue_poll_seconds": 1,
        })

        upload_map, status = app.fetch_cd2_uploads(cfg)

        self.assertEqual(client.calls, [(False, 100, 0), (False, 100, 1)])
        self.assertTrue(status["connected"])
        self.assertTrue(status["upload_queue_complete"])
        self.assertEqual(status["upload_count"], 2)
        self.assertEqual(list(upload_map), ["/115/00-mkiso/One.iso", "/115/00-mkiso/Two.iso"])

    def _seed_cd2_pull_claim(self, cfg, watch_dir, source_path, status="submitted", failure_code=None):
        claim_key = app.cd2_auto_pull_claim_key(source_path, cfg["cd2_remote_pull_dest_dir"])
        claim = {
            "source_path": source_path,
            "dest_dir": cfg["cd2_remote_pull_dest_dir"],
            "status": status,
            "local_path": str(watch_dir / Path(source_path).name),
            "created_at": app.now(),
            "updated_at": app.now(),
        }
        if failure_code:
            claim["failure_code"] = failure_code
        app.state["cd2"]["auto_pull_claims"] = {claim_key: claim}
        return claim_key

    def test_cd2_copy_api_progress_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            watch_dir = Path(temp_dir) / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
            })
            source_path = "/remote/Mercy.2026.V2.2160p.BluRay@CHDBits"
            claim_key = self._seed_cd2_pull_claim(cfg, watch_dir, source_path)
            task = {
                "kind": "copy",
                "source": source_path,
                "target": cfg["cd2_remote_pull_dest_dir"],
                "status": "2",
                "current": 42,
                "total": 100,
                "percent": 42.0,
                "done_files": 1,
                "total_files": 3,
                "done": False,
                "human": "CD2 复制中 42.0%",
            }

            summary = app.reconcile_cd2_auto_pull_claims(
                cfg,
                {"connected": True, "copy_tasks_complete": True, "copy_tasks": [task]},
            )

            self.assertEqual(summary["waiting"], 1)
            claim = app.state["cd2"]["auto_pull_claims"][claim_key]
            self.assertEqual(claim["status"], "submitted")
            self.assertEqual(claim["last_task"]["current"], 42)
            item = app.state["items"][str(watch_dir / Path(source_path).name)]
            self.assertEqual(item["status"], "waiting_cd2_pull")
            self.assertIn("42.0%", item["error"])

    def test_cd2_copy_api_completion_marks_pull_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            watch_dir = Path(temp_dir) / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
            })
            source_path = "/remote/Mercy.2026.V2.2160p.BluRay@CHDBits"
            claim_key = self._seed_cd2_pull_claim(cfg, watch_dir, source_path)
            task = {
                "kind": "copy",
                "source": source_path,
                "target": cfg["cd2_remote_pull_dest_dir"],
                "status": "3",
                "current": 100,
                "total": 100,
                "percent": 100.0,
                "done_files": 1,
                "total_files": 1,
                "done": True,
                "human": "CD2 复制完成 100.0%",
            }

            app.reconcile_cd2_auto_pull_claims(
                cfg,
                {"connected": True, "copy_tasks_complete": True, "copy_tasks": [task]},
            )

            claim = app.state["cd2"]["auto_pull_claims"][claim_key]
            self.assertEqual(claim["status"], "completed")
            item = app.state["items"][str(watch_dir / Path(source_path).name)]
            self.assertEqual(item["status"], "waiting_cd2_pull")
            self.assertTrue(item.get("cd2_pull_finished_at"))

    def test_cd2_copy_api_failure_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            watch_dir = Path(temp_dir) / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
            })
            source_path = "/remote/Mercy.2026.V2.2160p.BluRay@CHDBits"
            claim_key = self._seed_cd2_pull_claim(cfg, watch_dir, source_path)
            task = {
                "kind": "copy",
                "source": source_path,
                "target": cfg["cd2_remote_pull_dest_dir"],
                "status": "4",
                "failed_files": 1,
                "done": False,
                "errors": ["目标空间不足"],
                "human": "CD2 复制失败",
            }

            app.reconcile_cd2_auto_pull_claims(
                cfg,
                {"connected": True, "copy_tasks_complete": True, "copy_tasks": [task]},
            )

            claim = app.state["cd2"]["auto_pull_claims"][claim_key]
            self.assertEqual(claim["status"], "failed")
            self.assertEqual(claim["failure_code"], "cd2_copy_failed")
            item = app.state["items"][str(watch_dir / Path(source_path).name)]
            self.assertEqual(item["status"], "transfer_failed")
            self.assertEqual(item["failure_code"], "cd2_copy_failed")

    def test_cd2_copy_api_missing_task_stays_pending_without_remote_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            watch_dir = Path(temp_dir) / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
            })
            source_path = "/remote/Mercy.2026.V2.2160p.BluRay@CHDBits"
            claim_key = self._seed_cd2_pull_claim(cfg, watch_dir, source_path)
            with patch.object(app, "get_cd2_client", side_effect=AssertionError("不应访问远端结果")):
                summary = app.reconcile_cd2_auto_pull_claims(
                    cfg,
                    {"connected": True, "copy_tasks_complete": True, "copy_tasks": []},
                )

            self.assertEqual(summary["waiting"], 1)
            self.assertEqual(app.state["cd2"]["auto_pull_claims"][claim_key]["status"], "submitted")
            item = app.state["items"][str(watch_dir / Path(source_path).name)]
            self.assertEqual(item["status"], "waiting_cd2_pull")
            self.assertNotIn("recent_results", app.state["cd2"].get("pull", {}))

    def test_legacy_pull_failure_is_recovered_by_live_api_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            watch_dir = Path(temp_dir) / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
            })
            source_path = "/remote/Mercy.2026.V2.2160p.BluRay@CHDBits"
            claim_key = self._seed_cd2_pull_claim(
                cfg, watch_dir, source_path, status="failed", failure_code="cd2_pull_local_missing"
            )
            task = {
                "kind": "copy",
                "source": source_path,
                "target": cfg["cd2_remote_pull_dest_dir"],
                "status": "1",
                "current": 10,
                "total": 100,
                "done": False,
                "human": "CD2 复制中 10.0%",
            }
            app.reconcile_cd2_auto_pull_claims(
                cfg,
                {"connected": True, "copy_tasks_complete": True, "copy_tasks": [task]},
            )

            self.assertEqual(app.state["cd2"]["auto_pull_claims"][claim_key]["status"], "submitted")
            item = app.state["items"][str(watch_dir / Path(source_path).name)]
            self.assertEqual(item["status"], "waiting_cd2_pull")
            self.assertNotIn("failure_code", item)

    def test_cd2_upload_without_progress_stays_waiting(self) -> None:
        source = "/watch/Grace 2025"
        target = "/CloudNAS/CloudDrive/finished/Grace 2025.iso"
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "target": target,
            "pack_iso": True,
            "failure_code": "cd2_upload_stalled",
            "cd2_upload_progress_current": 100,
        }
        upload = {"path": target, "status": "uploading", "current": 100, "total": 1000, "percent": 10.0}

        app.check_waiting_cd2_uploads(
            dict(app.DEFAULT_CONFIG),
            {app.normalize_upload_path(target): upload},
            {"connected": True, "checked_at": app.now(), "human": "connected"},
        )

        item = app.state["items"][source]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertNotIn("failure_code", item)
        self.assertEqual(item["cd2_upload"]["current"], 100)

    def test_cd2_upload_api_failure_is_terminal(self) -> None:
        source = "/watch/Failed upload"
        target = "/CloudNAS/CloudDrive/finished/Failed upload.iso"
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "target": target,
            "pack_iso": True,
        }
        upload = {
            "path": target,
            "status": "failed",
            "error": "目标空间不足",
            "current": 100,
            "total": 1000,
            "percent": 10.0,
        }

        app.check_waiting_cd2_uploads(
            dict(app.DEFAULT_CONFIG),
            {app.normalize_upload_path(target): upload},
            {"connected": True, "checked_at": app.now(), "human": "connected"},
        )

        item = app.state["items"][source]
        self.assertEqual(item["status"], "transfer_failed")
        self.assertEqual(item["failure_code"], "cd2_upload_failed")

    def test_upload_recheck_resets_monitor_failure(self) -> None:
        source = "/watch/Grace 2025"
        target = "/CloudNAS/CloudDrive/finished/Grace 2025.iso"
        app.state["items"][source] = {
            "status": "transfer_failed",
            "target": target,
            "pack_iso": True,
            "failure_code": "cd2_upload_stalled",
            "failure_label": "CD2 上传停滞",
            "error": "上传长时间没有进展",
            "cd2_upload_progress_at": "2026-08-30 00:00:00",
        }

        result, status_code, mode = app.reset_task_for_recheck(source, dict(app.DEFAULT_CONFIG))

        self.assertTrue(result["ok"])
        self.assertEqual(status_code, 200)
        self.assertEqual(mode, "upload")
        item = app.state["items"][source]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertNotIn("failure_code", item)
        self.assertNotIn("cd2_upload_progress_at", item)

    def test_manual_upload_confirmation_requires_valid_cd2_iso(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            watch_dir = base / "watch"
            cd2_dir = base / "cd2"
            watch_dir.mkdir()
            cd2_dir.mkdir()
            source = watch_dir / "Grace 2025"
            target = cd2_dir / "Grace 2025.iso"
            target.write_bytes(b"valid-iso")
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "watch_dir": str(watch_dir),
                "cd2_target_dir": str(cd2_dir),
                "cd2_require_mount": False,
            })
            app.state["items"][str(source)] = {
                "status": "transfer_failed",
                "target": str(target),
                "target_size": target.stat().st_size,
                "pack_iso": True,
                "failure_code": "cd2_upload_stalled",
            }
            app.validate_iso = lambda candidate: candidate == target.resolve()

            result, status_code = app.confirm_cd2_upload_task(str(source), cfg)

            self.assertTrue(result["ok"])
            self.assertEqual(status_code, 200)
            item = app.state["items"][str(source)]
            self.assertEqual(item["status"], "transfer_done")
            self.assertTrue(item["cd2_upload_manual_confirmed"])
            self.assertTrue(target.exists())

    def test_dashboard_separates_running_and_waiting_tasks(self) -> None:
        stats = app.dashboard_stats([
            ("/watch/running", {"status": "running", "first_seen": app.now()}),
            ("/watch/upload", {"status": "waiting_cd2_upload", "first_seen": app.now()}),
            ("/watch/partial", {"status": "waiting_partial", "first_seen": app.now()}),
        ])

        self.assertEqual(stats["active"], 1)
        self.assertEqual(stats["waiting"], 2)

    def test_active_pack_can_be_cancelled(self) -> None:
        source = "/watch/Movie 2026"
        app.state["items"][source] = {"status": "running", "pack_iso": True}
        app.state["active"] = {
            "source": source,
            "status": "running",
            "progress": {"phase": "packing"},
        }

        result, status_code = app.cancel_active_pack(source)

        self.assertTrue(result["ok"])
        self.assertEqual(status_code, 200)
        self.assertTrue(app.pack_cancel_event.is_set())
        self.assertIn("取消", app.state["items"][source]["error"])

    def test_bdmv_root_scan_returns_all_candidates_without_child_requests(self) -> None:
        root = "/remote/01-BDMV"
        movie_count = 149

        class LargeDirectoryClient:
            def __init__(self) -> None:
                self.requested_paths = []

            def get_sub_files(self, path: str, force_refresh: bool = False):
                self.requested_paths.append(path)
                if path != root:
                    raise AssertionError(f"unexpected child request: {path}")
                return [SimpleNamespace(
                    name="[Search]BDMV",
                    fullPathName=f"{root}/[Search]BDMV",
                    isDirectory=True,
                    isSearchResult=True,
                    writeTime="2026-09-01 10:00:00",
                )] + [
                    SimpleNamespace(
                        name=f"Movie {index:03d}",
                        fullPathName=f"{root}/Movie {index:03d}",
                        isDirectory=True,
                        isSearchResult=False,
                        size=0,
                        writeTime=f"2026-08-{(index % 28) + 1:02d} 10:00:00",
                    )
                    for index in range(movie_count)
                ]

        client = LargeDirectoryClient()
        cfg = dict(app.DEFAULT_CONFIG)
        cfg.update({
            "cd2_api_enabled": True,
            "cd2_manual_pull_enabled": True,
            "cd2_remote_source_dirs": [root],
            "cd2_path_aliases": [],
            "cd2_remote_scan_depth": 1,
        })

        payload = app.scan_cd2_remote_candidates(cfg, client=client)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["candidate_count"], movie_count)
        self.assertEqual(client.requested_paths, [root])
        self.assertEqual(payload["candidates"][0]["modified"], "2026-08-28 10:00:00")
        self.assertTrue(all(item["disc_type"] == "BDMV" for item in payload["candidates"]))

    def test_inferred_root_type_is_revalidated_before_copy(self) -> None:
        root = "/remote/01-BDMV"

        class InvalidDiscClient:
            def __init__(self) -> None:
                self.copy_calls = []

            def get_sub_files(self, path: str, force_refresh: bool = False):
                return []

            def copy_file(self, source_paths, dest_dir):
                self.copy_calls.append((source_paths, dest_dir))

            def copy_file_safe(self, source_paths, dest_dir, **_kwargs):
                return self.copy_file(source_paths, dest_dir)

        client = InvalidDiscClient()
        app.get_cd2_client = lambda _cfg: client
        cfg = dict(app.DEFAULT_CONFIG)
        cfg.update({
            "cd2_api_enabled": True,
            "cd2_auto_pull_enabled": True,
            "cd2_remote_source_dirs": [root],
            "cd2_path_aliases": [],
            "cd2_remote_pull_dest_dir": "/remote/pulled",
            "cd2_local_pull_dir": "/watch",
            "watch_dir": "/watch",
        })

        payload, status_code = app.create_cd2_pull_task(
            cfg,
            f"{root}/Movie Without Disc Structure",
            mode="auto",
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(status_code, 400)
        self.assertIn("不是 BDMV / VIDEO_TS", payload["message"])
        self.assertEqual(client.copy_calls, [])

    def test_generic_root_scan_reports_partial_child_failure(self) -> None:
        root = "/remote/inbox"

        class PartialFailureClient:
            def get_sub_files(self, path: str, force_refresh: bool = False):
                if path == root:
                    return [
                        SimpleNamespace(name="Movie A", fullPathName=f"{root}/Movie A", isDirectory=True),
                        SimpleNamespace(name="Movie B", fullPathName=f"{root}/Movie B", isDirectory=True),
                    ]
                if path == f"{root}/Movie A":
                    return [SimpleNamespace(name="BDMV", fullPathName=f"{path}/BDMV", isDirectory=True)]
                raise RuntimeError("CD2 connection closed")

        cfg = dict(app.DEFAULT_CONFIG)
        cfg.update({
            "cd2_api_enabled": True,
            "cd2_manual_pull_enabled": True,
            "cd2_remote_source_dirs": [root],
            "cd2_path_aliases": [],
            "cd2_remote_scan_depth": 1,
        })

        payload = app.scan_cd2_remote_candidates(cfg, client=PartialFailureClient())

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["partial"])
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(len(payload["errors"]), 1)

    def test_cd2_pull_matching_uses_source_path_with_shared_target(self) -> None:
        source_root = "/remote/115/00-未整理"
        shared_target = "/mnt/115Download"
        source_a = f"{source_root}/Movie A"
        source_b = f"{source_root}/Movie B"
        source_c = f"{source_root}/Movie C"
        status = {
            "connected": True,
            "copy_tasks": [
                {"done": False, "source": f"{source_a}/BDMV", "target": shared_target},
                {"done": False, "source": source_b, "target": shared_target},
                {"done": False, "source": "", "target": shared_target},
            ],
            "downloads": [],
        }

        self.assertTrue(app.cd2_remote_task_matches_pull(source_a, shared_target, status))
        self.assertTrue(app.cd2_remote_task_matches_pull(source_b, shared_target, status))
        self.assertFalse(app.cd2_remote_task_matches_pull(source_a, "/mnt/another-target", status))
        self.assertFalse(app.cd2_remote_task_matches_pull(source_c, shared_target, status))

        pending_a = app.cd2_recorded_pull_pending(
            {"cd2_pull_source": source_a, "cd2_pull_dest": shared_target},
            status,
            finish_missing=False,
        )
        pending_c = app.cd2_recorded_pull_pending(
            {"cd2_pull_source": source_c, "cd2_pull_dest": shared_target},
            status,
            finish_missing=False,
        )
        self.assertIsNotNone(pending_a)
        self.assertEqual(pending_a["source"], f"{source_a}/BDMV")
        self.assertIsNone(pending_c)

    def test_cd2_pending_source_task_uses_aliases_without_name_fallback(self) -> None:
        status = {
            "connected": True,
            "copy_tasks": [
                {
                    "done": False,
                    "source": "/remote/Site A/Movie",
                    "target": "/mnt/115Download",
                },
            ],
            "downloads": [],
        }
        cfg = {"cd2_path_aliases": [{"local": "/watch", "remote": "/remote"}]}

        matched = app.cd2_pending_source_task(Path("/watch/Site A/Movie"), status, cfg)
        different_site = app.cd2_pending_source_task(Path("/watch/Site B/Movie"), status, cfg)

        self.assertIsNotNone(matched)
        self.assertIsNone(different_site)

    def test_candidate_scan_timeout_is_single_flight(self) -> None:
        release = threading.Event()
        factory_calls = []

        class BlockingClient:
            def close(self):
                return None

        original_factory = app.create_isolated_cd2_client
        original_scan = app.scan_cd2_remote_candidates
        try:
            app.reset_cd2_candidate_scan_controller()

            def fake_factory(_cfg):
                factory_calls.append(True)
                return BlockingClient(), ""

            def fake_scan(_cfg, force_refresh=False, client=None):
                release.wait(1)
                return {"ok": True, "candidates": [], "candidate_count": 0, "message": "done"}

            app.create_isolated_cd2_client = fake_factory
            app.scan_cd2_remote_candidates = fake_scan
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({"cd2_api_enabled": True, "cd2_remote_source_dirs": ["/remote"]})

            first = app.controlled_cd2_remote_candidates(cfg, force_refresh=True, timeout_seconds=0.01)
            second = app.controlled_cd2_remote_candidates(cfg, force_refresh=True, timeout_seconds=0.01)

            self.assertFalse(first["ok"])
            self.assertTrue(first["scan_timeout"])
            self.assertFalse(second["ok"])
            self.assertEqual(len(factory_calls), 1)
        finally:
            release.set()
            for _ in range(50):
                thread = app.cd2_candidate_scan_state.get("thread")
                if not thread or not thread.is_alive():
                    break
                time.sleep(0.01)
            app.create_isolated_cd2_client = original_factory
            app.scan_cd2_remote_candidates = original_scan
            app.reset_cd2_candidate_scan_controller()

    def test_auto_pull_claim_prevents_duplicate_and_can_be_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            watch_dir = base / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_api_enabled": True,
                "cd2_remote_source_dirs": ["/remote"],
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
            })
            client = FakePullClient()
            app.get_cd2_client = lambda _cfg: client

            source_path = "/remote/Mercy.2026.V2.2160p.BluRay@CHDBits"
            first, first_code = app.create_cd2_pull_task(cfg, source_path, mode="auto")
            self.assertTrue(first["ok"])
            self.assertEqual(first_code, 200)
            self.assertEqual(len(client.copy_calls), 1)
            app.save_state_locked = self.original_functions["save_state_locked"]
            app.save_state_locked()
            persisted = app.json.loads(app.STATE_PATH.read_text(encoding="utf-8"))
            self.assertIn("auto_pull_claims", persisted["cd2"])
            app.save_state_locked = lambda: None
            self.assertEqual(app.cd2_remote_candidate_status(cfg, source_path)["pull_state"], "active")

            app.state["items"] = {}
            second, second_code = app.create_cd2_pull_task(cfg, source_path, mode="auto")
            self.assertFalse(second["ok"])
            self.assertEqual(second_code, 409)
            self.assertEqual(len(client.copy_calls), 1)

            claim_key = app.cd2_auto_pull_claim_key(source_path, "/remote-destination")
            app.state["cd2"]["auto_pull_claims"][claim_key]["status"] = "completed"
            cleared, clear_code = app.clear_cd2_pull_record(cfg, source_path)
            self.assertTrue(cleared["ok"])
            self.assertEqual(clear_code, 200)
            self.assertEqual(cleared["removed_claim_count"], 1)

            third, third_code = app.create_cd2_pull_task(cfg, source_path, mode="auto")
            self.assertTrue(third["ok"])
            self.assertEqual(third_code, 200)
            self.assertEqual(len(client.copy_calls), 2)


if __name__ == "__main__":
    unittest.main()
