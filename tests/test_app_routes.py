import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "iso-packer"))

import app as app_module
import page as page_module


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

    def test_browse_slash_uses_selected_root(self):
        marker = self.watch / "BrowseRootMarker"
        marker.mkdir()
        self.login()
        response = self.client.get("/api/browse?root=watch&path=/")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(Path(payload["path"]).resolve(), self.watch.resolve())
        self.assertIn("BrowseRootMarker", {entry["name"] for entry in payload["entries"]})

    def test_browse_blocks_root_escape(self):
        self.login()
        response = self.client.get(f"/api/browse?root=watch&path={self.data_dir.parent}")
        self.assertEqual(response.status_code, 403)

    def test_login_next_rejects_external_url(self):
        response = self.client.get("/login?next=https://example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="/"', response.get_data(as_text=True))

    def test_dashboard_script_has_no_literal_newline_in_confirm_string(self):
        match = re.search(r"<script>\s*\(function\(\)\{([\s\S]*?)\}\)\(\);\s*</script>", page_module.PAGE)
        self.assertIsNotNone(match)
        script = match.group(1)
        self.assertIn('\\n\\n文件已手动补齐', script)
        self.assertNotIn(' + "\n\n文件已手动补齐', script)

    def test_dashboard_rows_render_task_progress(self):
        match = re.search(r"<script>\s*\(function\(\)\{([\s\S]*?)\}\)\(\);\s*</script>", page_module.PAGE)
        self.assertIsNotNone(match)
        script = match.group(1)
        self.assertIn("<th>进度</th>", page_module.PAGE)
        self.assertIn("progress: active.progress", script)
        self.assertIn("function renderTableProgress", script)
        self.assertIn("cells[3].innerHTML = renderTableProgress", script)

    def test_dashboard_shows_cd2_auto_pull_status(self):
        match = re.search(r"<script>\s*\(function\(\)\{([\s\S]*?)\}\)\(\);\s*</script>", page_module.PAGE)
        self.assertIsNotNone(match)
        script = match.group(1)
        self.assertIn("function formatCd2AutoPullStatus", script)
        self.assertIn("formatCd2AutoPullStatus(state.cd2 || {})", script)
        self.assertIn("自动拉取已创建", script)

    def test_remote_candidates_table_shows_pull_status(self):
        match = re.search(r"<script>\s*\(function\(\)\{([\s\S]*?)\}\)\(\);\s*</script>", page_module.PAGE)
        self.assertIsNotNone(match)
        script = match.group(1)
        self.assertIn("<th>状态</th>", page_module.PAGE)
        self.assertIn('colspan="6"', page_module.PAGE)
        self.assertIn("item.pull_status_label", script)

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

    def test_cd2_webhook_is_disabled_by_default(self):
        response = self.client.post("/api/cd2/webhook", json={"event": "created"})
        self.assertEqual(response.status_code, 404)

    def test_cd2_webhook_requires_secret(self):
        cfg = app_module.load_config()
        cfg.update({
            "cd2_webhook_enabled": True,
            "cd2_webhook_secret": "shared-secret",
        })
        app_module.save_config(cfg)

        response = self.client.post("/api/cd2/webhook", json={"event": "created"})

        self.assertEqual(response.status_code, 401)

    def test_cd2_webhook_records_event_and_triggers_scan_once(self):
        cfg = app_module.load_config()
        cfg.update({
            "cd2_webhook_enabled": True,
            "cd2_webhook_secret": "shared-secret",
            "cd2_event_debounce_seconds": 0,
            "cd2_event_dedupe_ttl_seconds": 600,
        })
        app_module.save_config(cfg)

        with mock.patch.object(app_module.threading, "Thread") as thread_cls:
            response = self.client.post(
                "/api/cd2/webhook",
                headers={"X-ISO-Packer-Token": "shared-secret"},
                json={"event": "created", "path": "/115/Movie/BDMV"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["scan_triggered"])
        thread_cls.assert_called_once()
        cd2_state = app_module.state["cd2"]["webhook"]
        self.assertEqual(cd2_state["last_event"]["path"], "/115/Movie/BDMV")

        with mock.patch.object(app_module.threading, "Thread") as thread_cls:
            response = self.client.post(
                "/api/cd2/webhook",
                headers={"X-ISO-Packer-Token": "shared-secret"},
                json={"event": "created", "path": "/115/Movie/BDMV"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["duplicate"])
        self.assertFalse(payload["scan_triggered"])
        thread_cls.assert_not_called()

    def test_cd2_refresh_uses_get_sub_files_force_refresh(self):
        class FakeCloudDriveClient:
            calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                self.calls.append((path, force_refresh))
                return []

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_refresh_enabled=True,
            cd2_path_aliases=[
                {"local": str(self.data_dir / "CloudNAS" / "CloudDrive"), "remote": "/115"},
            ],
        )
        local_path = str(self.data_dir / "CloudNAS" / "CloudDrive" / "00-未整理")

        result = app_module.refresh_cd2_directory(cfg, local_path, "test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["path"], "/115/00-未整理")
        self.assertEqual(FakeCloudDriveClient.calls, [("/115/00-未整理", True)])
        self.assertTrue(app_module.state["cd2"]["refresh"]["last_result"]["ok"])

    def test_cd2_remote_candidates_lists_disc_folders(self):
        class FakeFile:
            def __init__(self, name, full_path, is_dir=True, size=0):
                self.name = name
                self.fullPathName = full_path
                self.isDirectory = is_dir
                self.size = size
                self.writeTime = "2026-06-19 10:00:00"

        class FakeCloudDriveClient:
            calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                self.calls.append((path, force_refresh))
                data = {
                    "/115/03-PT": [
                        FakeFile("MovieBD", "/115/03-PT/MovieBD"),
                        FakeFile("MovieDVD", "/115/03-PT/MovieDVD"),
                        FakeFile("NotDisc", "/115/03-PT/NotDisc"),
                    ],
                    "/115/03-PT/MovieBD": [FakeFile("BDMV", "/115/03-PT/MovieBD/BDMV")],
                    "/115/03-PT/MovieDVD": [FakeFile("VIDEO_TS", "/115/03-PT/MovieDVD/VIDEO_TS")],
                    "/115/03-PT/NotDisc": [FakeFile("Extras", "/115/03-PT/NotDisc/Extras")],
                }
                return data.get(path, [])

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_remote_source_dirs=["/115/03-PT"],
        )

        payload = app_module.scan_cd2_remote_candidates(cfg, force_refresh=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual({item["disc_type"] for item in payload["candidates"]}, {"BDMV", "VIDEO_TS"})
        self.assertEqual({item["pull_state"] for item in payload["candidates"]}, {"new"})
        self.assertIn(("/115/03-PT", True), FakeCloudDriveClient.calls)
        self.assertFalse(payload["auto_pull_enabled"])

    def test_cd2_remote_candidates_include_pull_status(self):
        class FakeFile:
            def __init__(self, name, full_path, is_dir=True):
                self.name = name
                self.fullPathName = full_path
                self.isDirectory = is_dir

        class FakeCloudDriveClient:
            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                data = {
                    "/115/03-PT": [
                        FakeFile("PullingBD", "/115/03-PT/PullingBD"),
                        FakeFile("DoneBD", "/115/03-PT/DoneBD"),
                    ],
                    "/115/03-PT/PullingBD": [FakeFile("BDMV", "/115/03-PT/PullingBD/BDMV")],
                    "/115/03-PT/DoneBD": [FakeFile("BDMV", "/115/03-PT/DoneBD/BDMV")],
                }
                return data.get(path, [])

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        pulling_key = str((self.watch / "PullingBD").resolve())
        done_key = str((self.watch / "DoneBD").resolve())
        app_module.state["items"][pulling_key] = {
            "first_seen": "2000-01-01 00:00:00",
            "status": "waiting_cd2_pull",
            "pack_iso": True,
            "cd2_pull_source": "/115/03-PT/PullingBD",
            "cd2_pull_mode": "auto",
        }
        app_module.state["items"][done_key] = {
            "first_seen": "2000-01-01 00:00:00",
            "status": "done",
            "pack_iso": True,
            "cd2_pull_source": "/115/03-PT/DoneBD",
        }
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_local_pull_dir=str(self.watch),
        )

        payload = app_module.scan_cd2_remote_candidates(cfg, force_refresh=True)
        by_name = {item["name"]: item for item in payload["candidates"]}

        self.assertEqual(by_name["PullingBD"]["pull_state"], "active")
        self.assertEqual(by_name["PullingBD"]["pull_item_status"], "waiting_cd2_pull")
        self.assertEqual(by_name["PullingBD"]["pull_mode"], "auto")
        self.assertEqual(by_name["DoneBD"]["pull_state"], "done")
        self.assertEqual(by_name["DoneBD"]["pull_item_status"], "done")

    def test_cd2_remote_candidates_endpoint_without_dirs_is_empty(self):
        self.login()
        response = self.client.get("/api/cd2/remote-candidates")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["candidates"], [])

    def test_cd2_manual_pull_creates_copy_task(self):
        class FakeFile:
            def __init__(self, name, full_path, is_dir=True):
                self.name = name
                self.fullPathName = full_path
                self.isDirectory = is_dir

        class FakeResult:
            success = True
            errorMessage = ""
            resultFilePaths = ["/115/Downloads/MovieBD"]

        class FakeCloudDriveClient:
            copy_calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                if path == "/115/03-PT/MovieBD":
                    return [FakeFile("BDMV", "/115/03-PT/MovieBD/BDMV")]
                return []

            def copy_file(self, paths, dest_path):
                self.copy_calls.append((list(paths), dest_path))
                return FakeResult()

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        cfg = app_module.load_config()
        cfg.update({
            "cd2_api_enabled": True,
            "cd2_auth_mode": "api_token",
            "cd2_api_addr": "127.0.0.1:19798",
            "cd2_api_password": "dummy-token",
            "cd2_remote_source_dirs": ["/115/03-PT"],
            "cd2_manual_pull_enabled": True,
            "cd2_local_pull_dir": str(self.watch),
            "cd2_remote_pull_dest_dir": "/115/Downloads",
        })
        app_module.save_config(cfg)
        self.login()

        response = self.client.post("/api/cd2/pull", data={"path": "/115/03-PT/MovieBD"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(FakeCloudDriveClient.copy_calls, [(["/115/03-PT/MovieBD"], "/115/Downloads")])
        item = app_module.state["items"][str((self.watch / "MovieBD").resolve())]
        self.assertEqual(item["status"], "waiting_cd2_pull")
        self.assertEqual(item["cd2_pull_source"], "/115/03-PT/MovieBD")
        self.assertTrue(app_module.state["cd2"]["pull"]["last_result"]["ok"])

    def test_cd2_manual_pull_progress_takes_priority_over_partial_structure(self):
        source = self.make_bdmv("PullingBD", complete=False)
        key = str(source.resolve())
        app_module.state["items"][key] = {
            "first_seen": "2000-01-01 00:00:00",
            "status": "waiting_cd2_pull",
            "pack_iso": True,
            "last_size": 0,
            "last_changed": "2000-01-01 00:00:00",
            "cd2_pull_source": "/115/03-PT/PullingBD",
            "cd2_pull_dest": "/115/Downloads",
            "cd2_pull_created_at": "2000-01-01 00:00:00",
        }
        task = {
            "kind": "copy",
            "source": "/115/03-PT/PullingBD",
            "target": "/115/Downloads/PullingBD",
            "done": False,
            "human": "CD2 copy running 20.0%",
        }
        cfg = self.scan_config()

        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [], "copy_tasks": [task]})), \
             mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(cfg)

        process_item.assert_not_called()
        item = app_module.state["items"][key]
        self.assertEqual(item["status"], "waiting_cd2_pull")
        self.assertEqual(item["error"], "CD2 copy running 20.0%")
        self.assertTrue(item["cd2_pull_seen_task"])
        self.assertEqual(item["cd2_source_task"], task)

    def test_cd2_manual_pull_requires_enabled(self):
        self.login()
        response = self.client.post("/api/cd2/pull", data={"path": "/115/03-PT/MovieBD"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("未启用", response.get_json()["message"])

    def test_cd2_manual_pull_rejects_outside_source_dir(self):
        cfg = app_module.load_config()
        cfg.update({
            "cd2_manual_pull_enabled": True,
            "cd2_remote_source_dirs": ["/115/03-PT"],
            "cd2_remote_pull_dest_dir": "/115/Downloads",
        })
        app_module.save_config(cfg)
        self.login()

        response = self.client.post("/api/cd2/pull", data={"path": "/115/Other/MovieBD"})

        self.assertEqual(response.status_code, 403)
        self.assertIn("源目录", response.get_json()["message"])

    def test_cd2_auto_pull_disabled_by_default(self):
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_remote_pull_dest_dir="/115/Downloads",
        )

        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [], "copy_tasks": []})), \
             mock.patch.object(app_module, "scan_cd2_remote_candidates") as scan_remote:
            app_module.scan_once(cfg)

        scan_remote.assert_not_called()

    def test_cd2_auto_pull_creates_one_task_from_remote_candidate(self):
        class FakeFile:
            def __init__(self, name, full_path, is_dir=True):
                self.name = name
                self.fullPathName = full_path
                self.isDirectory = is_dir

        class FakeResult:
            success = True
            errorMessage = ""
            resultFilePaths = ["/115/Downloads/MovieBD"]

        class FakeCloudDriveClient:
            copy_calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                data = {
                    "/115/03-PT": [
                        FakeFile("MovieBD", "/115/03-PT/MovieBD"),
                        FakeFile("MovieDVD", "/115/03-PT/MovieDVD"),
                    ],
                    "/115/03-PT/MovieBD": [FakeFile("BDMV", "/115/03-PT/MovieBD/BDMV")],
                    "/115/03-PT/MovieDVD": [FakeFile("VIDEO_TS", "/115/03-PT/MovieDVD/VIDEO_TS")],
                }
                return data.get(path, [])

            def copy_file(self, paths, dest_path):
                self.copy_calls.append((list(paths), dest_path))
                return FakeResult()

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_auto_pull_enabled=True,
            cd2_local_pull_dir=str(self.watch),
            cd2_remote_pull_dest_dir="/115/Downloads",
        )

        unrelated_copy = {
            "kind": "copy",
            "source": "/115/03-PT/OtherBD",
            "target": "/115/Downloads/OtherBD",
            "done": False,
        }
        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [], "copy_tasks": [unrelated_copy]})), \
             mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(cfg)

        process_item.assert_not_called()
        self.assertEqual(FakeCloudDriveClient.copy_calls, [(["/115/03-PT/MovieBD"], "/115/Downloads")])
        item = app_module.state["items"][str((self.watch / "MovieBD").resolve())]
        self.assertEqual(item["status"], "waiting_cd2_pull")
        self.assertEqual(item["cd2_pull_mode"], "auto")
        self.assertEqual(item["cd2_pull_source"], "/115/03-PT/MovieBD")
        self.assertTrue(app_module.state["cd2"]["auto_pull"]["last_result"]["created"])
        self.assertEqual(app_module.state["cd2"]["auto_pull"]["last_result"]["created_count"], 1)

    def test_cd2_auto_pull_respects_max_tasks_per_scan(self):
        class FakeFile:
            def __init__(self, name, full_path, is_dir=True):
                self.name = name
                self.fullPathName = full_path
                self.isDirectory = is_dir

        class FakeResult:
            success = True
            errorMessage = ""
            resultFilePaths = []

        class FakeCloudDriveClient:
            copy_calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                data = {
                    "/115/03-PT": [
                        FakeFile("MovieA", "/115/03-PT/MovieA"),
                        FakeFile("MovieB", "/115/03-PT/MovieB"),
                        FakeFile("MovieC", "/115/03-PT/MovieC"),
                    ],
                    "/115/03-PT/MovieA": [FakeFile("BDMV", "/115/03-PT/MovieA/BDMV")],
                    "/115/03-PT/MovieB": [FakeFile("BDMV", "/115/03-PT/MovieB/BDMV")],
                    "/115/03-PT/MovieC": [FakeFile("BDMV", "/115/03-PT/MovieC/BDMV")],
                }
                return data.get(path, [])

            def copy_file(self, paths, dest_path):
                self.copy_calls.append((list(paths), dest_path))
                return FakeResult()

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_auto_pull_enabled=True,
            cd2_auto_pull_max_tasks_per_scan=2,
            cd2_local_pull_dir=str(self.watch),
            cd2_remote_pull_dest_dir="/115/Downloads",
        )

        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [], "copy_tasks": []})), \
             mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(cfg)

        process_item.assert_not_called()
        self.assertEqual(FakeCloudDriveClient.copy_calls, [
            (["/115/03-PT/MovieA"], "/115/Downloads"),
            (["/115/03-PT/MovieB"], "/115/Downloads"),
        ])
        result = app_module.state["cd2"]["auto_pull"]["last_result"]
        self.assertTrue(result["created"])
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(len(result["created_tasks"]), 2)
        self.assertIn("本轮已创建 2 个", result["message"])

    def test_cd2_auto_pull_filters_candidates_by_keywords(self):
        class FakeFile:
            def __init__(self, name, full_path, is_dir=True):
                self.name = name
                self.fullPathName = full_path
                self.isDirectory = is_dir

        class FakeResult:
            success = True
            errorMessage = ""
            resultFilePaths = []

        class FakeCloudDriveClient:
            copy_calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                data = {
                    "/115/03-PT": [
                        FakeFile("MovieKeep.UHD", "/115/03-PT/MovieKeep.UHD"),
                        FakeFile("MovieSkip.UHD", "/115/03-PT/MovieSkip.UHD"),
                        FakeFile("OtherMovie", "/115/03-PT/OtherMovie"),
                    ],
                    "/115/03-PT/MovieKeep.UHD": [FakeFile("BDMV", "/115/03-PT/MovieKeep.UHD/BDMV")],
                    "/115/03-PT/MovieSkip.UHD": [FakeFile("BDMV", "/115/03-PT/MovieSkip.UHD/BDMV")],
                    "/115/03-PT/OtherMovie": [FakeFile("BDMV", "/115/03-PT/OtherMovie/BDMV")],
                }
                return data.get(path, [])

            def copy_file(self, paths, dest_path):
                self.copy_calls.append((list(paths), dest_path))
                return FakeResult()

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_auto_pull_enabled=True,
            cd2_auto_pull_max_tasks_per_scan=3,
            cd2_auto_pull_include_keywords="UHD",
            cd2_auto_pull_exclude_keywords="Skip",
            cd2_local_pull_dir=str(self.watch),
            cd2_remote_pull_dest_dir="/115/Downloads",
        )

        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [], "copy_tasks": []})), \
             mock.patch.object(app_module, "process_item"):
            app_module.scan_once(cfg)

        self.assertEqual(FakeCloudDriveClient.copy_calls, [
            (["/115/03-PT/MovieKeep.UHD"], "/115/Downloads"),
        ])
        result = app_module.state["cd2"]["auto_pull"]["last_result"]
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(len(result["skipped"]), 2)

    def test_cd2_auto_pull_does_not_duplicate_existing_source(self):
        class FakeFile:
            def __init__(self, name, full_path, is_dir=True):
                self.name = name
                self.fullPathName = full_path
                self.isDirectory = is_dir

        class FakeCloudDriveClient:
            copy_calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                if path == "/115/03-PT":
                    return [FakeFile("MovieBD", "/115/03-PT/MovieBD")]
                if path == "/115/03-PT/MovieBD":
                    return [FakeFile("BDMV", "/115/03-PT/MovieBD/BDMV")]
                return []

            def copy_file(self, paths, dest_path):
                self.copy_calls.append((list(paths), dest_path))
                raise AssertionError("duplicate pull should not be created")

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        app_module.state["items"][str((self.watch / "MovieBD").resolve())] = {
            "first_seen": "2000-01-01 00:00:00",
            "status": "done",
            "pack_iso": True,
            "cd2_pull_source": "/115/03-PT/MovieBD",
        }
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_auto_pull_enabled=True,
            cd2_local_pull_dir=str(self.watch),
            cd2_remote_pull_dest_dir="/115/Downloads",
        )

        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [], "copy_tasks": []})):
            app_module.scan_once(cfg)

        self.assertEqual(FakeCloudDriveClient.copy_calls, [])

    def test_cd2_auto_pull_requires_dest_dir_before_remote_scan(self):
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_auto_pull_enabled=True,
            cd2_remote_pull_dest_dir="",
            cd2_path_aliases=[],
        )

        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [], "copy_tasks": []})), \
             mock.patch.object(app_module, "scan_cd2_remote_candidates") as scan_remote:
            app_module.scan_once(cfg)

        scan_remote.assert_not_called()
        self.assertFalse(app_module.state["cd2"]["auto_pull"]["last_result"]["ok"])

    def test_cd2_auto_pull_failure_cooldown_skips_recent_failure(self):
        app_module.record_cd2_pull_result("/115/03-PT/MovieBD", "/115/Downloads", False, "copy failed")
        cfg = self.scan_config(
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_auto_pull_failure_cooldown_seconds=600,
            cd2_local_pull_dir=str(self.watch),
            cd2_remote_pull_dest_dir="/115/Downloads",
        )
        local_source = app_module.cd2_local_pull_path_for_source(cfg, "/115/03-PT/MovieBD")

        self.assertTrue(app_module.cd2_pull_recent_failure("/115/03-PT/MovieBD", 600))
        result, status_code = app_module.create_cd2_pull_task(cfg, "/115/03-PT/MovieBD", mode="auto")

        self.assertEqual(status_code, 409)
        self.assertFalse(result["ok"])
        self.assertIn("最近自动拉取失败", result["message"])
        self.assertNotIn(str(local_source), app_module.state["items"])

    def test_cd2_auto_pull_failure_cooldown_zero_allows_retry(self):
        class FakeFile:
            def __init__(self, name, full_path, is_dir=True):
                self.name = name
                self.fullPathName = full_path
                self.isDirectory = is_dir

        class FakeResult:
            success = True
            errorMessage = ""
            resultFilePaths = ["/115/Downloads/MovieBD"]

        class FakeCloudDriveClient:
            copy_calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                if path == "/115/03-PT/MovieBD":
                    return [FakeFile("BDMV", "/115/03-PT/MovieBD/BDMV")]
                return []

            def copy_file(self, paths, dest_path):
                self.copy_calls.append((list(paths), dest_path))
                return FakeResult()

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        app_module.record_cd2_pull_result("/115/03-PT/MovieBD", "/115/Downloads", False, "copy failed")
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_remote_source_dirs=["/115/03-PT"],
            cd2_auto_pull_failure_cooldown_seconds=0,
            cd2_local_pull_dir=str(self.watch),
            cd2_remote_pull_dest_dir="/115/Downloads",
        )

        result, status_code = app_module.create_cd2_pull_task(cfg, "/115/03-PT/MovieBD", mode="auto")

        self.assertEqual(status_code, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(FakeCloudDriveClient.copy_calls, [(["/115/03-PT/MovieBD"], "/115/Downloads")])

    def test_cd2_webhook_refreshes_source_before_scan(self):
        class FakeCloudDriveClient:
            calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                self.calls.append((path, force_refresh))
                return []

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        cfg = app_module.load_config()
        cfg.update({
            "cd2_api_enabled": True,
            "cd2_auth_mode": "api_token",
            "cd2_api_addr": "127.0.0.1:19798",
            "cd2_api_password": "dummy-token",
            "cd2_webhook_enabled": True,
            "cd2_webhook_secret": "shared-secret",
            "cd2_refresh_enabled": True,
            "cd2_refresh_after_source_event": True,
            "cd2_path_aliases": [
                {"local": str(self.data_dir / "CloudNAS" / "CloudDrive"), "remote": "/115"},
            ],
        })
        app_module.save_config(cfg)

        with mock.patch.object(app_module.threading, "Thread") as thread_cls:
            response = self.client.post(
                "/api/cd2/webhook",
                headers={"X-ISO-Packer-Token": "shared-secret"},
                json={"event": "created", "path": "/115/Movie/BDMV"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["scan_triggered"])
        self.assertEqual(FakeCloudDriveClient.calls, [("/115/Movie/BDMV", True)])
        thread_cls.assert_called_once()

    def test_transfer_refreshes_cd2_target_directory(self):
        class FakeCloudDriveClient:
            calls = []

            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                self.calls.append((path, force_refresh))
                return []

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        source_iso = self.output / "RefreshAfterTransfer.iso"
        source_iso.write_bytes(b"iso")
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_transfer_enabled=True,
            cd2_require_mount=False,
            cd2_refresh_enabled=True,
            cd2_refresh_after_transfer=True,
            cd2_path_aliases=[
                {"local": str(self.data_dir / "CloudNAS" / "CloudDrive"), "remote": "/115"},
            ],
        )

        result = app_module.transfer_iso_to_mount(source_iso, cfg)

        self.assertIsNotNone(result)
        self.assertFalse(source_iso.exists())
        self.assertTrue(result.exists())
        transfer_log = "\n".join(app_module.state.get("events", []))
        self.assertIn(f"已删除输出目录临时ISO: {source_iso}", transfer_log)
        self.assertIn(f"目标文件保留: {result}", transfer_log)
        self.assertEqual(FakeCloudDriveClient.calls, [("/115/00-未整理/00-mkiso", True)])

    def test_transfer_marks_active_refreshing_cd2_directory(self):
        class FakeCloudDriveClient:
            def __init__(self, addr):
                self.jwt_token = None

            def get_sub_files(self, path, force_refresh=False):
                return []

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient
        source = str(self.watch / "RefreshStatus")
        source_iso = self.output / "RefreshStatus.iso"
        source_iso.write_bytes(b"iso")
        app_module.state["items"][source] = {"status": "transferring"}
        app_module.state["active"] = {
            "source": source,
            "target": str(source_iso),
            "status": "transferring",
            "progress": {"phase": "transfer", "percent": 100, "current": 3, "total": 3},
        }
        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_transfer_enabled=True,
            cd2_require_mount=False,
            cd2_refresh_enabled=True,
            cd2_refresh_after_transfer=True,
            cd2_path_aliases=[
                {"local": str(self.data_dir / "CloudNAS" / "CloudDrive"), "remote": "/115"},
            ],
        )

        result = app_module.transfer_iso_to_mount(source_iso, cfg)

        self.assertIsNotNone(result)
        self.assertEqual(app_module.state["active"]["status"], "refreshing_cd2_dir")
        self.assertEqual(app_module.state["active"]["progress"]["phase"], "refresh_cd2_dir")
        self.assertEqual(app_module.state["items"][source]["status"], "refreshing_cd2_dir")

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
            "cd2_upload_match_mode": "alias_only",
            "cd2_event_debounce_seconds": "5",
            "cd2_event_dedupe_ttl_seconds": "60",
            "cd2_confirm_delay_seconds": "15",
            "cd2_confirm_stable_checks": "2",
            "cd2_auto_pull_max_tasks_per_scan": "3",
            "cd2_auto_pull_failure_cooldown_seconds": "30",
            "cd2_refresh_enabled": "on",
            "cd2_refresh_after_source_event": "on",
            "cd2_refresh_after_transfer": "on",
            "cd2_path_aliases_text": f"{self.data_dir / 'CloudNAS' / 'CloudDrive'}=/115",
            "cd2_remote_source_dirs_text": "/115/03-PT\n/115/04-BDMV",
            "cd2_manual_pull_enabled": "on",
            "cd2_auto_pull_enabled": "on",
            "cd2_auto_pull_include_keywords": "UHD\nCHDBits",
            "cd2_auto_pull_exclude_keywords": "sample\ntrailer",
            "cd2_local_pull_dir": str(self.watch),
            "cd2_remote_pull_dest_dir": "/115/Downloads",
            "cd2_webhook_enabled": "on",
            "cd2_webhook_secret": "webhook-secret",
            "cd2_event_source": "symedia",
            "enabled": "on",
            "delete_source_after_success": "on",
            "cd2_transfer_enabled": "on",
            "cd2_wait_upload_complete": "on",
            "cd2_require_mount": "1",
        })

        self.assertEqual(response.status_code, 302)
        cfg = app_module.load_config()
        self.assertEqual(cfg["cd2_auth_mode"], "password")
        self.assertEqual(cfg["cd2_api_addr"], "127.0.0.1:19798")
        self.assertEqual(cfg["cd2_path_aliases"][0]["remote"], "/115")
        self.assertEqual(cfg["cd2_upload_match_mode"], "alias_only")
        self.assertTrue(cfg["cd2_wait_upload_complete"])
        self.assertTrue(cfg["cd2_webhook_enabled"])
        self.assertEqual(cfg["cd2_webhook_secret"], "webhook-secret")
        self.assertEqual(cfg["cd2_event_source"], "symedia")
        self.assertEqual(cfg["cd2_event_debounce_seconds"], 5)
        self.assertEqual(cfg["cd2_event_dedupe_ttl_seconds"], 60)
        self.assertEqual(cfg["cd2_confirm_delay_seconds"], 15)
        self.assertEqual(cfg["cd2_confirm_stable_checks"], 2)
        self.assertEqual(cfg["cd2_auto_pull_max_tasks_per_scan"], 3)
        self.assertEqual(cfg["cd2_auto_pull_failure_cooldown_seconds"], 30)
        self.assertTrue(cfg["cd2_refresh_enabled"])
        self.assertTrue(cfg["cd2_refresh_after_source_event"])
        self.assertTrue(cfg["cd2_refresh_after_transfer"])
        self.assertEqual(cfg["cd2_remote_source_dirs"], ["/115/03-PT", "/115/04-BDMV"])
        self.assertTrue(cfg["cd2_manual_pull_enabled"])
        self.assertTrue(cfg["cd2_auto_pull_enabled"])
        self.assertEqual(cfg["cd2_auto_pull_include_keywords"], "UHD\nCHDBits")
        self.assertEqual(cfg["cd2_auto_pull_exclude_keywords"], "sample\ntrailer")
        self.assertEqual(cfg["cd2_local_pull_dir"], str(self.watch))
        self.assertEqual(cfg["cd2_remote_pull_dest_dir"], "/115/Downloads")

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

    def test_cd2_webhook_candidate_waits_for_confirm_before_ready(self):
        source = self.make_bdmv("WebhookConfirmBDMV", complete=True)
        key = self.mark_candidate_stable(source)
        cfg = self.scan_config(
            cd2_confirm_delay_seconds=30,
            cd2_confirm_stable_checks=1,
            cd2_path_aliases=[
                {"local": str(self.watch), "remote": "/115"},
            ],
        )
        event = {
            "event": "created",
            "path": f"/115/{source.name}/BDMV",
        }
        app_module.record_cd2_webhook_event(cfg, event)

        with mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(cfg)

        process_item.assert_not_called()
        item = app_module.state["items"][key]
        self.assertEqual(item["status"], "waiting_cd2_confirm")
        self.assertIn("cd2_confirm_event_id", item)

        item["cd2_confirm_started_at"] = "2000-01-01 00:00:00"
        with mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(cfg)

        self.assertEqual(app_module.state["items"][key]["status"], "ready")
        process_item.assert_called_once()

    def test_cd2_webhook_confirm_still_respects_pending_download_gate(self):
        source = self.make_bdmv("WebhookPendingBDMV", complete=True)
        key = self.mark_candidate_stable(source)
        cfg = self.scan_config(
            cd2_confirm_delay_seconds=0,
            cd2_confirm_stable_checks=1,
            cd2_path_aliases=[
                {"local": str(self.watch), "remote": "/115"},
            ],
        )
        app_module.record_cd2_webhook_event(cfg, {"event": "created", "path": f"/115/{source.name}/BDMV"})
        pending_task = {
            "kind": "download",
            "path": f"/115/{source.name}",
            "done": False,
            "human": "CD2 下载中 50.0%",
        }

        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [pending_task], "copy_tasks": []})), \
             mock.patch.object(app_module, "process_item") as process_item:
            app_module.scan_once(cfg)

        process_item.assert_not_called()
        item = app_module.state["items"][key]
        self.assertEqual(item["status"], "waiting_partial")
        self.assertIn("CD2 下载中", item["error"])

    def test_process_item_clears_previous_error_when_started(self):
        source = self.make_bdmv("RetryClearsError", complete=True)
        key = str(source)
        app_module.state["items"][key] = {
            "status": "failed",
            "error": "old genisoimage error",
            "reason": "old reason",
            "last_error": "old last error",
            "cd2_source_task": {"kind": "download"},
            "pack_iso": True,
        }

        with mock.patch.object(app_module, "run_iso", side_effect=RuntimeError("stop after start")):
            app_module.process_item(source, self.scan_config())

        item = app_module.state["items"][key]
        self.assertNotIn("old genisoimage error", item.get("error", ""))
        self.assertNotIn("reason", item)
        self.assertNotIn("last_error", item)
        self.assertNotIn("cd2_source_task", item)

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

    def test_completed_cd2_download_does_not_block_candidate(self):
        source = self.make_bdmv("CompletedDownload", complete=True)
        task = {
            "kind": "download",
            "path": str(source),
            "key": str(source),
            "status": "Completed",
            "current": 100,
            "total": 100,
            "done": True,
            "human": "CD2 下载完成",
        }

        pending = app_module.cd2_pending_source_task(source, {
            "connected": True,
            "downloads": [task],
            "copy_tasks": [],
        })

        self.assertIsNone(pending)

    def test_full_cd2_copy_progress_does_not_block_candidate(self):
        source = self.make_bdmv("CompletedCopy", complete=True)
        task = {
            "kind": "copy",
            "source": str(source),
            "target": str(source),
            "status": "running",
            "current": 77_560_000_000,
            "total": 77_560_000_000,
            "done_files": 621,
            "total_files": 621,
            "failed_files": 0,
            "percent": 100.0,
            "done": True,
            "human": "CD2 复制完成 100.0%",
        }

        pending = app_module.cd2_pending_source_task(source, {
            "connected": True,
            "downloads": [],
            "copy_tasks": [task],
        })

        self.assertIsNone(pending)

    def test_rerun_can_force_past_cd2_pending_task(self):
        self.login()
        source = self.make_bdmv("ForcePastCd2", complete=True)
        pending_task = {
            "kind": "download",
            "path": str(source),
            "key": str(source),
            "status": "running",
            "current": 99,
            "total": 100,
            "done": False,
            "human": "CD2 下载中 99.0%",
        }
        cfg = self.scan_config()

        with mock.patch.object(app_module, "load_config", return_value=cfg), \
             mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [pending_task], "copy_tasks": []})), \
             mock.patch.object(app_module.threading, "Thread") as thread_cls:
            response = self.client.post("/rerun", data={"source": str(source), "force_cd2": "1"})

        self.assertEqual(response.status_code, 200)
        key = str(source.resolve())
        self.assertTrue(app_module.state["items"][key]["manual_force_cd2"])
        thread_cls.assert_called_once()

    def test_rerun_without_force_still_blocks_cd2_pending_task(self):
        self.login()
        source = self.make_bdmv("BlockPendingCd2", complete=True)
        pending_task = {
            "kind": "download",
            "path": str(source),
            "key": str(source),
            "status": "running",
            "current": 99,
            "total": 100,
            "done": False,
            "human": "CD2 下载中 99.0%",
        }
        cfg = self.scan_config()

        with mock.patch.object(app_module, "load_config", return_value=cfg), \
             mock.patch.object(app_module, "fetch_cd2_uploads", return_value=({}, {"connected": True, "downloads": [pending_task], "copy_tasks": []})), \
             mock.patch.object(app_module.threading, "Thread") as thread_cls:
            response = self.client.post("/rerun", data={"source": str(source)})

        self.assertEqual(response.status_code, 409)
        self.assertIn("CD2", response.get_json()["message"])
        thread_cls.assert_not_called()

    def test_cd2_download_queue_failure_keeps_upload_status_connected(self):
        class UploadResult:
            totalCount = 0
            totalBytes = 0
            finishedBytes = 0
            globalBytesPerSecond = 0
            uploadFiles = []

        class FakeCloudDriveClient:
            def __init__(self, addr):
                self.addr = addr
                self.jwt_token = None

            def authenticate(self, username, password):
                return True

            def get_upload_file_list(self, get_all=True):
                return UploadResult()

            def get_download_file_list(self):
                raise PermissionError("permission denied")

            def get_copy_tasks(self):
                class CopyResult:
                    copyTasks = []
                return CopyResult()

            def close(self):
                pass

        self.original_cd2_client = app_module.CloudDriveClient
        app_module.CloudDriveClient = FakeCloudDriveClient

        cfg = self.scan_config(
            cd2_api_enabled=True,
            cd2_auth_mode="api_token",
            cd2_api_addr="127.0.0.1:19798",
            cd2_api_password="dummy-token",
            cd2_queue_poll_seconds=1,
        )

        upload_map, status = app_module.fetch_cd2_uploads(cfg)

        self.assertEqual({}, upload_map)
        self.assertTrue(status["connected"])
        self.assertIn("下载任务读取失败", status["last_error"])
        self.assertEqual([], status["downloads"])

    def test_cd2_upload_matches_cloudnas_target_by_alias(self):
        source_key = str(self.watch / "Movie")
        target = self.cd2 / "Movie.iso"
        upload = {
            "path": "/115/00-未整理/00-mkiso/Movie.iso",
            "human": "42.0%",
        }
        other_upload = {
            "path": "/115/Other/Movie.iso",
            "human": "10.0%",
        }
        cfg = self.scan_config(
            cd2_mount_root=str(self.data_dir / "CloudNAS"),
            cd2_target_dir=str(self.cd2),
            cd2_path_aliases=[
                {"local": str(self.data_dir / "CloudNAS" / "CloudDrive"), "remote": "/115"}
            ],
        )
        items = {
            source_key: {
                "target": str(target),
                "pack_iso": True,
            }
        }

        with mock.patch.object(app_module, "fetch_cd2_uploads", return_value=(
            {
                app_module.normalize_upload_path(other_upload["path"]): other_upload,
                app_module.normalize_upload_path(upload["path"]): upload,
            },
            {"uploads": [other_upload, upload]},
        )):
            enriched, active, _ = app_module.attach_cd2_uploads(cfg, items, None)

        self.assertIsNone(active)
        self.assertEqual(enriched[source_key]["cd2_upload"], upload)

    def test_cd2_upload_match_mode_alias_only_rejects_suffix_fallback(self):
        target = self.cd2 / "Movie.iso"
        upload = {
            "path": "/115/Other/Movie.iso",
            "human": "42.0%",
        }
        cfg = self.scan_config(
            cd2_upload_match_mode="alias_only",
            cd2_mount_root=str(self.data_dir / "CloudNAS"),
            cd2_target_dir=str(self.cd2),
            cd2_path_aliases=[
                {"local": str(self.data_dir / "CloudNAS" / "CloudDrive"), "remote": "/115"}
            ],
        )
        upload_map = {app_module.normalize_upload_path(upload["path"]): upload}

        self.assertIsNone(app_module.find_upload_for_path(upload_map, str(target), cfg))

    def test_cd2_upload_match_mode_alias_then_suffix_keeps_existing_fallback(self):
        target = self.cd2 / "Movie.iso"
        upload = {
            "path": "/115/Other/Movie.iso",
            "human": "42.0%",
        }
        cfg = self.scan_config(
            cd2_upload_match_mode="alias_then_suffix",
            cd2_mount_root=str(self.data_dir / "CloudNAS"),
            cd2_target_dir=str(self.cd2),
            cd2_path_aliases=[
                {"local": str(self.data_dir / "CloudNAS" / "CloudDrive"), "remote": "/115"}
            ],
        )
        upload_map = {app_module.normalize_upload_path(upload["path"]): upload}

        self.assertEqual(app_module.find_upload_for_path(upload_map, str(target), cfg), upload)

    def test_waiting_cd2_upload_stays_until_upload_done(self):
        key = str(self.watch / "UploadWait")
        target = self.cd2 / "UploadWait.iso"
        app_module.state["items"][key] = {
            "status": "waiting_cd2_upload",
            "target": str(target),
            "pack_iso": True,
            "cd2_upload_wait_started_at": "2000-01-01 00:00:00",
        }
        cfg = self.scan_config(
            cd2_wait_upload_complete=True,
            cd2_path_aliases=[
                {"local": str(self.data_dir / "CloudNAS" / "CloudDrive"), "remote": "/115"}
            ],
        )
        upload = {
            "path": "/115/00-未整理/00-mkiso/UploadWait.iso",
            "current": 10,
            "total": 100,
            "percent": 10.0,
            "human": "10.0%",
        }
        upload_map = {app_module.normalize_upload_path(upload["path"]): upload}

        app_module.check_waiting_cd2_uploads(cfg, upload_map, {"connected": True, "checked_at": app_module.now()})
        self.assertEqual(app_module.state["items"][key]["status"], "waiting_cd2_upload")
        self.assertIn("等待 CD2 上传完成", app_module.state["items"][key]["error"])
        self.assertIn("cd2_upload_seen_at", app_module.state["items"][key])

        upload["current"] = 100
        upload["percent"] = 100.0
        app_module.check_waiting_cd2_uploads(cfg, upload_map, {"connected": True, "checked_at": app_module.now()})
        self.assertEqual(app_module.state["items"][key]["status"], "transfer_done")
        self.assertIn("finished_at", app_module.state["items"][key])
        self.assertIn("cd2_upload_done_at", app_module.state["items"][key])

    def test_waiting_cd2_upload_waits_for_queue_to_appear(self):
        key = str(self.watch / "UploadPendingQueue")
        target = self.cd2 / "UploadPendingQueue.iso"
        app_module.state["items"][key] = {
            "status": "waiting_cd2_upload",
            "target": str(target),
            "pack_iso": True,
            "cd2_upload_wait_started_at": (datetime.now() - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        cfg = self.scan_config(cd2_wait_upload_complete=True, cd2_queue_poll_seconds=10)

        app_module.check_waiting_cd2_uploads(cfg, {}, {"connected": True, "checked_at": app_module.now()})

        item = app_module.state["items"][key]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertIn("等待 CD2 上传队列出现", item["error"])
        self.assertNotIn("finished_at", item)

    def test_waiting_cd2_upload_finishes_when_seen_queue_disappears(self):
        key = str(self.watch / "UploadQueueCleared")
        target = self.cd2 / "UploadQueueCleared.iso"
        app_module.state["items"][key] = {
            "status": "waiting_cd2_upload",
            "target": str(target),
            "pack_iso": True,
            "cd2_upload_seen_at": "2000-01-01 00:00:00",
            "cd2_upload_wait_started_at": "2000-01-01 00:00:00",
        }
        cfg = self.scan_config(cd2_wait_upload_complete=True)

        app_module.check_waiting_cd2_uploads(cfg, {}, {"connected": True, "checked_at": app_module.now()})

        item = app_module.state["items"][key]
        self.assertEqual(item["status"], "transfer_done")
        self.assertIn("cd2_upload_done_at", item)

    def test_waiting_cd2_upload_does_not_complete_without_matching_queue(self):
        key = str(self.watch / "UploadNoMatch")
        target = self.cd2 / "UploadNoMatch.iso"
        app_module.state["items"][key] = {
            "status": "waiting_cd2_upload",
            "target": str(target),
            "pack_iso": True,
            "cd2_upload_wait_started_at": "2000-01-01 00:00:00",
        }
        cfg = self.scan_config(cd2_wait_upload_complete=True)

        app_module.check_waiting_cd2_uploads(cfg, {}, {"connected": True, "checked_at": app_module.now()})

        item = app_module.state["items"][key]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertIn("未在 CD2 上传队列找到匹配任务", item["error"])
        self.assertNotIn("finished_at", item)

    def test_waiting_cd2_upload_ignores_stale_cd2_snapshot(self):
        key = str(self.watch / "UploadStaleSnapshot")
        target = self.cd2 / "UploadStaleSnapshot.iso"
        app_module.state["items"][key] = {
            "status": "waiting_cd2_upload",
            "target": str(target),
            "pack_iso": True,
            "cd2_upload_wait_started_at": "2099-01-01 00:00:00",
        }
        cfg = self.scan_config(cd2_wait_upload_complete=True)

        app_module.check_waiting_cd2_uploads(cfg, {}, {"connected": True, "checked_at": "2000-01-01 00:00:00"})

        item = app_module.state["items"][key]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertEqual(item["error"], "等待 CD2 上传队列刷新")
        self.assertNotIn("finished_at", item)

    def test_waiting_cd2_upload_does_not_complete_when_cd2_disconnected(self):
        key = str(self.watch / "UploadDisconnected")
        target = self.cd2 / "UploadDisconnected.iso"
        app_module.state["items"][key] = {
            "status": "waiting_cd2_upload",
            "target": str(target),
            "pack_iso": True,
        }
        cfg = self.scan_config(cd2_wait_upload_complete=True)

        app_module.check_waiting_cd2_uploads(cfg, {}, {"connected": False, "human": "CD2 API 未连接"})

        item = app_module.state["items"][key]
        self.assertEqual(item["status"], "waiting_cd2_upload")
        self.assertIn("CD2 API 未连接", item["error"])


if __name__ == "__main__":
    unittest.main()
