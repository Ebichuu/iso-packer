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


if __name__ == "__main__":
    unittest.main()
