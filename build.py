import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".build-venv"
ASSETS = ROOT / ".build-assets"
DIST = ROOT / "dist"
WORK = ROOT / ".pyinstaller-work"
SPEC = ROOT / ".pyinstaller-spec"
NAME = "IslandTracker"


def run(*command):
    command = [str(part) for part in command]
    print(">", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    if os.name != "nt":
        sys.exit("PyInstaller can't cross-compile, run this on Windows.")
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10+ required.")

    python = VENV / "Scripts" / "python.exe"
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(VENV)
    run(python, "-m", "pip", "install", "--upgrade", "pip")
    run(python, "-m", "pip", "install", "-r", ROOT / "requirements.txt")

    for directory in (ASSETS, DIST, WORK, SPEC):
        directory.mkdir(exist_ok=True)

    icon = ASSETS / "island.ico"
    run(
        python, "-c",
        "from PyQt6.QtGui import QGuiApplication; app = QGuiApplication([]); "
        f"from app import save_icon; save_icon({str(icon)!r})",
    )

    run(
        python, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME,
        "--icon", icon,
        "--distpath", DIST,
        "--workpath", WORK,
        "--specpath", SPEC,
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide2",
        "--exclude-module", "PySide6",
        ROOT / "app.py",
    )

    exe = DIST / f"{NAME}.exe"
    if not exe.is_file():
        sys.exit("PyInstaller finished but there's no .exe.")
    print("Built", exe)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
