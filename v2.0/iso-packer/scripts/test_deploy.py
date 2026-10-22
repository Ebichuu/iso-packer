"""Exercise deployment control flow with a fake Docker CLI, never a daemon."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


DEPLOY_SCRIPT = Path(__file__).resolve().parents[2] / "deploy.sh"
BASH = shutil.which("bash")
if sys.platform == "win32":
    git = shutil.which("git")
    candidates = [Path(git).resolve().parents[1] / "bin/bash.exe"] if git else []
    candidates.append(Path("C:/Program Files/Git/bin/bash.exe"))
    BASH = next((str(path) for path in candidates if path.is_file()), None)


@unittest.skipUnless(BASH, "Bash is required for deployment control-flow tests")
class DeploymentTests(unittest.TestCase):
    def run_deploy(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            shutil.copyfile(DEPLOY_SCRIPT, root / "deploy.sh")
            docker = root / "bin/docker"
            docker.write_text(
                """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$MOCK_CALLS"
case "$1 $2" in
  "compose version"|"compose config") exit 0 ;;
  "compose pull") [[ "$MOCK_MODE" != pull_fail ]]; exit $? ;;
  "compose up") exit 0 ;;
  "compose ps") echo fake-container; exit 0 ;;
  "compose logs") exit 0 ;;
  "inspect --format")
    if [[ "$3" == *Health* ]]; then
      if [[ "$MOCK_MODE" == unhealthy ]]; then echo unhealthy; else echo healthy; fi
    else
      echo running
    fi
    exit 0 ;;
esac
echo "unexpected Docker command" >&2
exit 99
""",
                encoding="utf-8",
            )
            docker.chmod(0o755)
            calls_path = root / "docker-calls.txt"
            env = dict(os.environ, MOCK_CALLS=calls_path.as_posix(), MOCK_MODE=mode)
            result = subprocess.run(
                [BASH, "-c", 'cd -- "$1" || exit; PATH="$PWD/bin:$PATH"; export PATH; exec bash ./deploy.sh', "deploy-test", root.as_posix()],
                env=env,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertTrue(calls_path.exists(), result.stdout + result.stderr)
            calls = calls_path.read_text(encoding="utf-8").splitlines()
            return result, calls

    def test_updates_only_target_and_requires_health(self):
        result, calls = self.run_deploy("healthy")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("compose pull iso-packer-v2", calls)
        self.assertIn("compose up -d --no-deps --no-build iso-packer-v2", calls)
        self.assertFalse(any(" down" in call or " build" in call for call in calls))
        self.assertIn("健康检查通过", result.stdout)

    def test_failed_pull_never_restarts_service(self):
        result, calls = self.run_deploy("pull_fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call.startswith("compose up") for call in calls))
        self.assertNotIn("健康检查通过", result.stdout)

    def test_unhealthy_service_does_not_report_success(self):
        result, calls = self.run_deploy("unhealthy")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("compose logs --tail=50 iso-packer-v2", calls)
        self.assertNotIn("健康检查通过", result.stdout)


if __name__ == "__main__":
    unittest.main()
