---
name: print-to-bambu
description: Use when the user wants to slice an STL and print it on a Bambu Lab printer over the local network (LAN), preview an STL in 3D in the browser, or check/monitor a Bambu print's status. Covers slicing with Bambu Studio or OrcaSlicer, uploading over LAN, starting a print behind a confirmation gate, and streaming progress.
---

# Print to Bambu (LAN)

Slice an STL with Bambu Studio / OrcaSlicer and print it on a Bambu Lab printer
over the local network — with a **human confirmation gate before any plastic is
extruded**. Machine-agnostic: the printer model comes from `bambu.toml`.

**First time on this machine, or preflight not all green?** Use the **onboard**
skill (`/onboard`) first — it installs the slicer, sets up `bambu.toml`, and
enables Developer Mode.

Run scripts with the interpreter that has `bambulabs-api` (e.g. `.venv/bin/python`).
Scripts print a human summary on stderr and JSON on stdout.

## Workflow — do these in order

1. **Preflight** — `scripts/preflight.py`. Need `ready_to_slice` to slice,
   `ready_to_print` to print. Fix any ✗ (or run `/onboard`).
2. **Preview (optional)** — `scripts/view.py <stl> --open` opens a 3D viewer
   (orbit/zoom) so the user can check the model before printing.
3. **Slice** — `scripts/slice.py <stl>` → writes `<stl>.gcode.3mf` and a summary
   (print time, filament grams, nozzle/bed temps).
4. **CONFIRM (required)** — show the user the slice summary and WAIT for explicit
   approval. Slicing is automatic; **printing is not**.
5. **Send** — only after approval: `scripts/send.py <stl>.gcode.3mf`. Add
   `--dry-run` to upload without starting (safe test).
6. **Monitor** — `scripts/monitor.py` streams progress until FINISH / FAILED.

## The confirmation gate (do not skip)

Starting a print heats the printer and extrudes plastic, often unattended. After
slicing, present print time + filament weight + temps and stop for a yes. If the
user has not explicitly approved THIS slice, do not run `send.py` without
`--dry-run`. Violating the letter of this gate violates its spirit.

## Scripts

| Script | Does |
|--------|------|
| `setup_config.py` | scaffold gitignored `bambu.toml`, add it to `.gitignore` |
| `preflight.py` | check config, slicer, profiles, library, reachability → JSON |
| `view.py <stl>` | self-contained 3D HTML viewer (`--open` to launch) |
| `slice.py <stl>` | STL → `.gcode.3mf` + summary (time, filament, temps) |
| `send.py <3mf>` | upload over LAN + start print (`--dry-run` = upload only) |
| `monitor.py` | stream live print status until done |

## Common mistakes

- **`send.py` says "could not connect" though `:8883` is open** → Developer/LAN
  Mode is OFF (print start is gated), or the access code rotated. Slicing and
  monitoring don't need Developer Mode; starting a print does. See
  `reference/developer-mode.md`.
- **Running a script with system `python3` that lacks bambulabs-api** → use the
  venv interpreter.
- **`machine/process/filament profile ✗` in preflight** → the slicer is too old
  for the model (e.g. a brand-new printer needs an updated Bambu Studio) or the
  preset name in `bambu.toml` is wrong. Names must match the slicer exactly.
- **Filament grams look wrong** → Bambu's CLI writes weight 0.00; `slice.py`
  re-computes it from length × diameter × density (marked `filament_g_estimated`).
- **`use_ams` mismatch** → set `[print].use_ams` to match (AMS vs external spool).

## Safety / distribution

`bambu.toml` holds the LAN access code and is gitignored — never commit it. Only
`bambu.toml.example` (placeholders) is committed.
