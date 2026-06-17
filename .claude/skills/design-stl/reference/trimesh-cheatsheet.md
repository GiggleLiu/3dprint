# trimesh builder cheat-sheet (the default engine)

Write a Python file that builds a **watertight** `trimesh.Trimesh`. `build.py`
runs it, exports the STL, renders previews, and validates. Everything is in **mm**.

## The contract
Define `build()` returning a single `trimesh.Trimesh` (or a module-level `model`):
```python
import trimesh

def build():
    return trimesh.creation.box(extents=[20, 20, 20])
```

## Primitives
```python
trimesh.creation.icosphere(subdivisions=3, radius=10)   # smooth sphere (~1280 faces)
trimesh.creation.box(extents=[x, y, z])                 # centered at origin
trimesh.creation.cylinder(radius=3, height=20)          # along +Z, centered
trimesh.creation.cylinder(radius=3, segment=[p1, p2])   # spans two 3D points
trimesh.creation.capsule(radius=2, height=20)
```

## Place / move
```python
m = trimesh.creation.icosphere(radius=8)
m.apply_translation([x, y, z])
m.apply_transform(trimesh.transformations.rotation_matrix(angle_rad, [0, 0, 1]))
```

## Watertight = use boolean union (NOT concatenation)
The #1 printability rule. Overlap parts, then union them — the `manifold3d`
backend returns a clean 2-manifold solid. Concatenating meshes (or
`trimesh.util.concatenate`) leaves internal walls → **not watertight**.
```python
parts = [atom1, atom2, bond]          # make them physically overlap
solid = trimesh.boolean.union(parts)  # manifold3d -> watertight
```
Other booleans: `trimesh.boolean.difference([a, b])`, `.intersection([...])`.

## Worked example — a molecule
```python
import math, numpy as np, trimesh

def atom(c, r):
    s = trimesh.creation.icosphere(subdivisions=3, radius=r)
    s.apply_translation(c); return s

def bond(p1, p2, r):                       # overlaps both atoms -> no seam gap
    return trimesh.creation.cylinder(radius=r, segment=[p1, p2])

def build():
    d, ang = 16.0, 104.5
    o  = np.array([0, 0, 0.0])
    h1 = np.array([d*math.cos(math.radians(ang/2)),  d*math.sin(math.radians(ang/2)), 0])
    h2 = np.array([d*math.cos(math.radians(ang/2)), -d*math.sin(math.radians(ang/2)), 0])
    return trimesh.boolean.union([atom(o, 12), atom(h1, 7), atom(h2, 7),
                                  bond(o, h1, 3), bond(o, h2, 3)])
```

## Why Python over OpenSCAD here
You have numpy + real data: build from actual atomic coordinates, generate
lattices, sweep parametric families, or read a `z = f(x, y)` surface — none of
which OpenSCAD does well. Use `build.py model.scad` only if you specifically want
OpenSCAD CSG and the binary is installed.

## Printability (what the validator checks)
- **Watertight** — union, don't concatenate (see above).
- **Min feature ≥ ~0.8 mm** (2× a 0.4 nozzle line). The wall check is approximate
  and over-flags concave CSG seams — treat low values as "look for genuinely thin
  spikes/plates," not a hard fail.
- **Overhangs** shallower than ~45° need supports; a small flat base helps adhesion.
- **Fit the bed** (X2D 256×256×260). Rest the model near z = 0.
