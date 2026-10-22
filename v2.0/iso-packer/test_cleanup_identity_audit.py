"""File change-time regressions for conservative destructive cleanup."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class CleanupIdentityAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "Movie.V1.iso"
        self.old.write_bytes(b"original-iso-data")
        self.target = self.root / "Movie.V2.iso"
        self.target.write_bytes(b"finished-iso-data")

    def replace_preserving_size_and_mtime(self):
        original = self.old.stat()
        # Separate changes on filesystems that expose a coarse metadata clock.
        time.sleep(0.02)
        self.old.write_bytes(b"unrelated-ISOdata")
        self.assertEqual(self.old.stat().st_size, original.st_size)
        os.utime(self.old, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(self.old.stat().st_mtime_ns, original.st_mtime_ns)

    def test_identity_is_stable_without_a_file_change(self):
        identity = app.cleanup_file_identity(self.old)
        self.assertIsNotNone(identity)
        self.assertEqual(identity, app.cleanup_file_identity(self.old))
        self.assertGreater(identity["st_ctime_ns"], 0)

    def test_same_length_replacement_with_preserved_mtime_changes_identity(self):
        before = app.cleanup_file_identity(self.old)
        self.assertIsNotNone(before)
        self.replace_preserving_size_and_mtime()
        self.assertNotEqual(before, app.cleanup_file_identity(self.old))

    def test_tree_signature_changes_when_child_is_replaced_preserving_mtime(self):
        before = app.tree_signature(self.root)
        self.assertIsNotNone(before)
        self.replace_preserving_size_and_mtime()
        self.assertNotEqual(before, app.tree_signature(self.root))

    def test_replacement_cleanup_retains_same_length_new_content(self):
        source = self.root / "source"
        item = {
            "status": "transfer_done", "task_generation": "current-generation",
            "replacement_cleanup_pending": {
                "generation": "current-generation", "target": str(self.target),
                "target_identity": app.cleanup_file_identity(self.target),
                "candidates": app.capture_replacement_candidates([self.old]),
            },
        }
        state = {"items": {str(source): item}}
        self.replace_preserving_size_and_mtime()
        with patch.object(app, "state", state), patch.object(app, "save_state_locked"), patch.object(app, "log"):
            app.cleanup_replaced_iso_candidates(source, self.target)
        self.assertTrue(self.old.exists(), "A replacement file must survive cleanup of the original ISO")
        self.assertEqual(self.old.read_bytes(), b"unrelated-ISOdata")

    @unittest.skipUnless(os.name == "nt", "Windows metadata API only")
    def test_windows_change_time_read_failure_has_no_usable_identity(self):
        with patch.object(app, "windows_file_change_time_ns", return_value=None):
            self.assertIsNone(app.cleanup_file_identity(self.old))

    @unittest.skipUnless(os.name == "nt", "Windows metadata API only")
    def test_windows_change_time_read_failure_has_no_usable_tree_signature(self):
        with patch.object(app, "windows_file_change_time_ns", return_value=None):
            self.assertIsNone(app.tree_signature(self.root))

    @unittest.skipUnless(os.name == "nt", "Windows metadata API only")
    def test_windows_change_time_is_distinct_from_creation_time(self):
        before = app.windows_file_change_time_ns(self.old)
        created = self.old.stat().st_ctime_ns
        self.replace_preserving_size_and_mtime()
        self.assertEqual(self.old.stat().st_ctime_ns, created)
        self.assertNotEqual(app.windows_file_change_time_ns(self.old), before)


if __name__ == "__main__":
    unittest.main()
