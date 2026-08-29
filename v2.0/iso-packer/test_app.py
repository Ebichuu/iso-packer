from __future__ import annotations

import copy
import os
import tempfile
import unittest
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
        app.save_state_locked = lambda: None
        os.environ.pop("ISO_PACKER_DISABLE_CD2_PULL", None)

    def tearDown(self) -> None:
        app.state = self.original_state
        for name, function in self.original_functions.items():
            setattr(app, name, function)
        for name, path in self.original_paths.items():
            setattr(app, name, path)
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
