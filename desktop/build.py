"""Build script: freeze the Python backend with PyInstaller and rename
the output to Tauri's target-triple convention. Run from repo root or
from the desktop/ directory.

Usage:
    python desktop/build.py            # freeze backend only
    python desktop/build.py --tauri    # also run `tauri build`
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP = REPO_ROOT / "desktop"
SRC_TAURI = DESKTOP / "src-tauri"
BINARIES = SRC_TAURI / "binaries"
SPEC = SRC_TAURI / "lk-backend.spec"


def target_triple() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        if machine in ("arm64", "aarch64"):
            return "aarch64-apple-darwin"
        return "x86_64-apple-darwin"
    if system == "Windows":
        return "x86_64-pc-windows-msvc"
    if system == "Linux":
        return "x86_64-unknown-linux-gnu"
    raise RuntimeError(f"unsupported platform: {system} {machine}")


def freeze() -> None:
    BINARIES.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", str(BINARIES),
        "--workpath", str(DESKTOP / "build"),
        str(SPEC),
    ]
    print(f"[build.py] {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=DESKTOP)


def rename_for_tauri() -> None:
    triple = target_triple()
    is_win = platform.system() == "Windows"
    src = BINARIES / ("lk-backend.exe" if is_win else "lk-backend")
    if not src.is_file():
        raise SystemExit(f"PyInstaller output missing: {src}")
    dst = BINARIES / (
        f"lk-backend-{triple}.exe" if is_win else f"lk-backend-{triple}"
    )
    if dst.exists():
        dst.unlink()
    src.rename(dst)
    print(f"[build.py] sidecar ready at {dst}")


def tauri_build() -> None:
    cmd = ["npm", "run", "tauri", "build"]
    print(f"[build.py] (in {DESKTOP}) {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=DESKTOP)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tauri", action="store_true", help="also run `tauri build`")
    args = p.parse_args()

    freeze()
    rename_for_tauri()
    if args.tauri:
        tauri_build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
