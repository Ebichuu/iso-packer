import os
import sys
import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual(status["human"], "未发现上传任务")

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


if __name__ == "__main__":
    unittest.main()
