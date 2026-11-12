from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENVIRONMENT = ROOT / ".build-venv"
ASSETS = ROOT / ".build-assets"
OUTPUT = ROOT / "dist"
WORK = ROOT / ".pyinstaller-work"
SPEC = ROOT / ".pyinstaller-spec"
NAME = "IslandTracker"


def run(command):
    print("\n>", subprocess.list2cmdline([str(x) for x in command]), flush=True)
    subprocess.run(
        [str(x) for x in command],
        cwd=ROOT,
        check=True,
    )


def main():
    if os.name != "nt":
        raise SystemExit(
            "Build this Windows .exe on Windows. "
            "PyInstaller does not cross-compile Windows executables."
        )

    if sys.version_info < (3, 10):
        raise SystemExit("Use Python 3.10 or newer.")

    for filename in ("app.py", "requirements.txt"):
        if not (ROOT / filename).is_file():
            raise SystemExit(f"Missing required file: {filename}")

    print("Creating/reusing an isolated build environment...", flush=True)
    python = ENVIRONMENT / "Scripts" / "python.exe"
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(ENVIRONMENT)

    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    run([
        python,
        "-m",
        "pip",
        "install",
        "-r",
        ROOT / "requirements.txt",
    ])

    for directory in (ASSETS, OUTPUT, WORK, SPEC):
        directory.mkdir(parents=True, exist_ok=True)

    icon = ASSETS / "island.ico"

    print("\nGenerating application icon...", flush=True)
    run([
        python,
        "-c",
        (
            "from PyQt6.QtGui import QGuiApplication; "
            "app = QGuiApplication([]); "
            f"from app import save_icon; save_icon({str(icon)!r})"
        ),
    ])

    arguments = [
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", NAME,
        "--icon", str(icon),
        "--distpath", str(OUTPUT),
        "--workpath", str(WORK),
        "--specpath", str(SPEC),
        # Avoid accidentally collecting a second Qt binding.
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide2",
        "--exclude-module", "PySide6",
        str(ROOT / "app.py"),
    ]

    print("\nBuilding standalone executable...", flush=True)

    # Run PyInstaller's Python API inside the isolated environment.
    run([
        python,
        "-c",
        (
            "import PyInstaller.__main__; "
            f"PyInstaller.__main__.run({arguments!r})"
        ),
    ])

    executable = OUTPUT / f"{NAME}.exe"
    if not executable.is_file():
        raise SystemExit("Build finished without producing the expected .exe.")

    print("\nBuild completed successfully.")
    print(f"Executable: {executable}")
    print("You can distribute this .exe without the build environment.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(
            f"\nBuild failed: a subprocess returned exit code {exc.returncode}.",
            file=sys.stderr,
        )
        raise SystemExit(exc.returncode) from None