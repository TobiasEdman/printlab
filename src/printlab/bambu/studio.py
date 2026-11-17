"""Where the installed Bambu Studio lives and which version it is."""

from __future__ import annotations

import os
import plistlib
from pathlib import Path


def app() -> Path:
    return Path(os.environ.get("BAMBU_STUDIO_APP", "/Applications/BambuStudio.app"))


def executable(studio: Path | None = None) -> Path:
    return (studio or app()) / "Contents/MacOS/BambuStudio"


def vendor_profiles(studio: Path | None = None) -> Path:
    return (studio or app()) / "Contents/Resources/profiles/BBL"


def version(studio: Path | None = None) -> str:
    plist = (studio or app()) / "Contents/Info.plist"
    return plistlib.loads(plist.read_bytes())["CFBundleShortVersionString"]


def installed(studio: Path | None = None) -> bool:
    return executable(studio).exists()
