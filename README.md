# 🖨️ Design and print 3D models with Claude Code

Three [Claude Code](https://claude.com/claude-code) skills take you from an idea to a
finished print on a Bambu Lab printer over your local network — with a **confirmation
gate so nothing prints until you approve.** Run the skill for what you want to do:

| To… | Run | What happens |
|-----|-----|--------------|
| **Set up a printer** (first time) | **`/onboard`** | installs deps, connects your printer, enables LAN printing |
| **Design a model** from a description | **`/design-stl`** | builds a printable STL from your description, with previews + printability checks |
| **Slice and print** an STL | **`/print-to-bambu`** | previews, slices, shows the summary, prints after your OK, and monitors |

Claude runs the tooling for you — you never run scripts by hand.

## What you can do

- 🎨 **Turn a description into a printable STL.** `/design-stl` builds the model,
  shows you a preview, and checks it's actually printable — watertight, fits the
  bed, walls thick enough, no nasty overhangs — before you commit.
- 🖨️ **Print over your network.** `/print-to-bambu` slices an STL and sends it to a
  Bambu Lab printer over LAN, with live progress until it finishes.
- ✋ **Stay in control.** You see the print time, filament weight, and temperatures
  and approve before anything heats up. It also refuses to start a print that would
  extrude nothing (empty spool, wrong filament slot).
- 🖧 **Juggle several printers.** Keep a profile per printer and pick one by name —
  or let `/print-to-bambu` choose the one that's actually on your network.

## First time? Run `/onboard`

It walks you through setup and stops to let you act on the printer when needed:

1. **Install a slicer** — [Bambu Studio](https://bambulab.com/en/download) (or
   OrcaSlicer). A brand-new printer model needs an up-to-date build.
2. **Python environment** — checked, and set up if anything's missing.
3. **Connect your printer** — a private config is created; you copy the IP / serial /
   access code off the printer screen, and matching slicer presets are chosen.
4. **Enable Developer / LAN Mode** on the printer — needed to *start* prints
   (previewing and slicing work without it).

It finishes by confirming everything's ready (`ready_to_print=True`) and can do a
no-print dry run to prove the connection.

> Your printer config holds its access code and is kept private — never committed.

## Printing — `/print-to-bambu`

Point it at your STL. It previews, slices, shows you the summary (time, filament,
temperatures), **waits for your approval**, then prints and monitors to the end. Ask
for a dry run to upload without printing.

**Why it won't surprise you:** printing is never automatic. After slicing it shows
you the numbers and stops for a yes. Before it starts, it checks the printer's
*actual* filament — the AMS slots and external spool — and refuses to print if the
source you chose is empty or the wrong type. Printing from an AMS, it pre-loads your
slot first so the printer never runs dry.

It also manages multiple printers: list them, switch by name, or auto-pick the one
reachable on your LAN rather than only over a VPN.

## Designing — `/design-stl`

Give it a description ("a 60 mm hex planter with drainage holes"). It writes a small
builder, renders previews and an STL, runs printability checks, and iterates until
the model is sound — then it's ready to hand to `/print-to-bambu`. The default
toolkit is Python + trimesh; OpenSCAD is an optional alternative for CSG work.

## Under the hood

These skills live in `.claude/skills/` — `onboard`, `design-stl`, and
`print-to-bambu` — each a `SKILL.md` plus small Python scripts. You don't call the
scripts directly, but if you want to inspect or run them yourself,
[`AGENTS.md`](AGENTS.md) documents the layout, the scripts, and the conventions
(it's also what Codex and other agents read). The same skills are exposed to Codex
via `.codex/skills/`.

## License

MIT — use, modify, and share freely.

---

Happy printing! 🎉
