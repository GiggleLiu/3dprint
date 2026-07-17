---
name: preview-stl
description: Use when the user wants to present or inspect STL models in the browser (a single self-contained HTML viewer page, works offline) and/or physically simulate a ball rolling through printed geometry (marble runs, tracks, funnels, tunnels) with the trajectory animated inside the viewer. Complements design-stl (static PNG previews + printability checks) with interactive 3D and dynamic validation.
---

# Preview STLs in HTML + physics-simulate rolling geometry

Two scripts that pair up: `build_viewer.py` bakes STLs into **one dependency-free
HTML page** (embedded WebGL viewer — orbit/zoom/pan, multi-part scenes with a
legend and visibility toggles, translucent "ghost" parts, and an animated ball);
`simulate_ball.py` rolls a sphere through the **actual exported meshes** under
tilted gravity and emits a trajectory JSON the viewer plays back as an animation.

Prereqs: `pip install -r requirements.txt` (venv interpreter). For headless page
verification: `npm i -g playwright && npx playwright install chromium`.

## Viewer workflow

1. One-command demo from part STLs that share an exported coordinate frame:
   `scripts/build_viewer.py --demo --out viewer.html --title "My assembly"
   base.stl lid.stl insert.stl`. This creates a color-coded assembly with
   visibility toggles plus an automatically separated exploded view. A single
   STL produces one assembly scene.
2. Quick look at loose files, with one scene per file:
   `scripts/build_viewer.py --out viewer.html --title "My part" a.stl b.stl`
3. Authored presentations: write a **manifest.json** (schema in the script header) —
   one scene per view, each scene a list of parts with `name`/`color`/optional
   `alpha` (translucent) / `translate` / `rotate`. Good scene vocabulary:
   - **exploded stack** — translate each layer up by a constant;
   - **populated assembly** — same STL instanced at several translations;
   - **negative space** — export the *cut* solids (the air a ball rolls
     through) as their own STLs and show them instead of the part; internal
     channels are invisible any other way;
   - **ghost** — `alpha` ≈ 0.45 part over an opaque interior.
4. **Verify headlessly, always** (a viewer that renders black is worse than
   none): `NODE_PATH=$(npm root -g) node scripts/verify_page.cjs viewer.html
   /tmp/shots` — fails on console errors, WebGL probe errors, or a scene with
   too few non-background pixels; it saves each canvas directly (avoiding
   headless GPU-compositing artifacts), then actually LOOK at the screenshots.

How it stays self-contained: meshes are baked with trimesh (transforms applied),
exported binary STL, gzip+base64-embedded; the page inflates them with the
browser-native `DecompressionStream` — no CDN, no fetch, shareable as one file.
Transparency is a two-pass draw (opaque parts + ball first, then blended parts
with the depth mask off); the animated ball is a per-frame `uOff` uniform, so
playback costs nothing.

## Physics-sim workflow (dynamic validation of rolling geometry)

Static clearance checks (sweep a sphere along the intended centerline) prove a
ball *fits*; only dynamics proves it *arrives*. Simulate against the **shipped
STLs**, not the CAD — tessellation is part of the geometry (and regenerate STLs
before re-running, or you validate stale meshes).

```sh
.venv/bin/python scripts/simulate_ball.py \
  --stl plate_base.stl --stl cartridge.stl --translate 0,0,0 --translate 0,150,0 \
  --start 0,206,40 --radius 3 --tilt 12 --tmax 6 \
  --stop 'y < 50' --name channel --out sims/channel.json
```

Exit 0 + `REACHED STOP` means the ball traversed and left through the intended
port; `STUCK` prints where — load that scene in the viewer with the sim JSON
attached (`"anim": "sims/channel.json"`) and watch where it dies. The model:
semi-implicit Euler (dt 2e-4), closest-point contact per nearby part,
restitution 0.30, **global** linear drag 0.5/s (do NOT damp per contact-step —
at dt=2e-4 even 1% per step is absurdly overdamped), tunneling ejection.
Gravity convention: parts modeled lying in xy, board played leaning back by
`--tilt` degrees; -y is down-the-board.

### Design rules the simulation will enforce (learned the hard way)

- **Climb margin**: on a board tilted t from vertical, a rolling ball can only
  climb a channel whose rise-per-board-distance stays well under cot(t); keep
  ≥2x margin or shallow the tilt. Check this *before* building the geometry.
- **Eased corners are gravity traps**: a fillet/easing pocket at a bend in a
  descending channel becomes a local minimum the ball parks in. Prefer one
  smooth swept tube (circular profile perpendicular to a spline path) over
  straight segments + eased corners; keep the path's bend radius everywhere
  larger than the tube radius or the sweep self-intersects into folds.
- **Drop points**: a ball dropped down a shaft onto the *end* of a groove
  wedges on the end-cap lip — land it a few mm *down-track* from the end.
- **Sockets/gaps**: anywhere two parts meet across a clearance gap on the
  ball's path (e.g. a plate socket and an insert), the sim will find the
  corner where the gap opens; chamfered/keyed corners are prime stuck spots.
- Verify each moving-part in isolation first (fast: one small mesh), then the
  full assembly end-to-end (slow: minutes — run it in the background).

## Handoffs

`design-stl` builds the model → **preview-stl** presents it and dynamically
validates it → `print-to-bambu` prints it. Trajectory JSONs are small; commit
them next to the viewer so the page can be rebuilt without re-simulating.
