---
name: design-stl
description: Use when the user wants to create or design a 3D-printable STL model from a description (e.g. a molecule, a part, a parametric shape) rather than starting from an existing STL. Generates OpenSCAD, renders previews, validates printability, and iterates. Pairs with print-to-bambu to actually print it.
---

# Design an STL (OpenSCAD + verify loop)

Turn a description into a **printable** STL by writing OpenSCAD, then looping:
render → look → measure → fix. The script produces artifacts you can *see* (PNG
previews) and *measure* (printability report); you iterate the `.scad` until it's
right, then hand the STL to **print-to-bambu**.

Prereqs: OpenSCAD (`brew install --cask openscad`) and `pip install -r
requirements.txt` (trimesh). Run scripts with the venv interpreter
(`.venv/bin/python`). First-time setup is covered by the **onboard** skill.

## The loop (do this, don't one-shot it)

1. **Write `model.scad`** from the user's description. Read
   `reference/openscad-cheatsheet.md` first — it has the CSG idioms and the
   printability rules the validator enforces (overlap joints, min wall, base).
2. **Build** — `scripts/build.py model.scad`. It writes `model.stl`, renders
   preview PNGs (iso/front/top), and runs the printability checks.
3. **Look + measure** — actually VIEW the preview PNGs (they're images you can
   see) and read the validation report.
4. **Iterate** — if a render looks wrong, or any check fails (not watertight,
   exceeds bed, thin walls, heavy overhangs), edit the `.scad` and rebuild.
   Repeat until the model looks right AND `ok=true`.
5. **Hand off** — give `model.stl` to **print-to-bambu** (optionally `view.py`
   for an interactive 3D preview first), then slice → confirm → print.

Do not declare success from the code alone — confirm against the rendered image
and the report.

## What `build.py` reports

`scripts/build.py model.scad` → JSON (stdout) + human summary (stderr):
- `stl`, `previews` (PNG paths to view), `openscad_warnings`
- `validation`: `bed_fit`, `dims_mm`, `watertight`, `volume_mm3`, `triangles`,
  `min_wall_mm` (approx), `overhang_fraction`, `ok`

`scripts/validate.py <stl>` runs the same checks on any STL standalone.

## Reading the checks

| Check | Meaning / fix |
|-------|---------------|
| `bed_fit` ✗ | bounding box bigger than the bed — scale down or split |
| `watertight` ✗ | gaps/non-manifold — make joining solids **overlap**, not just touch |
| `min_wall_mm` low | feature thinner than ~0.8 mm — thicken it |
| `overhang_fraction` high | lots of shallow downward faces — expect supports, or add a base / reorient |
| `openscad_warnings` | syntax/CSG issues — fix the `.scad` |

`ok` is true only when it fits the bed and is watertight (the hard checks);
wall/overhang are warnings to weigh, not hard fails.

## Common mistakes

- **Trusting the code without viewing the render** — always look at the PNGs.
- **Touching (not overlapping) joints** → non-watertight. Overlap them.
- **trimesh/OpenSCAD missing** → validation degrades or build fails with an
  install hint; install per the prereqs (or run `/onboard`).
- **Units** — OpenSCAD is unitless but everything here treats it as **mm**.

## Config

Optional `[design]` in `bambu.toml`: `bed` (default X2D 256×256×260), `min_wall`
(0.8), `overhang_angle` (45), `views`. Works with zero config.
