# Preview-STL demo and verification design

## Problem

The first end-to-end preview demo exposed two product frictions. Rich multi-part
presentations required a hand-written manifest, and the headless verifier could
report success even when its screenshots contained a blank WebGL canvas.
Rendering itself was correct, but Chromium had already discarded the drawing
buffer before the screenshot.

The unavailable in-app browser was session infrastructure rather than repository
behavior, so it is not part of this code change.

## Design

Keep existing loose-STL and manifest behavior unchanged. Add an opt-in `--demo`
mode for part STLs exported in a common coordinate frame. It builds a
color-coded assembly scene and, for two or more parts, a second scene whose parts
are translated outward from the assembly center. The manifest remains the
authoring interface for named views, transparency, animation, and exact
transforms.

Create WebGL contexts with `preserveDrawingBuffer` so screenshots see the last
completed frame. Extend `verify_page.cjs` to read the canvas framebuffer after
each scene, derive the clear color from WebGL state, and require a small minimum
of non-background pixels. Save each canvas directly from its preserved buffer,
rather than relying on Chromium's nondeterministic full-page GPU composition.
Continue to fail on console or page errors.

## Error handling and tests

`--demo` rejects JSON manifests because mixing generated and authored scene
semantics would be ambiguous. Render-probe failures are collected as verifier
errors so the browser closes cleanly and the command exits nonzero.

Regression coverage checks that legacy loose-file mode remains unchanged, demo
mode creates assembly and exploded scenes, and exploded parts move outward. A
rendered triangle fixture is the verifier's positive control; a deliberately
blank WebGL fixture is the negative control and must be rejected. The generated
H₂ demo is the positive end-to-end control and every screenshot is inspected
visually.
