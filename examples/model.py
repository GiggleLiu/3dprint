"""QudeLeap logo desk standee — raised line-art panel + slotted base.

Two parts, laid flat on one plate:
  * panel  — solid slab with the logo's line-art raised on the front face,
             built as a single watertight heightmap prism straight from the
             logo PNG's colored ink (no hand-tracing, no vectorization libs).
  * base   — block with a centered slot the panel slides into to stand upright.

Engine: trimesh (+ numpy/scipy/PIL — all already installed). All units mm.
See docs/superpowers/specs/2026-06-17-qudeleap-standee-design.md.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from scipy import ndimage

# ---------------------------------------------------------------- parameters
IMG = Path(__file__).resolve().parent / "assets" / "qudeleap_logo.png"

PANEL_W      = 100.0    # panel width (mm)
SIDE_MARGIN  = 5.0      # blank border left/right
TOP_MARGIN   = 5.0      # blank border above the logo
BOTTOM_MARGIN = 16.0    # blank skirt below logo (buried in the base slot)
SLAB_THICK   = 3.5      # panel slab thickness
LINE_HEIGHT  = 1.2      # how far the line-art stands proud of the slab
CELL_MM      = 0.35     # heightmap grid resolution (mesh step size)
MIN_EXTRA_MM = 0.16     # half the width added by dilation (fattens thin strokes)
SMOOTH_CELLS = 0.6      # gaussian sigma (in cells) to soften stair-steps

# base / slot
BASE_W       = 110.0
BASE_D       = 34.0
BASE_H       = 16.0
SLOT_CLEAR   = 0.3      # added to slab thickness -> slot width
SLOT_DEPTH   = 12.0
PLATE_GAP    = 12.0     # gap between panel and base on the print plate


# ---------------------------------------------------------------- mask
def _ink_mask() -> np.ndarray:
    """Binary 'ink' mask of the logo (True = colored stroke), cropped to bbox.

    Background is white; the logo is colored/dark. Ink = opaque AND not
    near-white.
    """
    a = np.asarray(Image.open(IMG).convert("RGBA"), dtype=float)
    rgb, alpha = a[..., :3], a[..., 3]
    ink = (alpha > 128) & (rgb.mean(2) < 235)
    ys, xs = np.where(ink)
    return ink[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1]


def _level_field(n_rows: int, n_cols: int) -> np.ndarray:
    """Resampled, anti-aliased ink coverage in [0, 1] on the content grid.

    Rows are flipped so the logo stands upright (image row 0 = top of art).
    """
    mask = _ink_mask().astype(float)
    h0, w0 = mask.shape
    drawable_w = PANEL_W - 2 * SIDE_MARGIN
    mm_per_px = drawable_w / w0

    # Fatten thin strokes so even the finest line clears the min wall.
    r = max(1, round(MIN_EXTRA_MM / mm_per_px))
    mask = ndimage.binary_dilation(mask, iterations=r).astype(float)

    # Downsample to the mesh grid; order=1 + low threshold keeps thin lines.
    lvl = ndimage.zoom(mask, (n_rows / h0, n_cols / w0), order=1)
    lvl = np.clip((lvl - 0.30) / 0.30, 0.0, 1.0)     # soft ramp 0.30..0.60
    return np.flipud(lvl)                            # image-top -> world-top


# ---------------------------------------------------------------- heightmap solid
def _heightmap_prism(x: np.ndarray, y: np.ndarray, Z: np.ndarray) -> trimesh.Trimesh:
    """Closed solid: relief top surface Z(x, y), flat bottom at z=0, side walls."""
    ny, nx = Z.shape
    X, Y = np.meshgrid(x, y)
    N = nx * ny
    top = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    bot = np.column_stack([X.ravel(), Y.ravel(), np.zeros(N)])
    verts = np.vstack([top, bot])

    idx = np.arange(N).reshape(ny, nx)          # top vertex indices
    bidx = idx + N                              # bottom vertex indices

    def grid_faces(g, flip):
        a, b, c, d = g[:-1, :-1], g[:-1, 1:], g[1:, 1:], g[1:, :-1]
        t1 = np.stack([a, b, c], -1).reshape(-1, 3)
        t2 = np.stack([a, c, d], -1).reshape(-1, 3)
        f = np.vstack([t1, t2])
        return f[:, ::-1] if flip else f

    faces = [grid_faces(idx, False),            # top  (+z)
             grid_faces(bidx, True)]            # bottom (-z)

    def wall(t, b):                             # quad strip t[i],t[i+1] over b
        a0, a1, b0, b1 = t[:-1], t[1:], b[:-1], b[1:]
        return np.vstack([np.stack([a0, b0, b1], -1),
                          np.stack([a0, b1, a1], -1)])

    faces += [wall(idx[0, :], bidx[0, :]), wall(idx[-1, :], bidx[-1, :]),
              wall(idx[:, 0], bidx[:, 0]), wall(idx[:, -1], bidx[:, -1])]

    m = trimesh.Trimesh(vertices=verts, faces=np.vstack(faces), process=True)
    m.fix_normals()
    return m


def _panel() -> trimesh.Trimesh:
    drawable_w = PANEL_W - 2 * SIDE_MARGIN
    cw = round(drawable_w / CELL_MM)
    # content height from the logo's own aspect ratio
    mh, mw = _ink_mask().shape
    content_h = drawable_w * mh / mw
    ch = round(content_h / CELL_MM)
    panel_h = content_h + TOP_MARGIN + BOTTOM_MARGIN

    nx = round(PANEL_W / CELL_MM)
    ny = round(panel_h / CELL_MM)
    x = np.linspace(0.0, PANEL_W, nx)
    y = np.linspace(0.0, panel_h, ny)

    Z = np.full((ny, nx), SLAB_THICK)
    lvl = _level_field(ch, cw)
    c0 = round(SIDE_MARGIN / CELL_MM)
    r0 = round(BOTTOM_MARGIN / CELL_MM)
    Z[r0: r0 + lvl.shape[0], c0: c0 + lvl.shape[1]] += LINE_HEIGHT * lvl

    Z = ndimage.gaussian_filter(Z, SMOOTH_CELLS)     # soften stair-steps

    panel = _heightmap_prism(x, y, Z)
    panel.apply_translation([-PANEL_W / 2.0, -panel_h / 2.0, 0.0])
    return panel


def _base(panel_h: float) -> trimesh.Trimesh:
    base = trimesh.creation.box(extents=[BASE_W, BASE_D, BASE_H])
    base.apply_translation([0, 0, BASE_H / 2.0])     # rest on z=0

    slot = trimesh.creation.box(
        extents=[PANEL_W + 0.4, SLAB_THICK + SLOT_CLEAR, SLOT_DEPTH + 1.0])
    slot.apply_translation([0, 0, BASE_H - SLOT_DEPTH + (SLOT_DEPTH + 1.0) / 2.0])
    base = trimesh.boolean.difference([base, slot])

    # park the base below the panel on the plate
    base.apply_translation([0, -(panel_h / 2.0 + PLATE_GAP + BASE_D / 2.0), 0])
    return base


def build() -> trimesh.Trimesh:
    drawable_w = PANEL_W - 2 * SIDE_MARGIN
    mh, mw = _ink_mask().shape
    panel_h = drawable_w * mh / mw + TOP_MARGIN + BOTTOM_MARGIN

    panel = _panel()
    base = _base(panel_h)
    return trimesh.util.concatenate([panel, base])


if __name__ == "__main__":
    m = build()
    print("watertight:", m.is_watertight, "tris:", len(m.faces),
          "bounds:", m.bounds.tolist())
