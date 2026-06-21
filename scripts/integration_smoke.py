#!/usr/bin/env python3
"""Local integration smoke test for iso-packer's real ISO toolchain.

This script creates a tiny BDMV-like folder in a temporary workspace, runs the
same genisoimage/xorriso commands used by iso-packer, and optionally simulates
the filesystem transfer step into a local target directory.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_BDMV_DIRS = ("PLAYLIST", "STREAM", "CLIPINF")
TRANSFER_CHUNK_SIZE = 16 * 1024 * 1024


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"missing command: {name}")
    return path


def write_sample_bdmv(root: Path) -> Path:
    source = root / "Sample.BDMV.Smoke"
    bdmv = source / "BDMV"
    bdmv.mkdir(parents=True)
    (bdmv / "index.bdmv").write_bytes(b"INDX0200")
    (bdmv / "MovieObject.bdmv").write_bytes(b"MOBJ0200")
    for dirname in REQUIRED_BDMV_DIRS:
        (bdmv / dirname).mkdir()
    (bdmv / "STREAM" / "00001.m2ts").write_bytes(b"\x47" * 188 * 32)
    (bdmv / "PLAYLIST" / "00001.mpls").write_bytes(b"playlist")
    (bdmv / "CLIPINF" / "00001.clpi").write_bytes(b"clipinfo")
    return source


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip())
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return proc


def copy_with_verify(source: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    final_path = dest_dir / source.name
    tmp_path = final_path.with_name(final_path.name + ".partial")
    if tmp_path.exists():
        tmp_path.unlink()
    with source.open("rb") as src, tmp_path.open("wb") as dst:
        while True:
            chunk = src.read(TRANSFER_CHUNK_SIZE)
            if not chunk:
                break
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    if tmp_path.stat().st_size != source.stat().st_size:
        raise RuntimeError("transfer temp file size mismatch")
    tmp_path.replace(final_path)
    if final_path.stat().st_size != source.stat().st_size:
        raise RuntimeError("transfer final file size mismatch")
    return final_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local ISO toolchain smoke test.")
    parser.add_argument("--workdir", type=Path, help="workspace directory; defaults to a temp directory")
    parser.add_argument("--keep", action="store_true", help="keep the generated workspace")
    parser.add_argument("--transfer-target", type=Path, help="optional local directory for transfer simulation")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        genisoimage = require_tool("genisoimage")
        xorriso = require_tool("xorriso")
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Install genisoimage and xorriso, or run this script inside the project Docker image.", file=sys.stderr)
        return 2

    cleanup_workdir = False
    if args.workdir:
        workdir = args.workdir.resolve()
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        workdir = Path(tempfile.mkdtemp(prefix="iso-packer-smoke-"))
        cleanup_workdir = not args.keep

    try:
        print(f"workspace: {workdir}")
        print(f"genisoimage: {genisoimage}")
        print(f"xorriso: {xorriso}")

        source = write_sample_bdmv(workdir)
        output_dir = workdir / "output"
        output_dir.mkdir()
        iso_path = output_dir / f"{source.name}.iso"
        partial_iso_path = Path(str(iso_path) + ".partial")

        run([
            "genisoimage",
            "-iso-level", "3",
            "-udf",
            "-allow-limited-size",
            "-full-iso9660-filenames",
            "-V", "SAMPLE_BDMV_SMOKE",
            "-o", str(partial_iso_path),
            str(source),
        ], cwd=source.parent)

        if not partial_iso_path.exists() or partial_iso_path.stat().st_size <= 0:
            raise RuntimeError("partial ISO was not created or has zero size")
        partial_iso_path.replace(iso_path)
        if not iso_path.exists() or iso_path.stat().st_size <= 0:
            raise RuntimeError("ISO was not created or has zero size")
        run(["xorriso", "-indev", str(iso_path), "-toc"])
        print(f"ISO validation passed: {iso_path} ({iso_path.stat().st_size} bytes)")

        if args.transfer_target:
            transferred = copy_with_verify(iso_path, args.transfer_target.resolve())
            print(f"transfer simulation passed: {transferred}")

        print("OK: local ISO toolchain smoke test passed")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if args.keep:
            print(f"kept workspace: {workdir}")
        if cleanup_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
