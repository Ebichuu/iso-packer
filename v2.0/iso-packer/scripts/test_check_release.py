import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("check_release", Path(__file__).with_name("check_release.py"))
check_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_release)


class ReleaseValidationTests(unittest.TestCase):
    def test_version_file_rejects_invalid_or_shell_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "VERSION"
            for invalid in ("v2.1.0", "02.1.0", "2.1.0\nOTHER=oops", "2.1.0; echo bad", ""):
                path.write_text(invalid, encoding="utf-8")
                with self.subTest(version=invalid), self.assertRaises(ValueError):
                    check_release.read_version(path)
            path.write_text("2.1.0\n", encoding="utf-8")
            self.assertEqual(check_release.read_version(path), "2.1.0")

    def test_formal_release_rejects_branch_or_old_tag(self):
        for ref in ("refs/heads/main", "refs/tags/v2.0.2", "", "refs/tags/2.1.0"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                check_release.verify_release_ref("2.1.0", ref, ".")

    @patch.object(check_release, "git_revision", side_effect=["tag-commit", "head-commit"])
    def test_formal_release_rejects_tag_at_other_commit(self, _revision):
        with self.assertRaises(ValueError):
            check_release.verify_release_ref("2.1.0", "refs/tags/v2.1.0", ".")

    @patch.object(check_release, "git_revision", return_value="same-commit")
    def test_formal_release_accepts_exact_matching_tag(self, _revision):
        check_release.verify_release_ref("2.1.0", "refs/tags/v2.1.0", ".")

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_real_annotated_tag_is_bound_to_its_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args):
                subprocess.run(
                    ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgSign=false", *args],
                    cwd=repo,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            git("init", "-q")
            git("config", "user.name", "Release test")
            git("config", "user.email", "release-test@example.invalid")
            (repo / "VERSION").write_text("2.1.0\n", encoding="utf-8")
            git("add", "VERSION")
            git("commit", "-qm", "release candidate")
            git("tag", "-a", "v2.1.0", "-m", "release candidate")
            check_release.verify_release_ref("2.1.0", "refs/tags/v2.1.0", repo)
            (repo / "later-change").touch()
            git("add", "later-change")
            git("commit", "-qm", "later commit")
            with self.assertRaises(ValueError):
                check_release.verify_release_ref("2.1.0", "refs/tags/v2.1.0", repo)

    @patch.object(check_release, "read_version", return_value="2.1.0")
    def test_docker_build_rejects_mismatched_version(self, _version):
        self.assertEqual(check_release.main(["--expect-version", "2.0.2"]), 1)


if __name__ == "__main__":
    unittest.main()
