---
name: design-stl
description: Use when the user wants to create or design a 3D-printable STL model from a description (e.g. a molecule, a part, a parametric shape) rather than starting from an existing STL. Generates geometry with Python/trimesh (default) or OpenSCAD, renders previews, validates printability, and iterates. Pairs with print-to-bambu to actually print it.
---

# Design an STL (verify loop)

Turn a description into a **printable** STL, then loop: build → look → measure →
fix. The script makes artifacts you can *see* (preview PNGs) and *measure*
(printability report); iterate the source until it's right, then hand the STL to
**print-to-bambu**.

**Default engine: Python + trimesh** (flexible, data-driven, one language, and the
preview/validate stack is already installed). **OpenSCAD is optional** — use it
only if the user prefers CSG and the binary is installed.

Prereqs: `pip install -r requirements.txt` (trimesh, scipy, rtree, matplotlib,
manifold3d). Run scripts with the venv interpreter (`.venv/bin/python`). OpenSCAD
(optional): `brew install --cask openscad`. First-time setup: the **onboard** skill.

## The loop (do this, don't one-shot it)

1. **Write `model.py`** — a builder returning a **watertight** `trimesh.Trimesh`.
   Read `reference/trimesh-cheatsheet.md` first; the key rule is compose parts
   with **boolean `union`** (not concatenation) so the result is manifold.
   *(Prefer OpenSCAD CSG instead? Write `model.scad` — see
   `reference/openscad-cheatsheet.md` — and build it the same way.)*
2. **Build** — `scripts/build.py model.py` (or `model.scad`). Writes `model.stl`,
   renders iso/front/top previews, runs the printability checks. Auto-detects the
   engine from the extension.
3. **Look + measure** — actually VIEW the preview PNGs (they're images you can
   see) and read the validation report.
4. **Iterate** — if a render looks wrong or a check fails (not watertight,
   exceeds bed, thin features, heavy overhangs, or a builder traceback), edit the
   source and rebuild. Repeat until it looks right AND `ok=true`.
5. **Hand off** — give `model.stl` to **print-to-bambu** (optionally `view.py`
   for an interactive 3D preview first), then slice → confirm → print.

Don't declare success from the code alone — confirm against the rendered image
and the report.

## What `build.py` reports

JSON (stdout) + human summary (stderr): `engine`, `stl`, `previews` (PNG paths to
VIEW), `build_warnings` (incl. a builder traceback if it failed), and
`validation`: `bed_fit`, `dims_mm`, `watertight`, `volume_mm3`, `triangles`,
`min_wall_mm` (approx), `overhang_fraction`, `ok`.

`scripts/validate.py <stl>` runs the same checks on any STL standalone.

## Reading the checks

| Check | Meaning / fix |
|-------|---------------|
| builder traceback | Python error in `model.py` — read it, fix the code |
| `bed_fit` ✗ | bounding box bigger than the bed — scale down or split |
| `watertight` ✗ | non-manifold — compose with boolean `union`, make parts overlap |
| `min_wall_mm` low | maybe a thin feature; **approximate, over-flags CSG seams** — check for real thin spikes/plates, not a hard fail |
| `overhang_fraction` high | shallow downward faces — expect supports, add a base, or reorient |

`ok` is true only when it fits the bed and is watertight (the hard checks);
wall/overhang are warnings to weigh.

## Common mistakes

- **Concatenating parts instead of `union`** → not watertight. Union them.
- **Trusting the code without viewing the render** — always look at the PNGs.
- **Wrong interpreter** — run with the venv Python that has trimesh et al.
- **Reaching for OpenSCAD by default** — trimesh is the default; OpenSCAD is the
  opt-in path and needs the binary.

## Config

Optional `[design]` in `bambu.toml`: `bed` (default X2D 256×256×260), `min_wall`
(0.8), `overhang_angle` (45), `views`. Works with zero config.
