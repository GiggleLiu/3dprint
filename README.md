# 🖨️ Design and print 3D models by asking Claude

Tell [Claude Code](https://claude.com/claude-code) what you want to make and which
Bambu Lab printer to send it to. It turns your description into a printable model,
slices it, and prints it over your local network — and **never starts a print until
you've seen the preview and said go.**

> - *"Design a desk standee of our logo and print it on the P1S."*
> - *"Slice this STL and show me the time and filament estimate."*
> - *"Print model.stl — dry run first."*

## What you can do

- 🎨 **Turn a description into a printable STL.** Describe the object; Claude builds
  it, shows you a preview, and checks it's actually printable — watertight, fits the
  bed, walls thick enough, no nasty overhangs — before you commit.
- 🖨️ **Print over your network.** Slice an STL and send it to a Bambu Lab printer
  over LAN, with live progress until it finishes.
- ✋ **Stay in control.** You see the print time, filament weight, and temperatures
  and approve before anything heats up. Claude also refuses to start a print that
  would extrude nothing (empty spool, wrong filament slot).
- 🖧 **Juggle several printers.** Keep a profile per printer and pick one by name —
  or let Claude choose the one that's actually on your network.

## First time? Set up once

Just say **"set up my printer"** (or run **`/onboard`**) and Claude walks you through it:

1. **Install a slicer** — [Bambu Studio](https://bambulab.com/en/download) (or
   OrcaSlicer). A brand-new printer model needs an up-to-date build.
2. **Python environment** — Claude creates a local virtualenv and installs what's needed.
3. **Connect your printer** — Claude sets up a private config and helps you copy the
   IP / serial / access code off the printer screen, then picks slicer presets that
   match your model.
4. **Enable Developer / LAN Mode** on the printer — needed to *start* prints
   (previewing and slicing work without it).

To confirm it all worked, ask Claude to run **preflight** — you're aiming for
`ready_to_print=True`:

```bash
.venv/bin/python .claude/skills/print-to-bambu/scripts/preflight.py
```

> Your printer config holds its access code and is kept private — never committed.

## Print an STL

Just ask — *"print model.stl"* — and Claude previews it, slices it, shows you the
summary, waits for your OK, then prints and watches it. Under the hood that's:

```bash
P=.claude/skills/print-to-bambu/scripts
.venv/bin/python $P/view.py    model.stl --open   # 3D preview in your browser
.venv/bin/python $P/slice.py   model.stl          # → print time, filament, temperatures
# ── you review the summary and approve ──
.venv/bin/python $P/send.py    model.gcode.3mf    # add --dry-run to upload without printing
.venv/bin/python $P/monitor.py                    # live progress until it finishes
```

**Why it won't surprise you:** printing is never automatic. After slicing, Claude
shows you the numbers and stops for a yes. And before it starts, it checks the
printer's *actual* filament — the AMS slots and external spool — and refuses to
print if the source you chose is empty or the wrong type. When you print from an
AMS it pre-loads your slot first, so the printer never runs dry.

## Design a model from a description

*"Design a 60 mm hex planter with drainage holes."* Claude writes a small builder,
renders previews and an STL, and runs printability checks — iterating until the
model is sound and ready to print. The default toolkit is Python + trimesh (pure
pip); OpenSCAD is an optional alternative for CSG work.

```bash
.venv/bin/python .claude/skills/design-stl/scripts/build.py    model.py   # → STL + previews + report
.venv/bin/python .claude/skills/design-stl/scripts/validate.py any.stl    # printability check on any STL
```

## Working with more than one printer

Keep a profile per printer and switch by name — or let Claude pick the one that's
reachable on your network rather than only over a VPN:

```bash
P=.claude/skills/print-to-bambu/scripts
.venv/bin/python $P/use_printer.py --list   # every printer + whether it's on your LAN or only via VPN
.venv/bin/python $P/use_printer.py p1s      # make that one active
.venv/bin/python $P/use_printer.py --auto   # auto-pick the one on your physical network
```

## License

MIT — use, modify, and share freely.

---

Happy printing! 🎉
