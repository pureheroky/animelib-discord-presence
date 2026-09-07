#!/usr/bin/env python3
"""Builds the bridge into a single executable.

Run this on the platform you are building for — PyInstaller does not
cross-compile. Needs `pip install pyinstaller`.

The result is a windowed (console-less) binary: Firefox launches the host in the
background, and a console window would flash on screen every time. Windowed mode
is safe here because the host reads and writes the raw file descriptors rather
than sys.stdin/sys.stdout, which a windowed build may leave empty.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "AnimeLibPresence"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing. Install it with:\n  %s -m pip install pyinstaller"
              % sys.executable)
        return 1

    dist = HERE / "dist"
    work = Path(tempfile.gettempdir()) / (NAME + "-build")
    shutil.rmtree(work, ignore_errors=True)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--name", NAME,
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
        # The package is imported through a path insert, so name it explicitly.
        "--hidden-import", "presence",
        "--paths", str(HERE),
        str(HERE / "run.py"),
    ]
    # No --icon: PyInstaller wants a .ico on Windows and there is none in the
    # repo. The binary is launched by Firefox, never double-clicked, so its icon
    # is close to invisible anyway.

    print("building…")
    result = subprocess.run(args)
    if result.returncode:
        return result.returncode

    built = dist / (NAME + (".exe" if os.name == "nt" else ""))
    print("\nbuilt: %s (%.1f MB)" % (built, built.stat().st_size / 1e6))
    print("\nNext: run it once with --register so Firefox knows about it:")
    print("  %s --register" % built)
    return 0


if __name__ == "__main__":
    sys.exit(main())
