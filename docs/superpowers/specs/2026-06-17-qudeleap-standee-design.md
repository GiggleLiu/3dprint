# QudeLeap Logo Standee — Design Spec

**Date:** 2026-06-17
**Status:** Approved
**Target printer:** Bambu Lab X2D (256×256×260 bed), single extruder / no AMS, PLA.

## Concept

A two-part vertical desk standee of the QudeLeap logo. The full logo — the
leaping line-art horse, the R/track ring, the "QudeLeap" wordmark, and the
"幻码跃迁" line with its flanking dashes — appears as **raised line-art on a
solid panel**. The panel slides into a **slotted base** and stands upright.
Single color.

## Source & geometry approach

Source image: the QudeLeap logo PNG (1402×1122 RGBA), content bounding box
1049×910 px (aspect w/h ≈ 1.15).

The logo is **line-art** (colored strokes on white). We reproduce it faithfully
by thresholding the PNG into a binary "ink" mask (opaque AND not near-white),
then extruding that mask as a **heightmap solid**: a regular grid where ink
pixels rise to the line height and background sits at the panel surface, with a
flat back face and perimeter walls. This is watertight by construction, uses
only already-installed libraries (numpy, scipy, PIL, trimesh), and robustly
handles the many tiny holes and thin strokes.

**Rejected alternative:** vectorizing the mask into polygons (contour trace →
polygon extrude). It needs uninstalled libs (shapely / opencv / earcut) and
produces fragile slivers on fine line-art.

### Stroke-width check (measured from the PNG)
- Median stroke width ≈ 1.5 mm at target scale (safe).
- Thinnest features ≈ 0.69 mm — just under the 0.8 mm min wall.
- **Fix:** a 1px binary dilation of the mask lifts thin strokes to ≈ 1.0 mm.

## Part 1 — Panel

| Property | Value |
|---|---|
| Width | 100 mm (5 mm side margins → 90 mm drawable content) |
| Height | ≈ 99 mm (top margin 5 mm + content 78 mm + bottom margin 16 mm) |
| Slab thickness | 3.5 mm |
| Raised line height | +1.0 mm (≈ 5 layers @ 0.2 mm) |
| Thin-stroke fix | 1px dilation → min stroke ≈ 1.0 mm |
| Grid resolution | ≈ 0.12 mm/px (downsampled) — clean steps, manageable mesh |

The bottom 16 mm of the panel is intentionally **blank** so the slot never
buries the "幻码跃迁" text/dashes. ~87 mm of panel is visible above the base.

## Part 2 — Base

| Property | Value |
|---|---|
| Size | 110 × 34 × 16 mm block |
| Slot | centered groove, 3.8 mm wide (3.5 mm panel + 0.3 mm clearance) × 12 mm deep |
| Orientation | vertical slot (panel stands straight; 34 mm depth keeps it stable) |

## Print plan

- Both parts laid **flat on one plate**: panel lying down with **raised lines
  facing up** (no supports — relief is top-facing); base beside it (slot opens
  upward — no supports).
- Profile: `0.20mm Standard @BBL X2D`, ~15% infill, PLA. Est. ~2–3 h.
- Assembly: friction fit; adjust the 0.3 mm slot clearance or sand lightly if
  tight.

## Pipeline & validation

1. `model.py` — a parameterized trimesh builder (width, slab/line thickness,
   margins, slot clearance, dilation, grid resolution) that returns/exports the
   panel + base arranged on one plate.
2. `design-stl/build.py model.py` → STL + iso/front/top previews + printability
   report (bed fit / watertight / min-wall / overhangs). Iterate until clean.
3. `print-to-bambu`: `view.py` → `slice.py` → review summary → confirm →
   `send.py` → `monitor.py`.
4. Output: `qudeleap_standee.stl` (both parts on the plate), committed.

## Parameters (defaults)

```
panel_width      = 100.0   # mm
side_margin      = 5.0
top_margin       = 5.0
bottom_margin    = 16.0
slab_thickness   = 3.5
line_height      = 1.0
dilation_px      = 1        # at source resolution before downsample
grid_mm_per_px   = 0.12     # downsample target
base_w, base_d, base_h = 110.0, 34.0, 16.0
slot_clearance   = 0.3
slot_depth       = 12.0
```
