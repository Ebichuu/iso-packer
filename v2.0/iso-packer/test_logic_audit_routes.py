"""Offline regressions for file-operation identity and destination boundaries."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class FileOperationLogicAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.watch = self.base / "watch"
        self.output = self.base / "output"
        self.outside = self.base / "outside"
        for directory in (self.watch, self.output, self.outside):
            directory.mkdir()
        self.cfg = copy.deepcopy(app.DEFAULT_CONFIG)
        self.cfg.update(watch_dir=str(self.watch), output_dir=str(self.output), cd2_mount_root=str(self.base / "mount"))
        self.jobs = []
        jobs = self.jobs

        class QueuedThread:
            def __init__(self, target, args=(), **kwargs):
                self.target, self.args = target, args

            def start(self):
                jobs.append(lambda: self.target(*self.args))

        for name, value in {"load_config": lambda: self.cfg, "log": lambda *args: None, "file_operation_tasks": {}, "_process_config": self.cfg}.items():
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(app.threading, "Thread", QueuedThread)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post_action(self, action, source, **kwargs):
        payload = {"action": action, "root": "watch", "paths": [str(source)], **kwargs}
        if action == "delete":
            payload["confirm"] = "DELETE"
        with app.app.test_request_context("/api/file-actions", method="POST", json=payload):
            return app.app.make_response(app.api_file_actions())

    def symlink(self, link, target, is_dir=False):
        try:
            link.symlink_to(target, target_is_directory=is_dir)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")

    def test_delete_of_symlink_must_not_delete_its_actual_target(self):
        actual = self.watch / "actual.iso"
        actual.write_bytes(b"keep actual data")
        alias = self.watch / "alias.iso"
        self.symlink(alias, actual)
        response = self.post_action("delete", alias)
        for job in self.jobs:
            job()
        self.assertTrue(actual.exists(), "selecting a link deleted the actual media file")
        self.assertEqual(response.status_code, 400)

    def test_delete_through_a_linked_parent_is_rejected_even_within_the_same_root(self):
        real = self.watch / "actual-folder"
        real.mkdir()
        source = real / "Movie.iso"
        source.write_bytes(b"preserve")
        alias = self.watch / "folder-alias"
        self.symlink(alias, real, is_dir=True)
        response = self.post_action("delete", alias / source.name)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.jobs, [])
        self.assertEqual(source.read_bytes(), b"preserve")

    def test_queued_delete_must_not_delete_a_replacement_at_the_same_path(self):
        source = self.watch / "Movie.iso"
        source.write_bytes(b"queued original")
        response = self.post_action("delete", source)
        self.assertEqual(response.status_code, 200)
        source.rename(self.watch / "original-kept.iso")
        source.write_bytes(b"replacement must survive")
        self.jobs.pop()()
        self.assertTrue(source.exists(), "queued delete removed a newer replacement")
        self.assertEqual(source.read_bytes(), b"replacement must survive")
        self.assertEqual(app.file_operation_snapshot(response.get_json()["task_id"])["status"], "failed")

    def test_queued_copy_must_not_follow_a_replaced_destination_directory(self):
        source = self.watch / "Movie.iso"
        source.write_bytes(b"media")
        destination = self.output / "target"
        destination.mkdir()
        response = self.post_action("copy", source, destination="custom", destination_path=str(destination))
        self.assertEqual(response.status_code, 200)
        destination.rename(self.output / "target-original")
        self.symlink(destination, self.outside, is_dir=True)
        self.jobs.pop()()
        self.assertFalse((self.outside / source.name).exists(), "copy escaped its allowed root through a swapped directory")

    def test_queued_delete_must_not_follow_a_replaced_source_parent(self):
        directory = self.watch / "folder"
        directory.mkdir()
        source = directory / "Movie.iso"
        source.write_bytes(b"original")
        outside_source = self.outside / source.name
        outside_source.write_bytes(b"outside data")
        response = self.post_action("delete", source)
        self.assertEqual(response.status_code, 200)
        directory.rename(self.watch / "original-folder")
        self.symlink(directory, self.outside, is_dir=True)
        self.jobs.pop()()
        self.assertTrue(outside_source.exists(), "queued delete traversed a swapped parent outside its root")

    def test_copy_must_not_resolve_a_dangling_destination_link_outside_allowed_roots(self):
        source = self.watch / "Movie.iso"
        source.write_bytes(b"media")
        escaped = self.outside / "unexpected.iso"
        self.symlink(self.output / source.name, escaped)
        response = self.post_action("copy", source, destination="output")
        self.assertEqual(response.status_code, 200)
        self.jobs.pop()()
        self.assertFalse(escaped.exists(), "dangling destination link redirected a copy outside allowed roots")

    def test_normal_copy_and_rename_still_work(self):
        source = self.watch / "Movie.iso"
        source.write_bytes(b"media")
        response = self.post_action("copy", source, destination="output")
        self.assertEqual(response.status_code, 200)
        self.jobs.pop()()
        self.assertEqual((self.output / source.name).read_bytes(), b"media")
        response = self.post_action("rename", source, new_name="Renamed.iso")
        self.assertEqual(response.status_code, 200)
        self.jobs.pop()()
        self.assertEqual((self.watch / "Renamed.iso").read_bytes(), b"media")

    def test_copy_into_new_nested_destination_and_move_still_work(self):
        source = self.watch / "Movie.iso"
        source.write_bytes(b"media")
        destination = self.output / "new" / "nested"
        response = self.post_action("copy", source, destination="custom", destination_path=str(destination))
        self.assertEqual(response.status_code, 200)
        self.jobs.pop()()
        self.assertEqual((destination / source.name).read_bytes(), b"media")
        response = self.post_action("move", source, destination="output", confirm="MOVE")
        self.assertEqual(response.status_code, 200)
        self.jobs.pop()()
        self.assertFalse(source.exists())
        self.assertEqual((self.output / source.name).read_bytes(), b"media")

    def test_copy_never_overwrites_an_existing_file(self):
        source = self.watch / "Movie.iso"
        source.write_bytes(b"new media")
        target = self.output / source.name
        target.write_bytes(b"existing media")
        with self.assertRaises(FileExistsError):
            app.exclusive_file_operation_copy(source, target)
        self.assertEqual(target.read_bytes(), b"existing media")

    def test_directory_copy_and_delete_keep_their_normal_semantics(self):
        source = self.watch / "Movie"
        source.mkdir()
        (source / "stream.m2ts").write_bytes(b"stream")
        response = self.post_action("copy", source, destination="output")
        self.assertEqual(response.status_code, 200)
        self.jobs.pop()()
        self.assertEqual((self.output / source.name / "stream.m2ts").read_bytes(), b"stream")
        response = self.post_action("delete", source)
        self.assertEqual(response.status_code, 200)
        self.jobs.pop()()
        self.assertFalse(source.exists())
        self.assertTrue((self.output / source.name).exists())


if __name__ == "__main__":
    unittest.main()
