#!/usr/bin/env python3
"""Generate a self-contained 3D HTML viewer for an STL so you can orbit/zoom it.

Embeds the STL (base64) into one HTML file that loads three.js from a CDN and
renders the mesh with orbit controls, a ground grid, and a dimensions readout.
Open it in any browser; no local server needed (internet needed for the CDN).

  python3 view.py model.stl                 # writes model.viewer.html
  python3 view.py model.stl -o out.html --open
"""
from __future__ import annotations

import argparse
import base64
import struct
import subprocess
import sys
from pathlib import Path


def stl_bbox(data: bytes) -> tuple[tuple, tuple] | None:
    """Return (min_xyz, max_xyz) for a binary STL, or None if not parseable."""
    if len(data) < 84:
        return None
    # Binary STL: 80-byte header, uint32 triangle count, then 50 bytes/triangle.
    (n_tri,) = struct.unpack_from("<I", data, 80)
    if 84 + n_tri * 50 != len(data):
        return None  # likely ASCII STL; skip bbox (viewer still renders it)
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    off = 84
    for _ in range(n_tri):
        off += 12  # skip normal
        for _v in range(3):
            x, y, z = struct.unpack_from("<3f", data, off)
            off += 12
            for i, c in enumerate((x, y, z)):
                lo[i] = min(lo[i], c)
                hi[i] = max(hi[i], c)
        off += 2  # attribute byte count
    return tuple(lo), tuple(hi)


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
  html,body{{margin:0;height:100%;background:#1e2228;color:#e6e6e6;
    font-family:-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}}
  #info{{position:fixed;top:12px;left:12px;padding:10px 12px;background:#0008;
    border-radius:8px;font-size:13px;line-height:1.5;pointer-events:none}}
  #info b{{color:#7fd1ff}}
  #hint{{position:fixed;bottom:12px;left:12px;font-size:12px;color:#9aa4ad}}
</style>
</head>
<body>
<div id="info"><b>{title}</b><br/>{dims}</div>
<div id="hint">drag = rotate · scroll = zoom · right-drag = pan</div>
<script type="importmap">
{{ "imports": {{
  "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
  "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
}} }}
</script>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
import {{ STLLoader }} from 'three/addons/loaders/STLLoader.js';

const b64 = "{b64}";
const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1e2228);
const camera = new THREE.PerspectiveCamera(45, innerWidth/innerHeight, 0.1, 100000);
const renderer = new THREE.WebGLRenderer({{antialias:true}});
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);

scene.add(new THREE.HemisphereLight(0xffffff, 0x335577, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 1.4);
key.position.set(1, 1.5, 1); scene.add(key);

const geo = new STLLoader().parse(bin.buffer);
geo.computeVertexNormals();
geo.computeBoundingBox();
const bb = geo.boundingBox, c = new THREE.Vector3(), s = new THREE.Vector3();
bb.getCenter(c); bb.getSize(s);
geo.translate(-c.x, -c.y, -c.z);  // center at origin

const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial(
  {{color:0x9fb6c9, metalness:0.15, roughness:0.55, flatShading:false}}));
scene.add(mesh);

const radius = Math.max(s.x, s.y, s.z);
const grid = new THREE.GridHelper(radius*4, 20, 0x55606a, 0x333a42);
grid.position.y = -s.y/2; scene.add(grid);

camera.position.set(radius*1.4, radius*1.1, radius*1.8);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(0,0,0);

addEventListener('resize', () => {{
  camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}});
(function loop(){{ requestAnimationFrame(loop); controls.update();
  renderer.render(scene, camera); }})();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stl", help="STL file to view")
    ap.add_argument("-o", "--output", help="output HTML (default: <stl>.viewer.html)")
    ap.add_argument("--open", action="store_true", help="open in the default browser")
    args = ap.parse_args()

    stl = Path(args.stl).expanduser().resolve()
    if not stl.is_file():
        print(f"✗ STL not found: {stl}", file=sys.stderr)
        return 1
    data = stl.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")

    bbox = stl_bbox(data)
    if bbox:
        lo, hi = bbox
        dims = "size: %.1f × %.1f × %.1f mm" % (
            hi[0]-lo[0], hi[1]-lo[1], hi[2]-lo[2])
    else:
        dims = f"{len(data):,} bytes"

    out = Path(args.output).expanduser().resolve() if args.output else \
        stl.with_suffix(".viewer.html")
    out.write_text(HTML.format(title=stl.name, dims=dims, b64=b64))
    print(f"✓ Wrote {out}  ({out.stat().st_size:,} bytes)  [{dims}]")

    if args.open:
        opener = {"darwin": "open", "linux": "xdg-open"}.get(sys.platform, None)
        if opener:
            subprocess.run([opener, str(out)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
