import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "iso-packer"))

import app as app_module


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        app_module.APP_DIR = self.data_dir
        app_module.CONFIG_PATH = self.data_dir / "config.json"
        app_module.STATE_PATH = self.data_dir / "state.json"
        app_module.LOG_PATH = self.data_dir / "iso-packer.log"
        app_module.state = {"items": {}, "last_scan": None, "active": None, "events": [], "cd2": {}}
        app_module.worker_started = True
        app_module.app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app_module.app.test_client()

        self.watch = self.data_dir / "watch"
        self.output = self.data_dir / "output"
        self.cd2 = self.data_dir / "CloudNAS" / "CloudDrive" / "00-未整理" / "00-mkiso"
        self.watch.mkdir(parents=True)
        self.output.mkdir(parents=True)
        self.cd2.mkdir(parents=True)

        cfg = app_module.DEFAULT_CONFIG.copy()
        cfg.update({
            "watch_dir": str(self.watch),
            "output_dir": str(self.output),
            "cd2_mount_root": str(self.data_dir / "CloudNAS"),
            "cd2_target_dir": str(self.cd2),
            "web_secret_key": "test",
        })
        app_module.save_config(cfg)
        app_module.update_password(cfg, "test")

    def tearDown(self):
        app_module.CloudDriveClient = getattr(self, "original_cd2_client", app_module.CloudDriveClient)
        app_module.close_cd2_client()
        self.tmp.cleanup()

    def login(self):
        with self.client.session_transaction() as sess:
            sess["logged_in"] = True

    def scan_config(self, **updates):
        cfg = app_module.load_config()
        cfg.update({
            "stable_seconds": 30,
            "min_free_space_gb": 0,
            "delete_source_after_success": False,
        })
        cfg.update(updates)
        return cfg

    def make_bdmv(self, name, complete=True, empty=False):
        source = self.watch / name
        bdmv = source / "BDMV"
        bdmv.mkdir(parents=True)
        if empty:
            return source
        (bdmv / "index.bdmv").write_bytes(b"index")
        if complete:
            (bdmv / "MovieObject.bdmv").write_bytes(b"movie-object")
            for dirname in app_module.BDMV_REQUIRED_DIRS:
                (bdmv / dirname).mkdir()
            (bdmv / "STREAM" / "00001.m2ts").write_bytes(b"stream")
            (bdmv / "PLAYLIST" / "00001.mpls").write_bytes(b"playlist")
            (bdmv / "CLIPINF" / "00001.clpi").write_bytes(b"clip")
        else:
            (bdmv / "STREAM").mkdir()
        return source

    def mark_candidate_stable(self, source):
        key = str(source.resolve())
        app_module.state["items"][key] = {
            "first_seen": "2000-01-01 00:00:00",
            "status": "waiting_stable",
            "last_size": app_module.size_of(source),
            "tree_signature": app_module.tree_signature(source),
            "last_changed": "2000-01-01 00:00:00",
        }
        return key

    def test_healthz_is_public(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_directory_picker_blocks_escape(self):
        self.login()
        response = self.client.get(f"/api/directories?scope=watch_dir&path={self.data_dir.parent}")
        self.assertEqual(response.status_code, 403)

    def test_browse_blocks_root_escape(self):
        self.login()
        response = self.client.get("/api/browse?root=watch&path=/")
        self.assertEqual(response.status_code, 403)

    def test_login_next_rejects_external_url(self):
        response = self.client.get("/login?next=https://example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="/"', response.get_data(as_text=True))

    def test_cd2_api_token_auth_uses_bearer_token(self):
        class FakeUploadResult:
            totalCount = 0
            globalBytesPerSecond = 0
            totalBytes = 0
            finishedBytes = 0
            uploadFiles = []

        class FakeCloudDriveClient:
            def __init__(self, addr):
                self.addr = addr
                self.jwt_token = None

            def authenticate(self, username, password):
                raise AssertionError("API token mode must not call password login")

            def get_upload_file_list(self, get_all=True):
                if self.jwt_token != "api-token":
                    raise RuntimeError("missing bearer token")
                return FakeUploadResult()

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        cfg = app_module.load_config()
        cfg.update({
            "cd2_api_enabled": True,
            "cd2_auth_mode": "api_token",
            "cd2_api_addr": "127.0.0.1:19798",
            "cd2_api_username": "user@example.com",
            "cd2_api_password": "api-token",
        })

        _, status = app_module.fetch_cd2_uploads(cfg)

        self.assertTrue(status["connected"])
        self.assertEqual(status["auth_mode"], "api_token")
        self.assertEqual(status["human"], "未发现传输任务")

    def test_cd2_test_endpoint_reports_success(self):
        class FakeUploadResult:
            totalCount = 0
            globalBytesPerSecond = 0
            totalBytes = 0
            finishedBytes = 0
            uploadFiles = []

        class FakeCloudDriveClient:
            def __init__(self, addr):
                self.jwt_token = None

            def authenticate(self, username, password):
                raise AssertionError("API token mode must not call password login")

            def get_upload_file_list(self, get_all=True):
                if self.jwt_token != "api-token":
                    raise RuntimeError("missing bearer token")
                return FakeUploadResult()

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        self.login()

        response = self.client.post("/api/cd2/test", data={
            "cd2_auth_mode": "api_token",
            "cd2_api_addr": "127.0.0.1:19798",
            "cd2_api_password": "api-token",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"]["auth_mode"], "api_token")

    def test_settings_saves_cd2_auth_mode(self):
        self.login()
        response = self.client.post("/settings", data={
            "watch_dir": str(self.watch),
            "output_dir": str(self.output),
            "scan_interval_seconds": "20",
            "stable_seconds": "180",
            "min_free_space_gb": "5",
            "cd2_mount_root": str(self.data_dir / "CloudNAS"),
            "cd2_target_dir": str(self.cd2),
            "cd2_api_enabled": "on",
            "cd2_auth_mode": "password",
            "cd2_api_addr": "http://127.0.0.1:19798",
            "cd2_api_username": "user",
            "cd2_api_password": "secret",
            "cd2_queue_poll_seconds": "10",
            "enabled": "on",
            "delete_source_after_success": "on",
            "cd2_transfer_enabled": "on",
            "cd2_require_mount": "1",
        })

        self.assertEqual(response.status_code, 302)
        cfg = app_module.load_config()
        self.assertEqual(cfg["cd2_auth_mode"], "password")
        self.assertEqual(cfg["cd2_api_addr"], "127.0.0.1:19798")

    def test_has_partial_files_detects_cd2_temp_files(self):
        source = self.watch / "Disc"
        stream_dir = source / "BDMV" / "STREAM"
        stream_dir.mkdir(parents=True)

        for name in ("00001.m2ts.cifstmp", "00800.m2ts.clfstmp", "00800.m2ts.clfstmp.progress"):
            partial = stream_dir / name
            partial.write_bytes(b"in-progress")
            self.assertTrue(app_module.has_partial_files(partial))

        self.assertTrue(app_module.has_partial_files(source))

    def test_empty_or_incomplete_bdmv_does_not_become_ready(self):
        empty = self.make_bdmv("EmptyBDMV", empty=True)
        incomplete = self.make_bdmv("IncompleteBDMV", complete=False)
        keys = [self.mark_candidate_stable(empty), self.mark_candidate_stable(incomplete)]

        with mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(self.scan_config())

        process_item.assert_not_called()
        for key in keys:
            item = app_module.state["items"].get(key)
            self.assertNotEqual("ready", (item or {}).get("status"))

    def test_complete_bdmv_becomes_ready_after_stable(self):
        source = self.make_bdmv("CompleteBDMV", complete=True)
        key = self.mark_candidate_stable(source)

        with mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(self.scan_config())

        self.assertEqual(app_module.state["items"][key]["status"], "ready")
        process_item.assert_called_once()
        self.assertEqual(process_item.call_args.args[0].resolve(), source.resolve())

    def test_scan_once_waits_when_cd2_copy_or_download_task_matches_candidate(self):
        source = self.make_bdmv("PendingFromCD2", complete=True)
        key = self.mark_candidate_stable(source)

        class AttrTask(dict):
            def __getattr__(self, name):
                try:
                    return self[name]
                except KeyError as exc:
                    raise AttributeError(name) from exc

        class FakeTaskResult:
            def __init__(self, tasks):
                self.tasks = tasks
                self.files = tasks
                self.copyTasks = tasks
                self.downloadTasks = tasks
                self.copyFiles = tasks
                self.downloadFiles = tasks
                self.uploadFiles = []
                self.totalCount = len(tasks)
                self.totalBytes = sum(int(task.get("size", 0)) for task in tasks)
                self.finishedBytes = sum(int(task.get("transferedBytes", 0)) for task in tasks)
                self.globalBytesPerSecond = 1

            def __iter__(self):
                return iter(self.tasks)

            def get(self, name, default=None):
                return getattr(self, name, default)

        pending_task = AttrTask({
            "name": source.name,
            "fileName": source.name,
            "path": str(source),
            "destPath": str(source),
            "dstPath": str(source),
            "targetPath": str(source),
            "savePath": str(source),
            "localPath": str(source),
            "filePath": str(source),
            "sourcePath": f"/remote/{source.name}",
            "srcPath": f"/remote/{source.name}",
            "status": "running",
            "statusEnum": "running",
            "state": "running",
            "complete": False,
            "isFinished": False,
            "transferedBytes": 10,
            "finishedBytes": 10,
            "size": 100,
            "totalBytes": 100,
            "progress": 10,
        })

        class FakeCloudDriveClient:
            def __init__(self, addr):
                self.addr = addr
                self.jwt_token = None

            def authenticate(self, username, password):
                return True

            def get_upload_file_list(self, get_all=True):
                return FakeTaskResult([])

            def close(self):
                pass

            def __getattr__(self, name):
                lowered = name.lower()
                if ("copy" in lowered or "download" in lowered) and ("list" in lowered or "task" in lowered):
                    return lambda *args, **kwargs: FakeTaskResult([pending_task])
                raise AttributeError(name)

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient

        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_queue_poll_seconds=1,
        )

        with mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(cfg)

        process_item.assert_not_called()
        self.assertIn(app_module.state["items"][key]["status"], {"waiting_partial", "waiting_stable"})


if __name__ == "__main__":
    unittest.main()
