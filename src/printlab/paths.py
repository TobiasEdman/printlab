"""Repository locations. Generated files go under build/, mirroring the source tree.

The root is this checkout when printlab runs from it (editable
install). Installed as a library elsewhere, it is PRINTLAB_ROOT if set, else
the working directory; library functions such as viewer.write_all and the
checks take explicit paths and do not depend on it.
"""

from __future__ import annotations

import os
from pathlib import Path


def _root() -> Path:
    if os.environ.get("PRINTLAB_ROOT"):
        return Path(os.environ["PRINTLAB_ROOT"]).resolve()
    repo = Path(__file__).resolve().parents[2]
    if (repo / "profiles" / "bambu").is_dir():  # running from a printlab checkout
        return repo
    return Path.cwd().resolve()


ROOT = _root()
BUILD = ROOT / "build"
PROFILES = ROOT / "profiles" / "bambu"


def build_dir(source: str | Path) -> Path:
    """build/<path of the model folder>/ for a model folder or a file inside it."""
    source = Path(source).resolve()
    folder = source if source.is_dir() else source.parent
    out = BUILD / folder.relative_to(ROOT)
    out.mkdir(parents=True, exist_ok=True)
    return out
