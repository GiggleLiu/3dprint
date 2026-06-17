# Design: `design-stl` skill

**Date:** 2026-06-17
**Status:** Approved design — implementing directly (no separate plan, per user)

## Summary

A second in-repo Claude Code skill that turns a natural-language description into
a **printable** STL via an OpenSCAD generate→verify loop, then hands the STL to
the existing `print-to-bambu` skill. It fills the gap the surveyed tools
(openscad-mcp, CQAsk, etc.) leave open: a self-correcting loop with real
printability validation.

## Goals

- Description → printable STL, with Claude iterating until it's right.
- A loop where each step produces artifacts Claude can **see** (PNG renders) and
  **measure** (mesh report), so correctness isn't assumed.
- Output feeds straight into `print-to-bambu` (slice → confirm → print).

## Non-goals (YAGNI)

Multi-part assemblies, automatic support generation, text-to-CAD ML models,
non-OpenSCAD engines, any GUI.

## Key decisions (from brainstorming + research)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Engine | **Python + trimesh by default; OpenSCAD optional** | trimesh is more flexible/data-driven, single-language, all-pip; `build.py` auto-detects `.py` vs `.scad`. (Revised from OpenSCAD-only after weighing flexibility.) |
| Validation depth | **Full**: visual + bed-fit + mesh integrity + min-wall + overhangs | User selected full analysis |
| Mesh analysis lib | `trimesh` | watertight/volume/thickness/normals in one dep |
| Location | in-repo `.claude/skills/design-stl/` | ships with repo, like print-to-bambu |
| Config | reuse `bambu.toml`, add `[design]` | zero-config defaults for the X2D |
| Hand-off | output STL → `print-to-bambu` | clean separation of design vs print |

Prior art reviewed: `jabberjabberjabber/openscad-mcp` (PNG-as-base64 feedback,
subprocess+stderr capture, scratchpad state, temp cleanup) and `OpenOrion/CQAsk`
(dynamic code execution). Neither implements a verify/retry loop or printability
checks — that is this skill's value-add.

## The loop (encoded in SKILL.md)

```
describe -> Claude writes model.scad -> build.py -> STL + PNG views + report
                  ^                                        |
                  +---------------- Claude inspects -------+
        (sees renders + reads report; edits .scad; repeats until good)
                                     |
                          hand off to print-to-bambu
```

Claude writes the OpenSCAD (guided by the cheat-sheet); the script produces the
artifacts; Claude inspects renders (vision) + the validation report and iterates.

## Components — `.claude/skills/design-stl/`

| File | Role |
|------|------|
| `SKILL.md` | the loop, when to iterate, hand-off to print-to-bambu |
| `scripts/build.py` | `model.scad` → export STL + render PNG views + validate → consolidated JSON (stdout) + human summary (stderr) |
| `scripts/validate.py` | analyze any STL; importable by build.py and runnable standalone |
| `reference/openscad-cheatsheet.md` | CSG/transforms/modules/`$fn` + printability tips |
| `requirements.txt` | `trimesh` |

`build.py model.scad` is the single per-iteration command: scad → STL → PNGs →
validation, all reported together.

## Data flow

1. Claude writes `model.scad` from the description (using the cheat-sheet).
2. `build.py model.scad`:
   - OpenSCAD `-o model.stl model.scad` (capture warnings).
   - OpenSCAD PNG renders for configured views (iso, front, top) via
     `--camera ... --imgsize ... -o view.png --render`.
   - `validate.py` on the STL.
   - Emit consolidated report; PNG paths included so Claude can view them.
3. Claude inspects; if any check fails or a render looks wrong, edit `.scad`,
   re-run. Loop until clean.
4. Hand `model.stl` to `print-to-bambu` (optional `view.py` 3D preview, then
   slice → confirm → print).

## Validation (`validate.py`)

- **Bed fit** — bounding box vs bed `[design].bed` (default X2D **256×256×260 mm**);
  fail if any axis exceeds.
- **Mesh integrity** (trimesh) — `is_watertight`, `is_winding_consistent`, volume,
  triangle count. Non-watertight → flag (likely not printable).
- **Min wall thickness** — `trimesh.proximity.thickness` on sampled surface points;
  report min and flag below `[design].min_wall` (default **0.8 mm**). Documented as
  an approximate heuristic.
- **Overhangs** — using face normals, fraction of downward-facing area whose angle
  from the build plane exceeds `[design].overhang_angle` (default **45°**) →
  "may need supports."
- **OpenSCAD warnings** — surfaced from build.py (non-manifold/empty geometry).

Output: JSON `{bed_fit, dims, watertight, volume_mm3, triangles, min_wall_mm,
overhang_fraction, warnings, ok}` + a human ✓/✗ summary. Exit non-zero if a
hard check (bed fit, watertight) fails.

## Config additions (`bambu.toml` / `bambu.toml.example`)

```toml
[design]
bed           = [256, 256, 260]   # X2D; W, D, H in mm
min_wall      = 0.8               # mm; flag thinner features
overhang_angle = 45               # deg from build plane; steeper => supports
views         = ["iso", "front", "top"]
```

All optional; `validate.py`/`build.py` fall back to these defaults if absent.

## Dependencies & onboarding

- **OpenSCAD binary** — `brew install openscad` (macOS) or distro package.
- **trimesh** — `pip install -r .claude/skills/design-stl/requirements.txt`.
- Extend the **`/onboard`** skill with a "design" section covering both.
- `build.py` fails fast with an install hint if OpenSCAD or trimesh is missing.

## Error handling

- OpenSCAD missing → clear install message.
- OpenSCAD compile error → surface stderr, no STL produced, exit non-zero.
- trimesh missing → install hint (validation degrades to bed-fit only rather than
  crashing).
- Empty/zero-triangle STL → flagged as failed geometry.

## Implementation status (2026-06-17)

Implemented on branch `design-stl`. `build.py` dispatches by extension: `.py`
trimesh builder (default) or `.scad` (OpenSCAD, optional). Verified on this
machine:
- **trimesh path** end-to-end: a watertight H₂O builder → STL + 3 matplotlib
  preview PNGs + validation; `watertight=true`, fits bed, `ok=true`. The iso
  preview was visually confirmed to be a correct water molecule.
- **validate.py** on the repo's `hydrogen_molecule.stl` → correctly flags it
  **not watertight** (the hand-built mesh just concatenates triangles).
- **min-wall** uses a 5th-percentile thickness (absolute min spikes to ~0 at
  concave CSG seams); documented as approximate / over-flags seams.
- **OpenSCAD path** falls back cleanly with an install hint when the binary is
  absent. (On this machine the Homebrew cask install was incomplete — dangling
  symlink, empty app — so the optional path is coded but not yet run here.)
- Fixed a stale-output bug: `build.py` now deletes prior STL/PNGs before building
  so a previous run's files can't masquerade as success.

Deps added: trimesh, manifold3d (boolean union → watertight), matplotlib
(headless previews), scipy + rtree (proximity/thickness).

## Testing

- `validate.py` against the repo's `hydrogen_molecule.stl` (~45×20×20 mm) —
  exercises every check on a real model.
- `build.py` on a tiny `.scad` (a sphere) — proves scad → STL → PNG → report.
- Bed-fit fail path with a deliberately oversized box.

## Distribution

In-repo, committed. Generated artifacts (`*.scad` optional, `*.stl` already
ignored, `*.preview*.png`, `*.viewer.html`) gitignored. No secrets involved.
