"""Read the application version and validate immutable release provenance."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


def read_version(path=VERSION_FILE):
    version = Path(path).read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("VERSION must contain a stable semantic version, for example 2.1.0")
    return version


def git_revision(repo, ref="HEAD"):
    return subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def verify_release_ref(version, ref, repo):
    expected_ref = f"refs/tags/v{version}"
    if ref != expected_ref:
        raise ValueError(f"Formal publishing requires selecting the exact tag {expected_ref}; got {ref or '(empty)'}")
    if git_revision(repo, expected_ref) != git_revision(repo):
        raise ValueError(f"{expected_ref} does not point to the checked-out HEAD")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true", help="Require GITHUB_REF to be the exact VERSION tag at HEAD")
    parser.add_argument("--expect-version", help="Check the Docker build argument against VERSION")
    parser.add_argument("--github-output", type=Path, help="Append validated build metadata to GITHUB_OUTPUT")
    args = parser.parse_args(argv)
    try:
        version = read_version()
        if args.expect_version is not None and args.expect_version != version:
            raise ValueError(f"Build version {args.expect_version!r} does not match VERSION {version!r}")
        if args.release:
            verify_release_ref(version, os.environ.get("GITHUB_REF", ""), VERSION_FILE.parent)
        if args.github_output:
            revision = git_revision(VERSION_FILE.parent)
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"IMAGE_VERSION={version}\nREVISION={revision}\nSHORT_SHA={revision[:12]}\n")
        print(version)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Release validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
