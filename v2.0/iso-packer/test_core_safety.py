import unittest

from core import alias_variants_for_path, parse_cd2_path_alias_lines, safe_next_path


class CoreSafetyTests(unittest.TestCase):
    def test_alias_arrow_separator_maps_the_actual_remote_path(self):
        for separator in ("=", "=>", ","):
            with self.subTest(separator=separator):
                aliases = parse_cd2_path_alias_lines(f"/watch {separator} /remote/watch")
                self.assertEqual(aliases, [{"local": "/watch", "remote": "/remote/watch"}])
                self.assertIn("/remote/watch/Movie", alias_variants_for_path("/watch/Movie", aliases))

    def test_login_next_rejects_browser_normalized_external_urls(self):
        for value in ("//example.com", "/\\example.com", "/\t/example.com", "/\n/example.com", "/\r/example.com", "/\x00/example.com"):
            with self.subTest(value=value):
                self.assertEqual(safe_next_path(value), "/")

    def test_login_next_keeps_local_path_and_query(self):
        self.assertEqual(safe_next_path("/files?root=watch&path=%2Fwatch"), "/files?root=watch&path=%2Fwatch")


if __name__ == "__main__":
    unittest.main()
