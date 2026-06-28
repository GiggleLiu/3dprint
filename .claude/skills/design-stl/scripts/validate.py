#!/usr/bin/env python3
"""Validate an STL for printability: bed fit, mesh integrity, wall thickness, overhangs.

Reads optional `[design]` settings from bambu.toml (bed size, thresholds). Prints
a human ✓/✗ summary on stderr and a JSON report on stdout. Exit non-zero if a HARD
check fails (does not fit the bed, or not watertight).

trimesh powers the mesh checks; if it is missing, validation degrades to bed-fit +
dimensions rather than crashing.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import tomllib
from pathlib import Path

DEFAULTS = {
    "bed": [256, 256, 260],      # X2D W, D, H (mm)
    "min_wall": 0.8,             # mm
    "overhang_angle": 45,        # deg from horizontal; shallower downward => support
}


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def _native(o):
    """json default: convert numpy scalars/arrays to native Python."""
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"not JSON serializable: {type(o)}")


def design_config(explicit: str | None = None) -> dict:
    """Merge [design] from bambu.toml (searched upward) over DEFAULTS."""
    cfg = dict(DEFAULTS)
    path = None
    if explicit:
        p = Path(explicit).expanduser()
        path = p if p.is_file() else None
    else:
        cur = Path.cwd().resolve()
        for d in [cur, *cur.parents]:
            if (d / "bambu.toml").is_file():
                path = d / "bambu.toml"
                break
    if path:
        try:
            with path.open("rb") as fh:
                cfg.update((tomllib.load(fh).get("design", {})) or {})
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return cfg


def _binary_stl_stats(data: bytes):
    """Fallback (no trimesh): (min_xyz, max_xyz, n_triangles) for a binary STL."""
    if len(data) < 84:
        return None
    (n,) = struct.unpack_from("<I", data, 80)
    if 84 + n * 50 != len(data):
        return None
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    off = 84
    for _ in range(n):
        off += 12
        for _v in range(3):
            x, y, z = struct.unpack_from("<3f", data, off)
            off += 12
            for i, c in enumerate((x, y, z)):
                lo[i] = min(lo[i], c)
                hi[i] = max(hi[i], c)
        off += 2
    return tuple(lo), tuple(hi), n


def _fits_bed(dims, bed) -> bool:
    """Footprint may rotate in-plane; Z must fit bed height."""
    fx, fy = sorted([dims[0], dims[1]])
    bx, by = sorted([bed[0], bed[1]])
    return fx <= bx and fy <= by and dims[2] <= bed[2]


def validate_stl(stl: Path, cfg: dict) -> dict:
    bed = cfg["bed"]
    report: dict = {
        "stl": str(stl), "dims_mm": None, "bed": bed, "bed_fit": None,
        "watertight": None, "winding_consistent": None, "volume_mm3": None,
        "triangles": None, "min_wall_mm": None, "min_wall_ok": None,
        "overhang_fraction": None, "overhang_angle": cfg["overhang_angle"],
        "min_wall_threshold": cfg["min_wall"],
        "warnings": [], "checks_skipped": [], "ok": False,
    }

    try:
        import trimesh  # noqa
    except ImportError:
        trimesh = None
        report["checks_skipped"].append(
            "mesh integrity / wall / overhang (pip install trimesh)")

    if trimesh is not None:
        mesh = trimesh.load(str(stl), force="mesh")
        ext = mesh.extents
        report["dims_mm"] = [round(float(x), 2) for x in ext]
        report["triangles"] = int(len(mesh.faces))
        report["watertight"] = bool(mesh.is_watertight)
        report["winding_consistent"] = bool(mesh.is_winding_consistent)
        report["volume_mm3"] = round(float(abs(mesh.volume)), 2) if mesh.is_watertight else None
        report["bed_fit"] = bool(_fits_bed(ext, bed))

        # Overhangs: downward faces shallower than the threshold from horizontal.
        try:
            n = mesh.face_normals
            areas = mesh.area_faces
            slope = [math.degrees(math.acos(min(1.0, abs(float(nz))))) for nz in n[:, 2]]
            overhang_area = sum(a for a, nz, sl in zip(areas, n[:, 2], slope)
                                if nz < -1e-6 and sl < cfg["overhang_angle"])
            total = float(areas.sum())
            report["overhang_fraction"] = float(round(overhang_area / total, 3)) if total else 0.0
        except Exception as e:  # noqa
            report["warnings"].append(f"overhang calc failed: {e}")

        # Min wall thickness (approximate): inscribed-sphere thickness at samples.
        try:
            import numpy as np
            pts, fidx = trimesh.sample.sample_surface(mesh, 1500)
            th = trimesh.proximity.thickness(mesh, pts, normals=mesh.face_normals[fidx])
            th = [float(t) for t in th if t == t and t > 0]  # drop nan/<=0
            if th:
                # 5th percentile, not absolute min: inscribed-sphere thickness
                # spikes to ~0 at concave CSG seams, which aren't real thin walls.
                p5 = float(np.percentile(th, 5))
                report["min_wall_mm"] = round(p5, 3)
                report["min_wall_ok"] = p5 >= cfg["min_wall"]
        except Exception as e:  # noqa
            report["warnings"].append(f"wall-thickness calc failed (rtree?): {e}")
            report["checks_skipped"].append("min wall thickness")
    else:
        stats = _binary_stl_stats(stl.read_bytes())
        if stats:
            lo, hi, n = stats
            ext = [hi[i] - lo[i] for i in range(3)]
            report["dims_mm"] = [round(x, 2) for x in ext]
            report["triangles"] = n
            report["bed_fit"] = _fits_bed(ext, bed)
        else:
            report["warnings"].append("could not parse STL (ASCII or malformed)")

    # HARD checks: bed fit + watertight (watertight only when trimesh ran).
    hard_ok = bool(report["bed_fit"])
    if report["watertight"] is not None:
        hard_ok = hard_ok and report["watertight"]
    report["ok"] = hard_ok
    return report


def _summary(r: dict) -> None:
    def mark(v):
        return "✓" if v else ("?" if v is None else "✗")
    eprint(f"validate {Path(r['stl']).name}")
    eprint(f"  {mark(r['bed_fit'])} bed fit: {r['dims_mm']} mm in bed {r['bed']}")
    eprint(f"  {mark(r['watertight'])} watertight (winding {mark(r['winding_consistent'])}), "
           f"{r['triangles']} tris, vol {r['volume_mm3']} mm³")
    if r["min_wall_mm"] is not None:
        eprint(f"  {mark(r['min_wall_ok'])} min wall ~{r['min_wall_mm']} mm "
               f"(threshold {r['min_wall_threshold']}) [approx]")
    of = r["overhang_fraction"]
    if of is not None:
        eprint(f"  {'⚠' if of > 0.05 else '✓'} overhangs: {of*100:.1f}% of area "
               f"shallower than {r['overhang_angle']}° (supports if high)")
    for w in r["warnings"]:
        eprint(f"  ⚠ {w}")
    for s in r["checks_skipped"]:
        eprint(f"  · skipped: {s}")
    eprint(f"  => ok={r['ok']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stl", help="STL file to validate")
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    args = ap.parse_args()
    stl = Path(args.stl).expanduser().resolve()
    if not stl.is_file():
        eprint(f"✗ STL not found: {stl}")
        return 2
    cfg = design_config(args.config)
    report = validate_stl(stl, cfg)
    _summary(report)
    print(json.dumps(report, indent=2, default=_native))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
