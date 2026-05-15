"""Create a repo-local macOS .app launcher for PDF Manager.

The generated app bundle is intentionally lightweight. It launches this
repository with the repo's virtual environment Python when available, falling
back to python3 on PATH.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
from pathlib import Path


APP_NAME = "PDF Manager"
BUNDLE_IDENTIFIER = "local.pdftools.pdf-manager"
EXECUTABLE_NAME = "pdf-manager"


def build_app(output_dir: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    app_path = output_dir / f"{APP_NAME}.app"
    contents_dir = app_path / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"

    if app_path.exists():
        shutil.rmtree(app_path)

    macos_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)

    info_plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": EXECUTABLE_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    }
    with (contents_dir / "Info.plist").open("wb") as file:
        plistlib.dump(info_plist, file)

    (contents_dir / "PkgInfo").write_text("APPL????", encoding="ascii")

    launcher = macos_dir / EXECUTABLE_NAME
    launcher.write_text(
        f"""#!/bin/zsh
set -e

REPO_ROOT={str(repo_root)!r}
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

export PYTHONPATH="$REPO_ROOT:${{PYTHONPATH:-}}"
cd "$REPO_ROOT"
exec "$PYTHON" -m pdf_manager.app
""",
        encoding="utf-8",
    )
    launcher.chmod(launcher.stat().st_mode | 0o755)

    return app_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a repo-local macOS .app launcher.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("mac_app"),
        help="Directory that will contain PDF Manager.app. Defaults to ./mac_app.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir.expanduser()
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    app_path = build_app(output_dir)
    print(f"Created {app_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
