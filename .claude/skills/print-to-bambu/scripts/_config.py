"""Shared helpers for the print-to-bambu skill: config loading + slicer discovery.

Imported by preflight.py, slice.py, send.py, monitor.py. Pure standard library
so the slicing path needs no third-party packages (only send/monitor need
bambulabs-api, imported lazily there).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
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


def find_profile_config(name: str) -> Path:
    """Locate a named printer profile bambu.<name>.toml by walking up from cwd."""
    cur = Path.cwd().resolve()
    for d in [cur, *cur.parents]:
        candidate = d / f"bambu.{name}.toml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"No bambu.{name}.toml profile found. "
        f"Available: {', '.join(list_profiles()) or '(none)'}")


def list_profiles(root: Path | None = None) -> list[str]:
    """Names of every bambu.<name>.toml profile near the project (excludes example)."""
    if root is None:
        cur = Path.cwd().resolve()
        for d in [cur, *cur.parents]:
            if (d / CONFIG_NAME).is_file() or list(d.glob("bambu.*.toml")):
                root = d
                break
        else:
            root = Path.cwd()
    out = []
    for p in sorted(root.glob("bambu.*.toml")):
        if p.name == "bambu.toml.example":
            continue
        out.append(p.name[len("bambu."):-len(".toml")])
    return out


def load_config(explicit: str | None = None, printer: str | None = None) -> dict:
    """Load and lightly validate bambu.toml.

    With `printer`, loads the bambu.<printer>.toml profile instead of bambu.toml
    (an explicit path still wins). Returns a dict with the parsed tables plus:
    `_path` (config file Path), `_root` (its directory), and `access_code`
    resolved (env BAMBU_ACCESS_CODE takes precedence over the file).
    Raises FileNotFoundError if no config, ValueError if required keys missing.
    """
    if explicit is None and printer:
        explicit = str(find_profile_config(printer))
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


# --- preset compatibility & discovery (Fix 1 / Fix 2) -----------------------

def _preset_data(slicer_path: Path, kind_dir: str, name: str) -> dict | None:
    jp = preset_json_path(slicer_path, kind_dir, name)
    if jp is None:
        return None
    try:
        return json.loads(jp.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def compatible_printers(slicer_path: Path, kind_dir: str, name: str,
                        depth: int = 0) -> list[str] | None:
    """A preset's `compatible_printers`, following the `inherits` chain.

    Returns the list, or None if no preset/list could be resolved (unknown).
    """
    data = _preset_data(slicer_path, kind_dir, name)
    if data is None:
        return None
    cp = data.get("compatible_printers")
    if cp:
        return cp
    parent = data.get("inherits")
    if parent and depth < 8:
        return compatible_printers(slicer_path, kind_dir, parent, depth + 1)
    return cp  # None or [] (e.g. an abstract base preset)


def preset_compatible_with(slicer_path: Path, kind_dir: str, name: str,
                           machine_name: str) -> bool | None:
    """True/False if the preset lists machine_name; None if undeterminable.

    A None means the preset has no compatible_printers list at all (we can't
    prove incompatibility, so callers should warn rather than hard-fail).
    """
    cp = compatible_printers(slicer_path, kind_dir, name)
    if not cp:
        return None
    return machine_name in cp


def list_presets(slicer_path: Path, kind_dir: str,
                 selectable_only: bool = False) -> list[str]:
    """Display names of every preset of a kind across vendor dirs.

    selectable_only filters to user-pickable presets (Bambu marks these with
    "instantiation": "true"), excluding abstract bases and g-code templates.
    """
    root = slicer_resources_dir(slicer_path)
    if root is None:
        return []
    names = set()
    for p in root.glob(f"*/{kind_dir}/*.json"):
        name = p.stem
        if selectable_only:
            try:
                data = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if str(data.get("instantiation", "")).lower() != "true":
                continue
        names.add(name)
    return sorted(names)


def list_machines(slicer_path: Path) -> list[str]:
    """User-selectable machine presets (no g-code template / base entries)."""
    return list_presets(slicer_path, "machine", selectable_only=True)


def compatible_presets(slicer_path: Path, kind_dir: str,
                       machine_name: str) -> list[str]:
    """Preset names of a kind whose compatible_printers includes machine_name."""
    out = [
        name for name in list_presets(slicer_path, kind_dir)
        if preset_compatible_with(slicer_path, kind_dir, name, machine_name)
    ]
    return sorted(out)


# --- network helpers (Fix 3 / shared with use_printer.py) -------------------

_PHYSICAL_IFACE_PREFIXES = ("en", "eth", "bridge")
_VPN_IFACE_PREFIXES = ("utun", "ppp", "tun", "ipsec", "gpd", "wg")


def tcp_open(ip: str | None, port: int = 8883, timeout: float = 2.0) -> bool:
    """True if a TCP connection to ip:port succeeds within timeout."""
    if not ip:
        return False
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def route_iface(ip: str | None) -> str | None:
    """macOS/BSD: which interface routes to ip (en0, utun4, ...). None if N/A."""
    if not ip:
        return None
    try:
        out = subprocess.run(
            ["route", "-n", "get", ip], capture_output=True, text=True, timeout=4
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("interface:"):
            return line.split(":", 1)[1].strip()
    return None


def locality(iface: str | None) -> str:
    """Classify a route interface: 'lan', 'vpn', 'other', or 'unknown'."""
    if iface is None:
        return "unknown"
    if iface.startswith(_VPN_IFACE_PREFIXES):
        return "vpn"
    if iface.startswith(_PHYSICAL_IFACE_PREFIXES):
        return "lan"
    return "other"
