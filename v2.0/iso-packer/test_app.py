from __future__ import annotations

import copy
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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

    def copy_file(self, source_paths, dest_dir):
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
        self.assertNotEqual(
            identities["same film site v1"]["identity_key"],
            identities["different site"]["identity_key"],
        )
        self.assertEqual(identities["unversioned coexists"]["identity_key"], identities["same film site v1"]["identity_key"])

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
            self.assertFalse(target.exists())
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
            self.assertFalse(target.exists())

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

    def test_completed_cd2_pull_claim_requires_remote_and_local_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            watch_dir = Path(temp_dir) / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_api_enabled": True,
                "cd2_api_password": "token",
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
                "cd2_pull_result_grace_seconds": 0,
            })
            source_path = "/remote/Mercy.2026.V2.2160p.BluRay@CHDBits"
            target_path = "/remote-destination/Mercy.2026.V2.2160p.BluRay@CHDBits"
            local_path = watch_dir / Path(source_path).name
            local_path.mkdir()
            claim_key = app.cd2_auto_pull_claim_key(source_path, cfg["cd2_remote_pull_dest_dir"])
            app.state["cd2"]["auto_pull_claims"] = {
                claim_key: {
                    "source_path": source_path,
                    "dest_dir": cfg["cd2_remote_pull_dest_dir"],
                    "status": "submitted",
                    "local_path": str(local_path),
                    "result_paths": [target_path],
                    "created_at": app.now(),
                    "updated_at": app.now(),
                }
            }

            class RemoteResultClient:
                def find_file_by_path(self, path):
                    self.path = path
                    return SimpleNamespace(fullPathName=target_path, name=Path(target_path).name, isDirectory=True)

            app.get_cd2_client = lambda _cfg: RemoteResultClient()
            app.reconcile_cd2_auto_pull_claims(cfg, {"connected": True, "copy_tasks": []})

            self.assertEqual(app.state["cd2"]["auto_pull_claims"][claim_key]["status"], "completed")

    def test_missing_cd2_pull_result_releases_claim_for_one_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            watch_dir = Path(temp_dir) / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_api_enabled": True,
                "cd2_api_password": "token",
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
                "cd2_pull_result_grace_seconds": 0,
            })
            source_path = "/remote/Americana.2025.BluRay@OurBits"
            target_path = "/remote-destination/Americana.2025.BluRay@OurBits"
            claim_key = app.cd2_auto_pull_claim_key(source_path, cfg["cd2_remote_pull_dest_dir"])
            app.state["cd2"]["auto_pull_claims"] = {
                claim_key: {
                    "source_path": source_path,
                    "dest_dir": cfg["cd2_remote_pull_dest_dir"],
                    "status": "submitted",
                    "local_path": str(watch_dir / Path(source_path).name),
                    "result_paths": [target_path],
                    "created_at": app.now(),
                    "updated_at": app.now(),
                }
            }

            class MissingResultClient:
                def find_file_by_path(self, _path):
                    return SimpleNamespace()

                def get_sub_files(self, _path, force_refresh=False):
                    return []

            app.get_cd2_client = lambda _cfg: MissingResultClient()
            app.reconcile_cd2_auto_pull_claims(cfg, {"connected": True, "copy_tasks": []})

            self.assertNotIn(claim_key, app.state["cd2"]["auto_pull_claims"])
            recent = app.state["cd2"]["pull"]["recent_results"][-1]
            self.assertEqual(recent["failure_code"], "cd2_pull_missing_result")
            self.assertTrue(recent["retryable"])
            self.assertFalse(app.cd2_pull_recent_failure(source_path))

    def test_missing_cd2_pull_result_after_retry_becomes_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            watch_dir = Path(temp_dir) / "watch"
            watch_dir.mkdir()
            cfg = dict(app.DEFAULT_CONFIG)
            cfg.update({
                "cd2_api_enabled": True,
                "cd2_api_password": "token",
                "cd2_remote_pull_dest_dir": "/remote-destination",
                "cd2_local_pull_dir": str(watch_dir),
                "watch_dir": str(watch_dir),
                "cd2_pull_result_grace_seconds": 0,
            })
            source_path = "/remote/Anaconda.V2.2025.BluRay@CHDBits"
            target_path = "/remote-destination/Anaconda.V2.2025.BluRay@CHDBits"
            claim_key = app.cd2_auto_pull_claim_key(source_path, cfg["cd2_remote_pull_dest_dir"])
            app.state["cd2"].setdefault("pull", {})["recent_results"] = [{
                "source_path": source_path,
                "dest_dir": cfg["cd2_remote_pull_dest_dir"],
                "ok": False,
                "failure_code": "cd2_pull_missing_result",
                "retryable": True,
                "created_at": app.now(),
            }]
            app.state["cd2"]["auto_pull_claims"] = {
                claim_key: {
                    "source_path": source_path,
                    "dest_dir": cfg["cd2_remote_pull_dest_dir"],
                    "status": "submitted",
                    "local_path": str(watch_dir / Path(source_path).name),
                    "result_paths": [target_path],
                    "created_at": app.now(),
                    "updated_at": app.now(),
                }
            }

            class MissingResultClient:
                def find_file_by_path(self, _path):
                    return SimpleNamespace()

                def get_sub_files(self, _path, force_refresh=False):
                    return []

            app.get_cd2_client = lambda _cfg: MissingResultClient()
            app.reconcile_cd2_auto_pull_claims(cfg, {"connected": True, "copy_tasks": []})

            self.assertNotIn(claim_key, app.state["cd2"]["auto_pull_claims"])
            item = app.state["items"][str(watch_dir / Path(source_path).name)]
            self.assertEqual(item["status"], "transfer_failed")
            self.assertEqual(item["failure_code"], "cd2_pull_missing_result")

    def test_cd2_upload_progress_resets_stall_timer(self) -> None:
        source = "/watch/Grace 2025"
        target = "/CloudNAS/CloudDrive/finished/Grace 2025.iso"
        old_progress_at = (datetime.now() - timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S")
        recent_observation = (datetime.now() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "target": target,
            "pack_iso": True,
            "cd2_upload_wait_started_at": old_progress_at,
            "cd2_upload_seen_at": old_progress_at,
            "cd2_upload_progress_at": old_progress_at,
            "cd2_upload_progress_current": 100,
            "cd2_upload_progress_percent": 10.0,
            "cd2_upload_last_observed_at": recent_observation,
        }
        upload = {"path": target, "status": "uploading", "current": 101, "total": 1000, "percent": 10.1}
        checked_at = app.now()

        app.check_waiting_cd2_uploads(
            dict(app.DEFAULT_CONFIG),
            {app.normalize_upload_path(target): upload},
            {"connected": True, "checked_at": checked_at, "human": "connected"},
        )

        item = app.state["items"][source]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertEqual(item["cd2_upload_progress_current"], 101)
        self.assertEqual(item["cd2_upload_progress_at"], checked_at)

    def test_cd2_upload_stalls_after_thirty_minutes_without_progress(self) -> None:
        source = "/watch/Grace 2025"
        target = "/CloudNAS/CloudDrive/finished/Grace 2025.iso"
        old_progress_at = (datetime.now() - timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S")
        recent_observation = (datetime.now() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "target": target,
            "pack_iso": True,
            "cd2_upload_wait_started_at": old_progress_at,
            "cd2_upload_seen_at": old_progress_at,
            "cd2_upload_progress_at": old_progress_at,
            "cd2_upload_progress_current": 100,
            "cd2_upload_progress_percent": 10.0,
            "cd2_upload_last_observed_at": recent_observation,
        }
        upload = {"path": target, "status": "uploading", "current": 100, "total": 1000, "percent": 10.0}

        app.check_waiting_cd2_uploads(
            dict(app.DEFAULT_CONFIG),
            {app.normalize_upload_path(target): upload},
            {"connected": True, "checked_at": app.now(), "human": "connected"},
        )

        item = app.state["items"][source]
        self.assertEqual(item["status"], "transfer_failed")
        self.assertEqual(item["failure_code"], "cd2_upload_stalled")
        self.assertEqual(item["target"], target)

    def test_cd2_upload_missing_after_thirty_minutes(self) -> None:
        source = "/watch/Mona Lisa 1986"
        target = "/CloudNAS/CloudDrive/finished/Mona Lisa 1986.iso"
        missing_since = (datetime.now() - timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S")
        recent_observation = (datetime.now() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "target": target,
            "pack_iso": True,
            "cd2_upload_wait_started_at": missing_since,
            "cd2_upload_missing_since": missing_since,
            "cd2_upload_last_observed_at": recent_observation,
        }

        app.check_waiting_cd2_uploads(
            dict(app.DEFAULT_CONFIG),
            {},
            {"connected": True, "checked_at": app.now(), "human": "connected"},
        )

        item = app.state["items"][source]
        self.assertEqual(item["status"], "transfer_failed")
        self.assertEqual(item["failure_code"], "cd2_upload_missing")

    def test_cd2_disconnect_pauses_stall_detection(self) -> None:
        source = "/watch/Grace 2025"
        target = "/CloudNAS/CloudDrive/finished/Grace 2025.iso"
        old_progress_at = (datetime.now() - timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S")
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "target": target,
            "pack_iso": True,
            "cd2_upload_wait_started_at": old_progress_at,
            "cd2_upload_seen_at": old_progress_at,
            "cd2_upload_progress_at": old_progress_at,
            "cd2_upload_progress_current": 100,
            "cd2_upload_progress_percent": 10.0,
            "cd2_upload_last_observed_at": old_progress_at,
        }

        app.check_waiting_cd2_uploads(
            dict(app.DEFAULT_CONFIG),
            {},
            {"connected": False, "checked_at": app.now(), "human": "disconnected"},
        )

        item = app.state["items"][source]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertTrue(item["cd2_upload_monitor_paused"])

    def test_incomplete_upload_pagination_pauses_missing_detection(self) -> None:
        source = "/watch/Incomplete queue 2025"
        target = "/CloudNAS/CloudDrive/finished/Incomplete queue 2025.iso"
        missing_since = (datetime.now() - timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S")
        app.state["items"][source] = {
            "status": "waiting_cd2_upload",
            "target": target,
            "pack_iso": True,
            "cd2_upload_wait_started_at": missing_since,
            "cd2_upload_missing_since": missing_since,
        }

        app.check_waiting_cd2_uploads(
            dict(app.DEFAULT_CONFIG),
            {},
            {"connected": True, "checked_at": app.now(), "upload_queue_complete": False, "human": "partial"},
        )

        item = app.state["items"][source]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertTrue(item["cd2_upload_monitor_paused"])
        self.assertEqual(item["cd2_upload_missing_since"], missing_since)

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
