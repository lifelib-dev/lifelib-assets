"""Where the export and the compiled build live.

``BONDPORTFOLIO_BUILD`` if set; otherwise, when the project sits in a OneDrive
folder, ``~/.cache/lifelib-assets/build`` (OneDrive keeps directory handles
open, so deleting and rotating build directories inside it fails with "access
denied"; the home directory is used rather than %LOCALAPPDATA%, which some
sandboxed environments redirect); otherwise ``<project>/build``.
"""

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPORT_NAME = "BondPortfolio_nomx"
COMPILED_NAME = EXPORT_NAME + "_cy"


def build_dir() -> pathlib.Path:
    env = os.environ.get("BONDPORTFOLIO_BUILD")
    if env:
        return pathlib.Path(env)
    if any(part.lower().startswith("onedrive") for part in ROOT.parts):
        return pathlib.Path.home() / ".cache" / "lifelib-assets" / "build"
    return ROOT / "build"
