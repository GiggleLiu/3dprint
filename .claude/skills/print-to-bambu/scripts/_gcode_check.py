"""G-code sanity checks shared by slice.py: printing-over-air detection.

The model-side overhang fraction says nothing about whether the SLICED job is
actually printable — that depends on whether the slicer put support (or model)
material under each overhang. This replays every extrusion move into a coarse
per-layer occupancy grid and measures the area printed over air: cells whose
layer below (8-neighbor dilated, so 45-degree stepping counts as supported)
holds no material at all. Prime tower / skirt / brim are excluded.

Pure stdlib, resolution ~1 mm — a screening gate, not a simulation. Bridges
anchored at both ends also show up; small values are usually fine.
"""
from __future__ import annotations

import re

CELL = 1.0          # mm grid
SAMPLE = 0.7        # mm sampling step along extrusion segments
EXCLUDE_FEATURES = ("prime tower", "skirt", "brim", "flush")

_MOVE = re.compile(
    r"^G[123](?=[^;\n]*\sE(?P<e>-?[\d.]+))?(?=[^;\n]*\sX(?P<x>-?[\d.]+))?"
    r"(?=[^;\n]*\sY(?P<y>-?[\d.]+))?(?=[^;\n]*\sZ(?P<z>-?[\d.]+))?\s",
    re.MULTILINE)


def _cells_for_segment(x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    dist = (dx * dx + dy * dy) ** 0.5
    steps = max(1, int(dist / SAMPLE))
    for i in range(steps + 1):
        t = i / steps
        yield (round((x0 + dx * t) / CELL), round((y0 + dy * t) / CELL))


def _neighbors(cell):
    cx, cy = cell
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            yield (cx + ox, cy + oy)


def over_air_report(gcode: str, max_layers_reported: int = 5) -> dict | None:
    """Measure extrusion-over-air per layer. Returns None if no layers found."""
    layers = gcode.split("; CHANGE_LAYER")
    if len(layers) < 3:
        layers = gcode.split(";LAYER_CHANGE")
    if len(layers) < 3:
        return None

    x = y = None
    # Union of the last few layers: supports sit 1-2 layers below the object
    # (support_top_z_distance), so "supported" must look through that gap.
    LOOKBACK = 3
    recent: list = []       # last LOOKBACK layers' raw cell sets
    prev_dilated: set = set()
    total_mm2 = 0.0
    worst: list[tuple[float, float]] = []  # (mm2, z)
    for li, chunk in enumerate(layers[1:], start=1):
        zm = re.search(r";\s*Z_HEIGHT:\s*([\d.]+)", chunk) or \
            re.search(r";\s*Z:\s*([\d.]+)", chunk)
        z = float(zm.group(1)) if zm else None
        feature = ""
        cur: set = set()
        over_air: set = set()
        for line in chunk.splitlines():
            if line.startswith("; FEATURE:"):
                feature = line.split(":", 1)[1].strip().lower()
                continue
            if not line.startswith(("G1", "G2", "G3")):
                continue
            m = _MOVE.match(line)
            if not m:
                continue
            nx = float(m["x"]) if m["x"] else x
            ny = float(m["y"]) if m["y"] else y
            e = float(m["e"]) if m["e"] else 0.0
            if e > 0 and x is not None and nx is not None \
                    and not any(k in feature for k in EXCLUDE_FEATURES):
                for cell in _cells_for_segment(x, y, nx, ny):
                    cur.add(cell)
                    if li > 1 and cell not in prev_dilated:
                        over_air.add(cell)
            if nx is not None:
                x, y = nx, ny
        if over_air:
            mm2 = len(over_air) * CELL * CELL
            total_mm2 += mm2
            worst.append((mm2, z if z is not None else -1))
        recent.append(cur)
        recent = recent[-LOOKBACK:]
        prev_dilated = set()
        for layer_cells in recent:
            for cell in layer_cells:
                prev_dilated.update(_neighbors(cell))

    worst.sort(reverse=True)
    return {
        "over_air_mm2": round(total_mm2, 1),
        "worst_layers": [{"z": z, "mm2": round(a, 1)}
                         for a, z in worst[:max_layers_reported]],
    }
