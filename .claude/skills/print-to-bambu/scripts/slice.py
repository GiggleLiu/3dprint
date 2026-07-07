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
import os
import re
import subprocess
import sys
import tempfile
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
                  plate: int, process_path: Path | None = None) -> list[str]:
    proc = process_path or presets["process"][1]
    settings = f"{presets['machine'][1]};{proc}"
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


# Valid Bambu build-plate types (curr_bed_type). The slicer picks the bed temp
# from the filament preset's per-plate temps based on this.
BED_TYPES = {
    "cool plate": "Cool Plate",
    "textured pei plate": "Textured PEI Plate",
    "textured pei": "Textured PEI Plate",
    "smooth pei plate": "Smooth PEI Plate",
    "engineering plate": "Engineering Plate",
    "high temp plate": "High Temp Plate",
}


def make_process_override(process_json: Path, overrides: dict) -> Path:
    """Copy a process preset with extra keys injected, as a single temp file.

    The CLI rejects a second process file in --load-settings ("duplicate process
    config"), so we can't add options as an overlay — we clone the process and
    set them on the clone. inherits still resolves against the system profiles.
    Returns a temp path the caller must unlink.
    """
    data = json.loads(process_json.read_text())
    data.update(overrides)
    fd, tmp = tempfile.mkstemp(prefix="proc_override_", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    return Path(tmp)


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
            m = re.search(pat, gcode, re.IGNORECASE | re.MULTILINE)
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
        # The ACTUAL commanded bed temp (M190 heat-and-wait / M140 set) — this is
        # what the printer does, regardless of which plate's header temp applies.
        # Fall back to the header only if no command is present.
        "bed_temp": search(r"^M190\s+S(\d+)", r"^M140\s+S(\d+)",
                          r";\s*(?:hot_plate_temp|bed_temperature)\s*[:=]\s*\[?([\d]+)"),
        "bed_type": search(r";\s*curr_bed_type\s*[:=]\s*([^\n;]+)"),
        "layer_height": search(r";\s*layer_height\s*[:=]\s*([\d.]+)"),
    }


# Filament cross-section (1.75mm) in mm^3 per mm of filament.
_FILAMENT_MM3_PER_MM = math.pi * (1.75 / 2.0) ** 2
# Below this first-layer footprint the part is very likely to detach mid-print
# (the hydrogen-molecule lesson: full spheres touch the plate in a point).
FIRST_LAYER_MIN_MM2 = 40.0
# Minimum area of the MODEL's own base (triangles at min z). A brim can make
# the first-layer extrusion look healthy while the model still only touches
# the plate in points/edges — the brim then holds a 2mm-wide neck.
BASE_CONTACT_MIN_MM2 = 30.0


def stl_base_contact_mm2(stl_path: Path, tol: float = 0.25) -> float | None:
    """XY-projected area of the mesh's plate-contact triangles (binary STL).

    Sums triangles that lie entirely within `tol` mm of the model's lowest
    point. A sphere resting on the plate scores ~0 even though it slices fine —
    this is the geometry-side adhesion gate. Best effort: returns None for
    ASCII STLs or parse failures. Note the slicer may auto-reorient the model
    (--orient), so pair this with the G-code first-layer check.
    """
    import struct
    try:
        data = stl_path.read_bytes()
        if data[:5] == b"solid" and b"facet" in data[:500]:
            return None  # ASCII STL; skip rather than half-parse
        (n,) = struct.unpack_from("<I", data, 80)
        if len(data) < 84 + n * 50:
            return None
        zmin = None
        tris = []
        off = 84
        for _ in range(n):
            v = struct.unpack_from("<12f", data, off)  # normal + 3 vertices
            off += 50
            tri = ((v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11]))
            tris.append(tri)
            lo = min(tri[0][2], tri[1][2], tri[2][2])
            zmin = lo if zmin is None else min(zmin, lo)
        if zmin is None:
            return None
        area = 0.0
        for a, b, c in tris:
            if max(a[2], b[2], c[2]) <= zmin + tol:
                area += 0.5 * abs((b[0] - a[0]) * (c[1] - a[1])
                                  - (c[0] - a[0]) * (b[1] - a[1]))
        return round(area, 1)
    except (OSError, struct.error):
        return None


def first_layer_area_mm2(gcode: str, layer_height: float) -> float | None:
    """Approximate the printed first-layer footprint from the G-code.

    Sums extruded filament between the first two layer markers (Bambu:
    "; CHANGE_LAYER", Orca: ";LAYER_CHANGE") and converts volume / height to
    area. This is a *model* printability gate: a mesh that meets the plate in
    points or thin edges slices fine, uploads fine, and then peels off.
    """
    for marker in ("; CHANGE_LAYER", ";LAYER_CHANGE"):
        parts = gcode.split(marker)
        if len(parts) >= 3:
            first_layer = parts[1]
            break
    else:
        return None
    e_total = 0.0
    for m in re.finditer(r"^G[123][^\n;]*\sE([\d.]+)", first_layer, re.MULTILINE):
        try:
            e_total += float(m.group(1))
        except ValueError:
            pass
    if layer_height <= 0:
        return None
    return round(e_total * _FILAMENT_MM3_PER_MM / layer_height, 1)


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
    ap.add_argument("--printer", help="use the bambu.<name>.toml profile")
    ap.add_argument("--output", help="output .gcode.3mf path (default: <stl>.gcode.3mf)")
    ap.add_argument("--machine", help="override [slice].machine preset name")
    ap.add_argument("--process", help="override [slice].process preset name")
    ap.add_argument("--filament", help="override [slice].filament preset name")
    ap.add_argument("--bed-type", help="build-plate type, e.g. \"Textured PEI Plate\" "
                    "(sets the bed temp); overrides [slice].bed_type")
    ap.add_argument("--support", action="store_true",
                    help="enable tree supports (for models with overhangs, "
                    "e.g. figurines)")
    args = ap.parse_args()

    stl = Path(args.stl).expanduser().resolve()
    if not stl.is_file():
        eprint(f"✗ STL not found: {stl}")
        return 1

    cfg = load_config(args.config, printer=args.printer)
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

    # Optional build-plate type → sets the bed temperature (Fix: Cool Plate 35C
    # was the default and too cold for PLA on textured PEI). Cloned into the
    # process preset because the CLI rejects a second process file.
    bed_type_raw = args.bed_type or cfg.get("slice", {}).get("bed_type")
    bed_type = None
    proc_override = None
    proc_extra: dict = {}
    if bed_type_raw:
        bed_type = BED_TYPES.get(bed_type_raw.strip().lower(), bed_type_raw.strip())
        proc_extra["curr_bed_type"] = bed_type
    if args.support:
        proc_extra["enable_support"] = "1"
        proc_extra["support_type"] = "tree(auto)"
    if proc_extra:
        proc_override = make_process_override(presets["process"][1], proc_extra)

    cmd = build_command(slicer_path, presets, stl, out, plate, proc_override)
    eprint(f"Slicing {stl.name} with {kind}:")
    for k in ("machine", "process", "filament"):
        eprint(f"  {k}: {presets[k][0]}")
    if bed_type:
        eprint(f"  bed_type: {bed_type}")
    if args.support:
        eprint("  supports : tree(auto)")
    eprint(f"  -> {out}")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=SLICE_TIMEOUT)
    except subprocess.TimeoutExpired:
        eprint(f"✗ Slicer timed out after {SLICE_TIMEOUT}s")
        return 1
    finally:
        if proc_override is not None:
            try:
                proc_override.unlink()
            except OSError:
                pass

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

    # Model-side adhesion gate: tiny plate contact means the print peels off no
    # matter how healthy the printer is. Two complementary signals:
    #  - geometry: the STL's own base area (a brim can't fix point contact),
    #  - G-code: actual first-layer extrusion (catches slicer reorientation).
    base_area = stl_base_contact_mm2(stl)
    if base_area is not None:
        summary["base_contact_mm2"] = base_area
    if gcode:
        try:
            lh = float(summary.get("layer_height") or 0.2)
        except ValueError:
            lh = 0.2
        area = first_layer_area_mm2(gcode, lh)
        if area is not None:
            summary["first_layer_mm2"] = area
    if ((base_area is not None and base_area < BASE_CONTACT_MIN_MM2)
            or (summary.get("first_layer_mm2") is not None
                and summary["first_layer_mm2"] < FIRST_LAYER_MIN_MM2)):
        summary["adhesion_warning"] = True

    eprint("✓ Slice complete:")
    eprint(f"  print time : {summary.get('print_time')}")
    eprint(f"  filament   : {summary.get('filament_g')} g "
           f"({summary.get('filament_mm')} mm)")
    eprint(f"  temps      : nozzle {summary.get('nozzle_temp')}C / "
           f"bed {summary.get('bed_temp')}C"
           f"{' on ' + summary['bed_type'] if summary.get('bed_type') else ''}")
    if summary.get("base_contact_mm2") is not None or \
            summary.get("first_layer_mm2") is not None:
        eprint(f"  adhesion   : model base {summary.get('base_contact_mm2', '?')} mm2, "
               f"first layer ~{summary.get('first_layer_mm2', '?')} mm2")
    if summary.get("adhesion_warning"):
        eprint("  ⚠ plate contact is tiny — the part will likely detach "
               "mid-print. Give the model a flat base (cut its underside), "
               "don't rely on a brim to hold point contact.")
    eprint(f"  output     : {out} ({summary['size_bytes']} bytes)")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
