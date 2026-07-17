#!/usr/bin/env python
"""Build a single self-contained HTML page that 3D-views STL models.

Meshes are baked (transforms applied) with trimesh, exported binary STL,
gzipped + base64-embedded; the page inflates them with the browser-native
DecompressionStream and renders with a small dependency-free WebGL viewer
(orbit / zoom / pan, per-part legend with visibility toggles, optional
translucent parts, optional animated ball following a physics trajectory
from simulate_ball.py). Nothing is fetched at view time — the file works
offline and can be shared as-is.

Two input modes:
  build_viewer.py --out viewer.html a.stl b.stl        # one scene per file
  build_viewer.py --out viewer.html manifest.json      # full control

Manifest (paths relative to the manifest file):
{
  "title": "My assembly",
  "subtitle": "optional header line",
  "scenes": [
    {"title": "Exploded", "caption": "what the viewer is looking at",
     "parts": [
       {"stl": "base.stl", "name": "base", "color": "#93a9cc"},
       {"stl": "lid.stl",  "name": "lid",  "color": "#c7d3e6",
        "alpha": 0.45, "translate": [0, 0, 38],
        "rotate": {"axis": [1, 0, 0], "deg": 90}}
     ],
     "anim": "sims/run.json"}          // optional: output of simulate_ball.py
  ]
}
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path

import numpy as np
import trimesh

PALETTE = ["#d9b382", "#5b8def", "#3fb98c", "#c96f5e", "#e0764f",
           "#9fb8a3", "#aebfd9", "#e78778", "#93a9cc", "#c7d3e6"]


def pack(mesh: trimesh.Trimesh) -> str:
    raw = trimesh.exchange.stl.export_stl(mesh)
    return base64.b64encode(gzip.compress(raw, 6)).decode()


def load_part(spec: dict, base: Path) -> dict:
    m = trimesh.load(base / spec["stl"])
    rot = spec.get("rotate")
    if rot:
        m.apply_transform(trimesh.transformations.rotation_matrix(
            np.radians(rot["deg"]), rot["axis"]))
    if spec.get("translate"):
        m.apply_translation(spec["translate"])
    out = {"name": spec.get("name", Path(spec["stl"]).stem),
           "color": spec.get("color", PALETTE[0]), "stl": pack(m)}
    if spec.get("alpha") is not None:
        out["alpha"] = spec["alpha"]
    return out


def build_scenes(args) -> tuple[str, str, list]:
    inputs = [Path(p) for p in args.inputs]
    if len(inputs) == 1 and inputs[0].suffix.lower() == ".json":
        man = json.loads(inputs[0].read_text())
        base = inputs[0].parent
        scenes = []
        for sc in man["scenes"]:
            parts = [load_part(p, base) for p in sc["parts"]]
            out = {"title": sc["title"], "caption": sc.get("caption", ""),
                   "parts": parts}
            if sc.get("anim"):
                r = json.loads((base / sc["anim"]).read_text())
                out["anim"] = {"fps": r["fps"], "traj": r["traj"],
                               "ball_r": r.get("ball_r", 3.0)}
                out["title"] = "▶ " + out["title"]
            scenes.append(out)
            print(sc["title"], sum(len(p["stl"]) for p in parts) // 1024, "KB")
        return man.get("title", "STL preview"), man.get("subtitle", ""), scenes
    scenes = []
    for i, f in enumerate(inputs):
        p = load_part({"stl": f.name, "color": PALETTE[i % len(PALETTE)]}, f.parent)
        scenes.append({"title": f.stem, "caption": f.name, "parts": [p]})
        print(f.stem, len(p["stl"]) // 1024, "KB")
    return args.title, "", scenes


HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#0f131b;--panel:#161c28;--ink:#e8ecf4;--dim:#9aa7bd;--line:#2a3448;
 --acc:#5b8def}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.5 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;height:100vh;
 display:flex;flex-direction:column}
header{padding:14px 22px;border-bottom:1px solid var(--line)}
header h1{font-size:19px;margin:0}
header .dim{font-size:13px;color:var(--dim)}
#wrap{flex:1;display:flex;min-height:0}
#side{width:270px;overflow-y:auto;border-right:1px solid var(--line);padding:10px}
.scene{padding:9px 12px;border-radius:9px;cursor:pointer;margin-bottom:4px;
 border:1px solid transparent;font-size:14px}
.scene:hover{background:var(--panel)}
.scene.sel{background:var(--panel);border-color:var(--acc)}
#stage{flex:1;position:relative;min-width:0}
canvas{width:100%;height:100%;display:block;touch-action:none}
#cap{position:absolute;left:14px;bottom:12px;right:14px;max-width:640px;
 background:rgba(22,28,40,.88);border:1px solid var(--line);border-radius:10px;
 padding:9px 13px;font-size:13.5px;color:#c9d3e6}
#legend{position:absolute;top:12px;right:14px;background:rgba(22,28,40,.88);
 border:1px solid var(--line);border-radius:10px;padding:8px 11px;font-size:12.5px;
 max-height:60%;overflow-y:auto}
#legend div{display:flex;align-items:center;gap:7px;cursor:pointer;padding:1.5px 0}
#legend .off{opacity:.35}
#legend i{width:11px;height:11px;border-radius:3px;display:inline-block}
#hint{position:absolute;top:12px;left:14px;font-size:12px;color:var(--dim)}
#load{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
 color:var(--dim);font-size:14px;pointer-events:none}
</style></head><body>
<header><h1>__TITLE__</h1>
<div class="dim">__SUBTITLE__ Self-contained viewer: models are embedded, nothing
is fetched. Drag to orbit · wheel to zoom · shift-drag to pan.</div></header>
<div id="wrap">
  <div id="side"></div>
  <div id="stage"><canvas id="cv"></canvas>
    <div id="hint"></div><div id="legend"></div>
    <div id="cap"></div><div id="load">decompressing…</div></div>
</div>
<script>
const SCENES = __SCENES__;
const cv = document.getElementById("cv");
const gl = cv.getContext("webgl", {antialias:true});
const VS=`attribute vec3 aP,aN;uniform mat4 uMVP;uniform mat3 uNrm;uniform vec3 uOff;
varying vec3 vN;void main(){vN=uNrm*aN;gl_Position=uMVP*vec4(aP+uOff,1.0);}`;
const FS=`precision mediump float;varying vec3 vN;uniform vec3 uCol;uniform float uA;
void main(){vec3 n=normalize(vN);
 float d1=max(dot(n,normalize(vec3(.4,.35,.85))),0.);
 float d2=max(dot(n,normalize(vec3(-.5,-.2,.35))),0.);
 vec3 c=uCol*(0.30+0.62*d1+0.22*d2);
 gl_FragColor=vec4(pow(c,vec3(0.9)),uA);}`;
function sh(t,s){const x=gl.createShader(t);gl.shaderSource(x,s);gl.compileShader(x);
 if(!gl.getShaderParameter(x,gl.COMPILE_STATUS))throw gl.getShaderInfoLog(x);return x;}
const prog=gl.createProgram();
gl.attachShader(prog,sh(gl.VERTEX_SHADER,VS));
gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,FS));
gl.linkProgram(prog);gl.useProgram(prog);
const locP=gl.getAttribLocation(prog,"aP"),locN=gl.getAttribLocation(prog,"aN");
const uMVP=gl.getUniformLocation(prog,"uMVP"),uNrm=gl.getUniformLocation(prog,"uNrm"),
      uCol=gl.getUniformLocation(prog,"uCol"),uA=gl.getUniformLocation(prog,"uA"),
      uOff=gl.getUniformLocation(prog,"uOff");
gl.enable(gl.DEPTH_TEST);

function mul(a,b){const o=new Float32Array(16);
 for(let i=0;i<4;i++)for(let j=0;j<4;j++){let s=0;
  for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s;}return o;}
function persp(f,asp,n,fr){const t=1/Math.tan(f/2);const o=new Float32Array(16);
 o[0]=t/asp;o[5]=t;o[10]=(fr+n)/(n-fr);o[11]=-1;o[14]=2*fr*n/(n-fr);return o;}
function ident(){const o=new Float32Array(16);o[0]=o[5]=o[10]=o[15]=1;return o;}
function trans(x,y,z){const o=ident();o[12]=x;o[13]=y;o[14]=z;return o;}
function rotX(a){const o=ident(),c=Math.cos(a),s=Math.sin(a);
 o[5]=c;o[6]=s;o[9]=-s;o[10]=c;return o;}
function rotZ(a){const o=ident(),c=Math.cos(a),s=Math.sin(a);
 o[0]=c;o[1]=s;o[4]=-s;o[5]=c;return o;}

async function unpackSTL(b64){
 const bin=atob(b64);const u=new Uint8Array(bin.length);
 for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);
 const ds=new Blob([u]).stream().pipeThrough(new DecompressionStream("gzip"));
 const buf=await new Response(ds).arrayBuffer();
 const dv=new DataView(buf);const n=dv.getUint32(80,true);
 const pos=new Float32Array(n*9),nrm=new Float32Array(n*9);
 let o=84;
 for(let t=0;t<n;t++){
  const nx=dv.getFloat32(o,true),ny=dv.getFloat32(o+4,true),nz=dv.getFloat32(o+8,true);
  for(let v=0;v<3;v++){
   const b=o+12+v*12,i=t*9+v*3;
   pos[i]=dv.getFloat32(b,true);pos[i+1]=dv.getFloat32(b+4,true);
   pos[i+2]=dv.getFloat32(b+8,true);
   nrm[i]=nx;nrm[i+1]=ny;nrm[i+2]=nz;}
  o+=50;}
 return {pos,nrm,count:n*3};
}
function hex(c){return [1,3,5].map(i=>parseInt(c.slice(i,i+2),16)/255);}

let cur=null, cam={yaw:-0.9,pitch:0.98,dist:1,cx:0,cy:0,cz:0,panX:0,panY:0};
let anim=null, ball=null;
function makeBall(r){
 const la=14, lo=20, P=[], N=[];
 for(let i=0;i<la;i++)for(let j=0;j<lo;j++){
  const v=[[i,j],[i+1,j],[i+1,j+1],[i,j],[i+1,j+1],[i,j+1]];
  for(const [a,b] of v){
   const th=Math.PI*a/la, ph=2*Math.PI*b/lo;
   const n=[Math.sin(th)*Math.cos(ph),Math.sin(th)*Math.sin(ph),Math.cos(th)];
   N.push(...n);P.push(n[0]*r,n[1]*r,n[2]*r);}}
 const bp=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bp);
 gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(P),gl.STATIC_DRAW);
 const bn=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bn);
 gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(N),gl.STATIC_DRAW);
 return {bp,bn,count:P.length/3,color:[0.94,0.96,1.0],alpha:1,r};
}
const cache={};
async function show(idx){
 document.querySelectorAll(".scene").forEach((e,i)=>e.classList.toggle("sel",i===idx));
 document.getElementById("load").style.display="flex";
 const sc=SCENES[idx];
 if(!cache[idx]){
  const parts=[];
  for(const p of sc.parts){
   const g=await unpackSTL(p.stl);
   const bp=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bp);
   gl.bufferData(gl.ARRAY_BUFFER,g.pos,gl.STATIC_DRAW);
   const bn=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bn);
   gl.bufferData(gl.ARRAY_BUFFER,g.nrm,gl.STATIC_DRAW);
   let mn=[1e9,1e9,1e9],mx=[-1e9,-1e9,-1e9];
   for(let i=0;i<g.pos.length;i+=3)for(let k=0;k<3;k++){
    mn[k]=Math.min(mn[k],g.pos[i+k]);mx[k]=Math.max(mx[k],g.pos[i+k]);}
   parts.push({bp,bn,count:g.count,color:hex(p.color),name:p.name,vis:true,mn,mx,
    alpha:(p.alpha===undefined?1:p.alpha)});
  }
  cache[idx]=parts;
 }
 cur=cache[idx];
 let mn=[1e9,1e9,1e9],mx=[-1e9,-1e9,-1e9];
 for(const p of cur)for(let k=0;k<3;k++){
  mn[k]=Math.min(mn[k],p.mn[k]);mx[k]=Math.max(mx[k],p.mx[k]);}
 cam.cx=(mn[0]+mx[0])/2;cam.cy=(mn[1]+mx[1])/2;cam.cz=(mn[2]+mx[2])/2;
 const R=Math.max(mx[0]-mn[0],mx[1]-mn[1],mx[2]-mn[2]);
 cam.dist=R*1.5;cam.panX=0;cam.panY=0;
 let capHtml="<b>"+sc.title+"</b>"+(sc.caption?" — "+sc.caption:"");
 if(sc.anim){
  const r=sc.anim.ball_r||3.0;
  if(!ball||ball.r!==r) ball=makeBall(r);
  anim={traj:sc.anim.traj,fps:sc.anim.fps,playing:true,t:0,speed:0.45,
        last:performance.now()};
  capHtml+=` &nbsp;<button id="apl">⏸</button> <button id="asp">speed 0.45×</button>`;
 } else anim=null;
 document.getElementById("cap").innerHTML=capHtml;
 if(sc.anim){
  document.getElementById("apl").addEventListener("click",ev=>{
   anim.playing=!anim.playing;anim.last=performance.now();
   ev.target.textContent=anim.playing?"⏸":"▶";});
  document.getElementById("asp").addEventListener("click",ev=>{
   anim.speed=anim.speed>=1?0.2:(anim.speed+0.25);
   ev.target.textContent="speed "+anim.speed.toFixed(2)+"×";});
  requestAnimationFrame(tick);
 }
 const lg=document.getElementById("legend");lg.innerHTML="";
 if(cur.length>1) cur.forEach(p=>{
  const d=document.createElement("div");
  d.innerHTML=`<i style="background:rgb(${p.color.map(v=>v*255|0).join(",")})"></i>${p.name}`;
  d.addEventListener("click",()=>{p.vis=!p.vis;d.classList.toggle("off",!p.vis);draw();});
  lg.appendChild(d);});
 document.getElementById("load").style.display="none";
 draw();
}
function draw(){
 const w=cv.clientWidth,h=cv.clientHeight;
 if(cv.width!==w*devicePixelRatio){cv.width=w*devicePixelRatio;cv.height=h*devicePixelRatio;}
 gl.viewport(0,0,cv.width,cv.height);
 gl.clearColor(0.059,0.075,0.106,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
 if(!cur)return;
 const P=persp(0.9,w/h,cam.dist*0.01,cam.dist*10);
 let V=trans(cam.panX,cam.panY,-cam.dist);
 V=mul(V,rotX(cam.pitch-Math.PI/2));
 V=mul(V,rotZ(cam.yaw));
 V=mul(V,trans(-cam.cx,-cam.cy,-cam.cz));
 const MVP=mul(P,V);
 const NM=new Float32Array([V[0],V[1],V[2],V[4],V[5],V[6],V[8],V[9],V[10]]);
 gl.uniformMatrix4fv(uMVP,false,MVP);gl.uniformMatrix3fv(uNrm,false,NM);
 function drawPart(p,off){
  gl.uniform3fv(uCol,p.color);gl.uniform1f(uA,p.alpha);
  gl.uniform3fv(uOff,off||[0,0,0]);
  gl.bindBuffer(gl.ARRAY_BUFFER,p.bp);
  gl.enableVertexAttribArray(locP);gl.vertexAttribPointer(locP,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,p.bn);
  gl.enableVertexAttribArray(locN);gl.vertexAttribPointer(locN,3,gl.FLOAT,false,0,0);
  gl.drawArrays(gl.TRIANGLES,0,p.count);
 }
 for(const p of cur){ if(p.vis&&p.alpha>=1) drawPart(p); }
 if(anim&&ball){
  const i=Math.min(anim.traj.length-1,Math.floor(anim.t*anim.fps));
  drawPart(ball,anim.traj[i]);
 }
 gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
 gl.depthMask(false);
 for(const p of cur){ if(p.vis&&p.alpha<1) drawPart(p); }
 gl.depthMask(true);gl.disable(gl.BLEND);
}
function tick(now){
 if(!anim)return;
 if(anim.playing){
  anim.t+=(now-anim.last)/1000*anim.speed;
  const dur=anim.traj.length/anim.fps;
  if(anim.t>dur+0.6)anim.t=0;
  draw();
 }
 anim.last=now;
 requestAnimationFrame(tick);
}
let drag=null;
cv.addEventListener("pointerdown",e=>{drag={x:e.clientX,y:e.clientY,pan:e.shiftKey};
 cv.setPointerCapture(e.pointerId);});
cv.addEventListener("pointermove",e=>{
 if(!drag)return;
 const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;
 if(drag.pan){cam.panX+=dx*cam.dist*0.0011;cam.panY-=dy*cam.dist*0.0011;}
 else{cam.yaw+=dx*0.008;cam.pitch=Math.min(3.1,Math.max(0.05,cam.pitch+dy*0.008));}
 draw();});
cv.addEventListener("pointerup",()=>drag=null);
cv.addEventListener("wheel",e=>{e.preventDefault();
 cam.dist*=Math.pow(1.0015,e.deltaY);draw();},{passive:false});
window.addEventListener("resize",draw);

const side=document.getElementById("side");
SCENES.forEach((s,i)=>{
 const d=document.createElement("div");d.className="scene";d.textContent=s.title;
 d.addEventListener("click",()=>show(i));side.appendChild(d);});
show(0);
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+", help="STL files, or one manifest.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="STL preview")
    a = ap.parse_args()
    title, subtitle, scenes = build_scenes(a)
    html = (HTML.replace("__TITLE__", title).replace("__SUBTITLE__", subtitle)
            .replace("__SCENES__", json.dumps(scenes)))
    out = Path(a.out)
    out.write_text(html)
    print(out, out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
