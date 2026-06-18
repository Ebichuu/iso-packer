import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "iso-packer"))

import core


class CoreUtilityTests(unittest.TestCase):
    def test_safe_next_path_rejects_external_urls(self):
        self.assertEqual(core.safe_next_path("/"), "/")
        self.assertEqual(core.safe_next_path("/api/status"), "/api/status")
        self.assertEqual(core.safe_next_path("https://example.com"), "/")
        self.assertEqual(core.safe_next_path("//example.com"), "/")
        self.assertEqual(core.safe_next_path(""), "/")

    def test_normalize_cd2_api_addr_accepts_scheme_or_plain_host(self):
        self.assertEqual(core.normalize_cd2_api_addr("host.docker.internal:19798"), "host.docker.internal:19798")
        self.assertEqual(core.normalize_cd2_api_addr("http://host.docker.internal:19798"), "host.docker.internal:19798")
        self.assertEqual(core.normalize_cd2_api_addr("https://example.com:19798/api"), "example.com:19798")

    def test_path_in_root_blocks_parent_escape(self):
        root = ROOT
        self.assertTrue(core.path_in_root(root / "iso-packer", root))
        self.assertFalse(core.path_in_root(root.parent, root))

    def test_formatting_helpers(self):
        self.assertEqual(core.format_duration(65), "01:05")
        self.assertEqual(core.format_duration(3661), "01:01:01")
        self.assertEqual(core.safe_filename('a/b:c*?'), "a_b_c_")
        self.assertEqual(core.safe_volume_id("蓝光 Dolby Vision"), "_ Dolby Vision")

    def test_apply_task_timings_adds_human_summary(self):
        item = {
            "task_started_at": "2026-06-18 10:00:00",
            "pack_started_at": "2026-06-18 10:00:00",
            "pack_finished_at": "2026-06-18 10:10:00",
            "transfer_started_at": "2026-06-18 10:10:00",
            "transfer_finished_at": "2026-06-18 10:15:00",
            "finished_at": "2026-06-18 10:15:00",
        }
        result = core.apply_task_timings(item)
        self.assertEqual(result["timings"]["durations"]["total"], 900)
        self.assertEqual(result["timings"]["durations"]["pack"], 600)

    def test_sanitize_config_removes_secrets(self):
        result = core.sanitize_config({
            "web_password_hash": "hash",
            "web_secret_key": "secret",
            "cd2_api_password": "cd2-secret",
            "cd2_webhook_secret": "webhook-secret",
            "cd2_auth_mode": "api_token",
            "cd2_api_username": "user",
        })
        self.assertNotIn("web_password_hash", result)
        self.assertNotIn("web_secret_key", result)
        self.assertNotIn("cd2_api_password", result)
        self.assertNotIn("cd2_webhook_secret", result)
        self.assertEqual(result["cd2_auth_mode"], "api_token")
        self.assertEqual(result["cd2_api_username"], "user")

    def test_cd2_path_alias_helpers(self):
        aliases = core.parse_cd2_path_alias_lines("""
        /CloudNAS/CloudDrive=/115
        /mnt/cloud => /remote
        # ignored
        """)
        self.assertEqual(aliases[0], {"local": "/CloudNAS/CloudDrive", "remote": "/115"})
        self.assertIn(
            "/115/00-未整理/Movie.iso",
            core.alias_variants_for_path("/CloudNAS/CloudDrive/00-未整理/Movie.iso", aliases),
        )
        self.assertIn(
            "/CloudNAS/CloudDrive/00-未整理/Movie.iso",
            core.alias_variants_for_path("/115/00-未整理/Movie.iso", aliases),
        )


if __name__ == "__main__":
    unittest.main()
