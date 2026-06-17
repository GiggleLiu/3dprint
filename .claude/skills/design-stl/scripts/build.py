#!/usr/bin/env python3
"""Build a printable STL from EITHER an OpenSCAD file or a Python/trimesh builder,
render preview PNGs, and validate printability — one command per design iteration.

  build.py model.scad     # OpenSCAD CSG -> STL, OpenSCAD-rendered previews
  build.py model.py       # Python builder -> trimesh -> STL, matplotlib previews

A .py builder must expose either a `build()` function returning a trimesh.Trimesh,
or a module-level `model` of that type. Compose with boolean union (manifold3d
backend) so the result is watertight.

Output: previews (PNG paths to VIEW) + a validation report. Human summary on
stderr, JSON on stdout. Claude inspects the renders + report and iterates the
source until it looks right AND ok=true, then hands the STL to print-to-bambu.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import _native, _summary, design_config, eprint, validate_stl  # noqa: E402

RENDER_TIMEOUT = 180
DEFAULT_VIEWS = ["iso", "front", "top"]

# OpenSCAD gimbal camera "transX,transY,transZ,rotX,rotY,rotZ,dist"; --viewall
# --autocenter auto-frames, so 0 trans + 0 dist works.
OPENSCAD_VIEWS = {
    "iso": "0,0,0,55,0,25,0", "front": "0,0,0,90,0,0,0",
    "top": "0,0,0,0,0,0,0", "right": "0,0,0,90,0,90,0",
}
# matplotlib (elev, azim) per view.
MPL_VIEWS = {"iso": (30, 45), "front": (0, -90), "top": (90, -90), "right": (0, 0)}

_MAC_APP = "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"


# ---------- OpenSCAD path ----------

def find_openscad() -> str | None:
    for name in ("openscad", "openscad-nightly", "OpenSCAD"):
        p = shutil.which(name)
        if p and Path(p).is_file():   # is_file() follows symlinks -> skips dangling
            return p
    candidates = ["/opt/homebrew/bin/openscad", "/usr/local/bin/openscad", _MAC_APP]
    candidates += [str(p) for p in
                   Path("/Applications").glob("OpenSCAD*.app/Contents/MacOS/OpenSCAD")]
    return next((c for c in candidates if Path(c).is_file()), None)


def openscad_export(openscad: str, scad: Path, stl: Path) -> tuple[bool, str]:
    p = subprocess.run([openscad, "-o", str(stl), str(scad)],
                       capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    return stl.is_file() and stl.stat().st_size > 0, p.stderr.strip()


def openscad_render(openscad: str, scad: Path, png: Path, camera: str) -> bool:
    subprocess.run([openscad, "--camera=" + camera, "--viewall", "--autocenter",
                    "--imgsize=1024,1024", "--colorscheme=Tomorrow", "-o", str(png),
                    str(scad)], capture_output=True, text=True, timeout=RENDER_TIMEOUT)
    return png.is_file()


# ---------- Python/trimesh path ----------

def run_python_builder(py: Path):
    """Execute a .py builder and return (trimesh_or_None, error_str)."""
    try:
        import trimesh  # noqa
        spec = importlib.util.spec_from_file_location("_design_builder", py)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        obj = mod.build() if callable(getattr(mod, "build", None)) else \
            getattr(mod, "model", None)
        if obj is None:
            return None, "builder must define build() -> Trimesh or a `model` Trimesh"
        if isinstance(obj, trimesh.Scene):
            obj = obj.dump(concatenate=True)
        elif isinstance(obj, (list, tuple)):
            obj = trimesh.util.concatenate(list(obj))
        if not isinstance(obj, trimesh.Trimesh):
            return None, f"builder returned {type(obj)}, expected trimesh.Trimesh"
        return obj, ""
    except ImportError:
        return None, "trimesh not installed (pip install -r requirements.txt)"
    except Exception:  # noqa  — surface the traceback so Claude can self-correct
        return None, traceback.format_exc()


def render_trimesh(mesh, base: Path, views: list[str]) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    out = []
    b = mesh.bounds
    ctr = mesh.centroid
    r = float((b[1] - b[0]).max()) / 2 or 1.0
    for v in views:
        elev, azim = MPL_VIEWS.get(v, (30, 45))
        fig = plt.figure(figsize=(6, 6), dpi=170)
        ax = fig.add_subplot(111, projection="3d")
        ax.add_collection3d(Poly3DCollection(
            mesh.triangles, facecolor="#9fb6c9", edgecolor="#33414c", linewidths=0.05))
        for lo, hi, setlim in ((ctr[0]-r, ctr[0]+r, ax.set_xlim),
                               (ctr[1]-r, ctr[1]+r, ax.set_ylim),
                               (ctr[2]-r, ctr[2]+r, ax.set_zlim)):
            setlim(lo, hi)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        png = base.with_suffix(f".{v}.png")
        fig.savefig(png, bbox_inches="tight")
        plt.close(fig)
        out.append(str(png))
    return out


# ---------- orchestration ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="model.scad (OpenSCAD) or model.py (trimesh builder)")
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    ap.add_argument("--output", help="output STL (default: <source>.stl)")
    ap.add_argument("--views", help="comma list of: iso,front,top,right")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    src = Path(args.source).expanduser().resolve()
    if not src.is_file():
        eprint(f"✗ source not found: {src}")
        return 2
    engine = "openscad" if src.suffix == ".scad" else (
        "trimesh" if src.suffix == ".py" else None)
    if engine is None:
        eprint(f"✗ unknown source type '{src.suffix}'. Use .scad or .py")
        return 2

    cfg = design_config(args.config)
    stl = Path(args.output).expanduser().resolve() if args.output else src.with_suffix(".stl")
    views = [v.strip() for v in (args.views.split(",") if args.views
                                 else cfg.get("views", DEFAULT_VIEWS))]
    report: dict = {"engine": engine, "source": str(src), "stl": None,
                    "previews": [], "build_warnings": None, "validation": None,
                    "ok": False}
    eprint(f"Building {src.name} via {engine} ...")

    # Remove stale outputs so we never mistake a previous run's files for success.
    if stl.exists():
        stl.unlink()
    for v in views:
        stale = src.with_suffix(f".{v}.png")
        if stale.exists():
            stale.unlink()

    if engine == "openscad":
        openscad = find_openscad()
        if openscad is None:
            eprint("✗ OpenSCAD not found. Install: brew install --cask openscad")
            return 2
        ok, warn = openscad_export(openscad, src, stl)
        report["build_warnings"] = warn or None
        if not ok:
            eprint("✗ OpenSCAD produced no STL.")
            if warn:
                eprint(warn)
            print(json.dumps(report, indent=2, default=_native))
            return 1
        for v in views:
            if v in OPENSCAD_VIEWS:
                png = src.with_suffix(f".{v}.png")
                if openscad_render(openscad, src, png, OPENSCAD_VIEWS[v]):
                    report["previews"].append(str(png))
    else:
        mesh, err = run_python_builder(src)
        if mesh is None:
            eprint("✗ builder failed:\n" + err)
            report["build_warnings"] = err
            print(json.dumps(report, indent=2, default=_native))
            return 1
        mesh.export(str(stl))
        try:
            report["previews"] = render_trimesh(mesh, src, views)
        except Exception as e:  # noqa  — preview is non-fatal
            report["build_warnings"] = f"preview render failed: {e}"

    report["stl"] = str(stl)
    eprint(f"✓ STL: {stl} ({stl.stat().st_size} bytes)")
    for p in report["previews"]:
        eprint(f"✓ preview: {p}")
    if report["build_warnings"]:
        eprint(f"⚠ {report['build_warnings']}")

    if not args.no_validate:
        val = validate_stl(stl, cfg)
        report["validation"] = val
        eprint("")
        _summary(val)
        report["ok"] = bool(val["ok"])
    else:
        report["ok"] = True

    print(json.dumps(report, indent=2, default=_native))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
