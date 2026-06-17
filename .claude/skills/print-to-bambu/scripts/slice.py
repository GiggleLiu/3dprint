#!/usr/bin/env python3
"""Slice an STL into a Bambu-ready .gcode.3mf using the configured slicer CLI.

Bambu Studio and OrcaSlicer share the same CLI flags (Orca is a fork). Output is
a `.gcode.3mf` archive with the G-code embedded. Prints a summary JSON (estimated
time, filament, temps) on stdout and a human summary on stderr.

Preset names come from bambu.toml ([slice].machine/process/filament) unless
overridden with --machine/--process/--filament (handy for testing).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import eprint, find_slicer, load_config, preset_json_path  # noqa: E402

SLICE_TIMEOUT = 900  # seconds


def resolve_presets(slicer_path: Path, slice_cfg: dict, overrides: dict) -> dict:
    """Map machine/process/filament preset names to their JSON file paths."""
    resolved = {}
    for kind in ("machine", "process", "filament"):
        name = overrides.get(kind) or slice_cfg.get(kind)
        if not name:
            raise ValueError(f"[slice].{kind} is not set (and no --{kind} override)")
        jp = preset_json_path(slicer_path, kind, name)
        if jp is None:
            raise ValueError(
                f"{kind} preset '{name}' not found in this slicer. "
                "Update the slicer or fix the name in bambu.toml.")
        resolved[kind] = (name, jp)
    return resolved


def build_command(slicer: Path, presets: dict, stl: Path, out: Path,
                  plate: int) -> list[str]:
    settings = f"{presets['machine'][1]};{presets['process'][1]}"
    return [
        str(slicer),
        "--load-settings", settings,
        "--load-filaments", str(presets["filament"][1]),
        "--slice", str(plate),
        "--arrange", "1",
        "--orient", "1",
        "--export-3mf", str(out),
        str(stl),
    ]


def _gcode_text(threemf: Path, plate: int) -> str | None:
    """Return the embedded plate G-code text from a .gcode.3mf, if present."""
    try:
        with zipfile.ZipFile(threemf) as z:
            names = z.namelist()
            wanted = [f"Metadata/plate_{plate}.gcode", "Metadata/plate_1.gcode"]
            target = next((n for n in wanted if n in names), None)
            if target is None:
                target = next((n for n in names if n.endswith(".gcode")), None)
            if target is None:
                return None
            return z.read(target).decode("utf-8", "replace")
    except (zipfile.BadZipFile, OSError):
        return None


def parse_summary(gcode: str) -> dict:
    """Best-effort extraction of estimates from Bambu/Orca G-code header+config."""
    def search(*patterns):
        for pat in patterns:
            m = re.search(pat, gcode, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    return {
        "print_time": search(r";\s*model printing time:\s*([^\n;]+)",
                              r";\s*total estimated time:\s*([^\n]+)"),
        "filament_g": search(r";\s*total filament weight \[g\]\s*[:=]\s*([\d.]+)",
                             r";\s*filament used \[g\]\s*[:=]\s*([\d.]+)"),
        "filament_mm": search(r";\s*total filament length \[mm\]\s*[:=]\s*([\d.]+)",
                              r";\s*filament used \[mm\]\s*[:=]\s*([\d.]+)"),
        "nozzle_temp": search(r";\s*nozzle_temperature\s*[:=]\s*\[?([\d]+)",
                             r";\s*nozzle_temperature_initial_layer\s*[:=]\s*\[?([\d]+)"),
        "bed_temp": search(r";\s*(?:hot_plate_temp|bed_temperature)\s*[:=]\s*\[?([\d]+)",
                          r";\s*first_layer_bed_temperature\s*[:=]\s*\[?([\d]+)"),
        "layer_height": search(r";\s*layer_height\s*[:=]\s*([\d.]+)"),
    }


def _filament_prop(slicer: Path, json_path: Path, key: str, depth: int = 0):
    """Resolve a filament preset value, following the `inherits` chain.

    Bambu's CLI doesn't fill in filament weight, and leaf presets often inherit
    density/diameter from a base. Returns the first non-empty value found.
    """
    try:
        data = json.loads(json_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    val = data.get(key)
    if isinstance(val, list):
        val = val[0] if val else None
    if val not in (None, "", "0", "0.0", "0.00"):
        return val
    parent = data.get("inherits")
    if parent and depth < 8:
        pj = preset_json_path(slicer, "filament", parent)
        if pj is not None:
            return _filament_prop(slicer, pj, key, depth + 1)
    return val


def estimate_weight_g(slicer: Path, filament_json: Path, length_mm: float) -> float | None:
    """Estimate filament mass from extruded length, diameter and density."""
    try:
        density = float(_filament_prop(slicer, filament_json, "filament_density"))
        diameter = float(_filament_prop(slicer, filament_json, "filament_diameter") or 1.75)
    except (TypeError, ValueError):
        return None
    volume_mm3 = length_mm * math.pi * (diameter / 2.0) ** 2
    return round(volume_mm3 * density / 1000.0, 2)  # mm^3 * g/cm^3 / 1000 = g


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stl", help="path to the STL to slice")
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    ap.add_argument("--output", help="output .gcode.3mf path (default: <stl>.gcode.3mf)")
    ap.add_argument("--machine", help="override [slice].machine preset name")
    ap.add_argument("--process", help="override [slice].process preset name")
    ap.add_argument("--filament", help="override [slice].filament preset name")
    args = ap.parse_args()

    stl = Path(args.stl).expanduser().resolve()
    if not stl.is_file():
        eprint(f"✗ STL not found: {stl}")
        return 1

    cfg = load_config(args.config)
    slicer_path, kind = find_slicer(cfg)
    if slicer_path is None:
        eprint("✗ No slicer found. Install Bambu Studio or OrcaSlicer, or set "
               "[slicer].binary in bambu.toml.")
        return 1

    overrides = {"machine": args.machine, "process": args.process,
                 "filament": args.filament}
    try:
        presets = resolve_presets(slicer_path, cfg.get("slice", {}), overrides)
    except ValueError as e:
        eprint(f"✗ {e}")
        return 1

    plate = int(cfg.get("slice", {}).get("plate", 1))
    out = Path(args.output).expanduser().resolve() if args.output else \
        stl.with_suffix("").with_suffix(".gcode.3mf")
    if out.exists():
        out.unlink()

    cmd = build_command(slicer_path, presets, stl, out, plate)
    eprint(f"Slicing {stl.name} with {kind}:")
    for k in ("machine", "process", "filament"):
        eprint(f"  {k}: {presets[k][0]}")
    eprint(f"  -> {out}")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=SLICE_TIMEOUT)
    except subprocess.TimeoutExpired:
        eprint(f"✗ Slicer timed out after {SLICE_TIMEOUT}s")
        return 1

    if not out.is_file():
        eprint("✗ Slice failed — no output produced.")
        eprint("--- slicer stdout (tail) ---")
        eprint("\n".join(proc.stdout.splitlines()[-25:]))
        eprint("--- slicer stderr (tail) ---")
        eprint("\n".join(proc.stderr.splitlines()[-25:]))
        return 1

    gcode = _gcode_text(out, plate)
    summary = parse_summary(gcode) if gcode else {}

    # Bambu's CLI leaves weight at 0.00; estimate from length when needed.
    weight = summary.get("filament_g")
    try:
        weight_bad = weight is None or float(weight) == 0.0
    except ValueError:
        weight_bad = True
    if weight_bad and summary.get("filament_mm"):
        est = estimate_weight_g(slicer_path, presets["filament"][1],
                                float(summary["filament_mm"]))
        if est is not None:
            summary["filament_g"] = f"{est}"
            summary["filament_g_estimated"] = True

    summary["output"] = str(out)
    summary["machine"] = presets["machine"][0]
    summary["filament"] = presets["filament"][0]
    summary["size_bytes"] = out.stat().st_size

    eprint("✓ Slice complete:")
    eprint(f"  print time : {summary.get('print_time')}")
    eprint(f"  filament   : {summary.get('filament_g')} g "
           f"({summary.get('filament_mm')} mm)")
    eprint(f"  temps      : nozzle {summary.get('nozzle_temp')}C / "
           f"bed {summary.get('bed_temp')}C")
    eprint(f"  output     : {out} ({summary['size_bytes']} bytes)")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
