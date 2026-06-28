# OpenSCAD cheat-sheet (for generating printable models)

OpenSCAD builds solids with Constructive Solid Geometry (CSG). You write a script;
`build.py` compiles it to STL and renders PNGs. Everything is in **millimeters**.

## Primitives
```scad
sphere(r = 10);                 // or sphere(d = 20);
cube([20, 10, 5], center = true);
cylinder(h = 20, r = 3, center = true);          // add center to sit on origin
cylinder(h = 20, r1 = 5, r2 = 0);                // cone
$fn = 64;                        // facets per circle: 32 draft, 64 smooth
```

## Transforms (wrap the shape that follows)
```scad
translate([x, y, z]) sphere(10);
rotate([rx, ry, rz]) cylinder(h = 20, r = 2);
scale([2, 1, 1]) sphere(5);
```

## Booleans (CSG)
```scad
union()        { a(); b(); }    // glue together (default for siblings)
difference()   { a(); b(); }    // a minus b (drill holes / carve)
intersection() { a(); b(); }    // common volume
```

## Reuse with modules + parameters
```scad
module atom(pos, r) { translate(pos) sphere(r); }
module bond(p1, p2, r) {
    // cylinder from p1 to p2
    d = p2 - p1; len = norm(d);
    translate(p1) rotate([0, 0, atan2(d[1], d[0])])
        rotate([0, 90, 0]) cylinder(h = len, r = r);
}
atom([-12, 0, 0], 8);
atom([ 12, 0, 0], 8);
bond([-12, 0, 0], [12, 0, 0], 2.5);
```

## Printability tips (the validator checks these)
- **Watertight:** let solids **overlap** where they join (e.g. push a bond slightly
  *into* each atom). Touching-but-not-overlapping faces produce non-manifold gaps.
- **Min wall / feature ≥ ~0.8 mm** (2× a 0.4 nozzle line). Avoid knife-thin spikes.
- **Overhangs:** faces shallower than ~45° from horizontal need supports. Spheres
  and big bridges add overhang area; a small flat base improves bed adhesion.
- **Fit the bed:** keep the bounding box within the printer bed (X2D 256×256×260).
- **Sit on z = 0:** center horizontally, rest the lowest point near the plate.

## Iterating
Edit the `.scad`, rerun `build.py model.scad`, look at the PNG previews and the
validation report, repeat until watertight + fits + looks right.
