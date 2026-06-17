"""Shared helpers for the print-to-bambu skill: config loading + slicer discovery.

Imported by preflight.py, slice.py, send.py, monitor.py. Pure standard library
so the slicing path needs no third-party packages (only send/monitor need
bambulabs-api, imported lazily there).
"""
from __future__ import annotations

import os
import shutil
import sys
import tomllib
from pathlib import Path

CONFIG_NAME = "bambu.toml"

# Where slicer machine profiles live, relative to a macOS .app's MacOS binary.
# Both Bambu Studio and OrcaSlicer (a fork) use profiles/<vendor>/<kind>/<name>.json.
_MAC_APP_CANDIDATES = [
    ("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio", "bambustudio"),
    ("/Applications/Bambu Studio.app/Contents/MacOS/BambuStudio", "bambustudio"),
    ("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer", "orca"),
]
_PATH_CANDIDATES = [
    ("bambu-studio", "bambustudio"),
    ("bambustudio", "bambustudio"),
    ("orca-slicer", "orca"),
    ("orcaslicer", "orca"),
    ("OrcaSlicer", "orca"),
]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def find_config_file(explicit: str | None = None) -> Path | None:
    """Locate bambu.toml: explicit path, else walk up from cwd to filesystem root."""
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    cur = Path.cwd().resolve()
    for d in [cur, *cur.parents]:
        candidate = d / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_config(explicit: str | None = None) -> dict:
    """Load and lightly validate bambu.toml.

    Returns a dict with the parsed tables plus: `_path` (config file Path),
    `_root` (its directory), and `access_code` resolved (env BAMBU_ACCESS_CODE
    takes precedence over the file).
    Raises FileNotFoundError if no config, ValueError if required keys missing.
    """
    path = find_config_file(explicit)
    if path is None:
        raise FileNotFoundError(
            f"No {CONFIG_NAME} found. Run setup_config.py to scaffold one."
        )
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    printer = data.get("printer", {})
    missing = [k for k in ("ip", "serial") if not printer.get(k)]
    if missing:
        raise ValueError(
            f"{path}: [printer] is missing required key(s): {', '.join(missing)}"
        )

    access_code = os.environ.get("BAMBU_ACCESS_CODE") or printer.get("access_code", "")
    data["access_code"] = access_code
    data["_path"] = path
    data["_root"] = path.parent
    return data


def find_slicer(cfg: dict) -> tuple[Path | None, str]:
    """Resolve the slicer binary. Returns (path_or_None, kind).

    Order: configured [slicer].binary, then known macOS .app bundles, then PATH.
    kind is one of 'bambustudio', 'orca', 'unknown'.
    """
    configured = (cfg.get("slicer", {}) or {}).get("binary", "")
    if configured:
        p = Path(configured).expanduser()
        if p.is_file():
            kind = "orca" if "orca" in p.name.lower() else (
                "bambustudio" if "bambu" in p.name.lower() else "unknown")
            return p, kind
        return None, "unknown"

    for path_str, kind in _MAC_APP_CANDIDATES:
        p = Path(path_str)
        if p.is_file():
            return p, kind
    for name, kind in _PATH_CANDIDATES:
        found = shutil.which(name)
        if found:
            return Path(found), kind
    return None, "unknown"


def slicer_resources_dir(slicer_path: Path) -> Path | None:
    """Find the bundled profiles root for a slicer binary, if discoverable.

    macOS .app layout: <app>/Contents/MacOS/<bin> -> <app>/Contents/Resources/profiles
    """
    parts = slicer_path.resolve().parts
    if "Contents" in parts and "MacOS" in parts:
        contents = Path(*parts[: parts.index("Contents") + 1])
        prof = contents / "Resources" / "profiles"
        if prof.is_dir():
            return prof
    # Generic fallback: look near the binary.
    for up in [slicer_path.parent, slicer_path.parent.parent]:
        cand = up / "resources" / "profiles"
        if cand.is_dir():
            return cand
    return None


def preset_json_path(slicer_path: Path, kind_dir: str, name: str) -> Path | None:
    """Find a preset JSON by display name within a slicer's profiles tree.

    kind_dir is 'machine', 'process', or 'filament'. Searches every vendor dir
    (BBL, Orca, etc.). Returns the JSON path or None if not present.
    """
    if not name:
        return None
    root = slicer_resources_dir(slicer_path)
    if root is None:
        return None
    # profiles/<vendor>/<kind_dir>/<name>.json
    matches = list(root.glob(f"*/{kind_dir}/{name}.json"))
    return matches[0] if matches else None


def machine_profile_exists(slicer_path: Path, machine_name: str) -> bool:
    return preset_json_path(slicer_path, "machine", machine_name) is not None
