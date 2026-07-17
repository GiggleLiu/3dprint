#!/usr/bin/env python
"""Roll a ball through STL geometry under (optionally tilted) gravity.

Sphere-vs-mesh penalty contact: semi-implicit Euler; each step query the
closest surface point of every nearby part (trimesh ProximityQuery); if the
ball center is within the ball radius, project out along the contact normal,
reflect the inward normal velocity with restitution, and apply a global
linear drag (rolling + air). If the center tunnels inside a solid, eject it
to the surface. This is the dynamic sibling of static swept-clearance
checks: the ball must actually traverse the print and exit where intended.

Output JSON: {"name", "traj" [[x,y,z]...], "fps", "ok", "exit", "ball_r"} —
directly consumable by build_viewer.py as a scene "anim".

CLI example (6mm ball dropped into a track, board leaned 12 degrees):
  .venv/bin/python simulate_ball.py --stl plate.stl --stl cart.stl \
    --start 0,206,40 --vel 0,0,0 --radius 3 --tilt 12 --tmax 6 \
    --stop 'y < 50' --name channel --out sims/channel.json

Library use: from simulate_ball import Part, simulate
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import trimesh


class Part:
    def __init__(self, mesh: trimesh.Trimesh, radius: float):
        self.pq = trimesh.proximity.ProximityQuery(mesh)
        self.lo = mesh.bounds[0] - (radius + 4)
        self.hi = mesh.bounds[1] + (radius + 4)

    def near(self, c):
        return np.all(c > self.lo) and np.all(c < self.hi)


def simulate(parts, c0, v0, radius, tilt_deg, t_max, stop, *,
             g=9810.0, dt=2e-4, rest=0.30, drag=0.5, fps=120):
    """parts: list[Part]; c0/v0: mm, mm/s; stop: callable(c) -> bool.

    Gravity acts in -z, tilted by tilt_deg about x (board leaned back), so a
    'flat' groove in +y flows downhill: G = (0, -g sin? no --) we tilt the
    gravity vector instead of the mesh: gy = -g*cos(tilt) is wrong for a
    board standing near-vertical. Convention used here (board plates built
    lying in xy, played leaning back by tilt from vertical):
      GRAV = (0, -g*cos(tilt), -g*sin(tilt))
    i.e. -y is 'down the board', -z presses the ball into the grooves.
    """
    tilt = math.radians(tilt_deg)
    grav = np.array([0.0, -g * math.cos(tilt), -g * math.sin(tilt)])
    c = np.array(c0, float)
    v = np.array(v0, float)
    traj = [c.tolist()]
    rec_every = int(round(1 / (fps * dt)))
    for step in range(1, int(t_max / dt) + 1):
        v += grav * dt
        v *= 1.0 - drag * dt
        c += v * dt
        for p in parts:
            if not p.near(c):
                continue
            closest, dist, _ = p.pq.on_surface(c[None, :])
            n = c - closest[0]
            nn = np.linalg.norm(n)
            if nn < 1e-9:
                continue
            n = n / nn
            if p.pq.signed_distance(c[None, :])[0] > 0:
                # tunneled into solid: eject to the surface, bleed speed
                c = closest[0] + (closest[0] - c) / max(nn, 1e-9) * radius
                v *= 0.2
                continue
            d = float(dist[0])
            if d < radius:
                c += n * (radius - d)
                vn = float(v @ n)
                if vn < 0:
                    v = (v - vn * n) - rest * vn * n
        if step % rec_every == 0:
            traj.append(c.tolist())
        if stop(c):
            traj.append(c.tolist())
            return np.array(traj), True
    return np.array(traj), False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stl", action="append", required=True,
                    help="mesh the ball collides with (repeatable)")
    ap.add_argument("--translate", action="append", default=[],
                    help="dx,dy,dz applied to the matching --stl (positional pairing; "
                         "pass '0,0,0' for parts that stay put)")
    ap.add_argument("--start", required=True, help="x,y,z ball-center start (mm)")
    ap.add_argument("--vel", default="0,0,0", help="x,y,z initial velocity (mm/s)")
    ap.add_argument("--radius", type=float, default=3.0)
    ap.add_argument("--tilt", type=float, default=0.0, help="board lean, degrees")
    ap.add_argument("--tmax", type=float, default=6.0)
    ap.add_argument("--stop", default="False",
                    help="python expr over x,y,z — sim succeeds when true, "
                         "e.g. 'y < -14.2'")
    ap.add_argument("--rest", type=float, default=0.30)
    ap.add_argument("--drag", type=float, default=0.5)
    ap.add_argument("--fps", type=int, default=120)
    ap.add_argument("--name", default="sim")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    vec = lambda s: [float(t) for t in s.split(",")]
    parts = []
    for i, f in enumerate(a.stl):
        m = trimesh.load(f)
        if i < len(a.translate):
            m.apply_translation(vec(a.translate[i]))
        parts.append(Part(m, a.radius))
    stop = lambda c: bool(eval(a.stop, {}, {"x": c[0], "y": c[1], "z": c[2]}))
    traj, ok = simulate(parts, vec(a.start), vec(a.vel), a.radius, a.tilt,
                        a.tmax, stop, rest=a.rest, drag=a.drag, fps=a.fps)
    end = traj[-1]
    print(f"{a.name}: {'REACHED STOP' if ok else 'STUCK/TIMEOUT'} at "
          f"x={end[0]:+.1f} y={end[1]:.1f} z={end[2]:.1f} "
          f"({traj.shape[0] / a.fps:.2f}s)")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "name": a.name, "traj": np.round(traj, 2).tolist(), "fps": a.fps,
        "ok": bool(ok), "exit": [round(float(v), 2) for v in end],
        "ball_r": a.radius}))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
