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


if __name__ == "__main__":
    unittest.main()
