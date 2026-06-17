#!/usr/bin/env python3
"""Compile an OpenSCAD file to STL, render preview PNGs, and validate printability.

One command per design iteration: `build.py model.scad` writes model.stl and
model.<view>.png, runs the printability checks, and prints a consolidated report
(human summary on stderr, JSON on stdout). Claude looks at the PNGs + report and
edits the .scad until it's right, then hands the STL to print-to-bambu.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import _native, design_config, eprint, validate_stl  # noqa: E402

RENDER_TIMEOUT = 180

# OpenSCAD gimbal camera "rotX,rotY,rotZ"; with --viewall --autocenter the
# distance is auto-computed, so 0,0,0 trans + 0 dist frames the model.
VIEWS = {
    "iso":   "0,0,0,55,0,25,0",
    "front": "0,0,0,90,0,0,0",
    "top":   "0,0,0,0,0,0,0",
    "right": "0,0,0,90,0,90,0",
}

_MAC_APP = "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"


def find_openscad() -> str | None:
    for name in ("openscad", "openscad-nightly", "OpenSCAD"):
        p = shutil.which(name)
        if p:
            return p
    if Path(_MAC_APP).is_file():
        return _MAC_APP
    return None


def export_stl(openscad: str, scad: Path, out: Path) -> tuple[bool, str]:
    proc = subprocess.run([openscad, "-o", str(out), str(scad)],
                          capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    return out.is_file() and out.stat().st_size > 0, proc.stderr.strip()


def render_png(openscad: str, scad: Path, out: Path, camera: str) -> bool:
    cmd = [openscad, "--camera=" + camera, "--viewall", "--autocenter",
           "--imgsize=1024,1024", "--colorscheme=Tomorrow", "-o", str(out), str(scad)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    return out.is_file()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scad", help="OpenSCAD source file")
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    ap.add_argument("--output", help="output STL (default: <scad>.stl)")
    ap.add_argument("--views", help="comma list of: " + ",".join(VIEWS))
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    scad = Path(args.scad).expanduser().resolve()
    if not scad.is_file():
        eprint(f"✗ SCAD not found: {scad}")
        return 2

    openscad = find_openscad()
    if openscad is None:
        eprint("✗ OpenSCAD not found. Install it: brew install --cask openscad")
        return 2

    cfg = design_config(args.config)
    stl = Path(args.output).expanduser().resolve() if args.output else \
        scad.with_suffix(".stl")
    view_names = (args.views.split(",") if args.views else cfg.get("views",
                  ["iso", "front", "top"]))

    report: dict = {"scad": str(scad), "stl": None, "previews": [],
                    "openscad_warnings": None, "validation": None, "ok": False}

    eprint(f"Building {scad.name} with OpenSCAD ...")
    ok, warnings = export_stl(openscad, scad, stl)
    report["openscad_warnings"] = warnings or None
    if not ok:
        eprint("✗ OpenSCAD produced no STL.")
        if warnings:
            eprint("--- openscad stderr ---")
            eprint(warnings)
        print(json.dumps(report, indent=2, default=_native))
        return 1
    report["stl"] = str(stl)
    eprint(f"✓ STL: {stl} ({stl.stat().st_size} bytes)")
    if warnings:
        eprint(f"⚠ OpenSCAD warnings:\n{warnings}")

    for v in view_names:
        v = v.strip()
        if v not in VIEWS:
            eprint(f"· unknown view '{v}' (skip)")
            continue
        png = scad.with_suffix(f".{v}.png")
        if render_png(openscad, scad, png, VIEWS[v]):
            report["previews"].append(str(png))
            eprint(f"✓ preview: {png}")

    if not args.no_validate:
        val = validate_stl(stl, cfg)
        report["validation"] = val
        # mirror validate's summary to stderr
        eprint("")
        from validate import _summary
        _summary(val)
        report["ok"] = bool(val["ok"])
    else:
        report["ok"] = True

    print(json.dumps(report, indent=2, default=_native))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
