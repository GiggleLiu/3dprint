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
4. **CONFIRM (required)** — show the user the slice summary **and the resolved
   print parameters** (filament source, plate/bed, nozzle) and WAIT for explicit
   approval. Slicing is automatic; **printing is not**.
5. **Send** — only after approval: `scripts/send.py <stl>.gcode.3mf`. Add
   `--dry-run` to upload without starting (safe test). Before it starts a real
   print, `send.py` runs the **parameter gate** (below) and refuses to start if
   the configured filament source is empty/mismatched.
6. **Monitor** — `scripts/monitor.py` streams progress until FINISH / FAILED.

## The confirmation gate (do not skip)

Starting a print heats the printer and extrudes plastic, often unattended. After
slicing, present print time + filament weight + temps and stop for a yes. If the
user has not explicitly approved THIS slice, do not run `send.py` without
`--dry-run`. Violating the letter of this gate violates its spirit.

## The parameter-confirmation gate (key params must match reality)

A clean slice and a working upload do **not** mean the print will succeed — the
*print-determining parameters* must match the printer's actual state. Split them
by how often they change, so the user isn't re-asked the same thing every print:

**Confirmed once, at setup** (stored in `bambu.toml`; the gate *trusts* these and
only displays them — it does not re-prompt):

- **Build plate** — `[slice].bed_type` (e.g. `"Textured PEI Plate"`). Sets the bed
  temperature. The plate rarely changes; confirm it during `/onboard` and store it.
  The gate only warns if it was **never set** (setup is incomplete).
- **Has an AMS?** — `[print].use_ams`. A hardware fact; confirm at setup.

**Re-checked every print** (volatile — the gate validates these live and can
**block**, because they change between jobs):

- **Chosen filament slot is actually loaded** — `[print].ams_tray`. `send.py` reads
  the AMS/external state and **refuses to start** if that source is empty (e.g.
  `use_ams=false` while filament is only in the AMS → the printer extrudes nothing).
- **Filament type matches the slice** — PLA slice vs a PETG/support slot → ⚠.

> **AMS auto-load.** A print started with `use_ams` + `ams_mapping` does **not**
> reliably make the printer load the mapped tray — it can run the whole job with
> `tray_now=255` (nothing at the nozzle) and extrude nothing, with no error. So
> `send.py` **pre-loads** the AMS slot itself (`ams_change_filament`) and waits
> until `tray_now` matches before starting. If the slot won't feed (spool not
> threaded into the AMS), it refuses to start rather than print dry.

`send.py` prints a concise `── print parameters ──` block (source / filament /
bed / nozzle); stable params appear as plain info, only genuine per-print
problems get ⚠/✗. Show it to the user as part of CONFIRM. Override a ✗ block only
deliberately with `--force`.

## Scripts

| Script | Does |
|--------|------|
| `setup_config.py` | scaffold gitignored `bambu.toml` (`--machine "<name>"` auto-fills compatible presets) |
| `list_presets.py` | list machines, or `--machine "<name>"` → compatible process/filament presets (`--suggest` for paste-ready `[slice]`) |
| `preflight.py` | check config, slicer, preset **compatibility**, library, live API → JSON |
| `view.py <stl>` | self-contained 3D HTML viewer (`--open` to launch) |
| `slice.py <stl>` | STL → `.gcode.3mf` + summary (time, filament, temps) |
| `send.py <3mf>` | upload over LAN + start print (`--dry-run` = upload only) |
| `monitor.py` | stream live print status until done |
| `use_printer.py` | switch between `bambu.<name>.toml` profiles (`--list` / `<name>` / `--auto`) |

Every printer-facing script takes `--printer <name>` to use a `bambu.<name>.toml`
profile instead of the active `bambu.toml` (see **Multiple printers**).

## Multiple printers

Keep one `bambu.<name>.toml` per printer (e.g. `bambu.p1s.toml`, `bambu.x2d.toml`)
alongside the active `bambu.toml`. All are gitignored via `bambu.*.toml`.

- `use_printer.py --list` — show every profile, its model, IP, and whether it's
  reachable on the **local network** vs only over a VPN tunnel.
- `use_printer.py <name>` — make that profile active (copies it to `bambu.toml`).
- `use_printer.py --auto` — pick the profile reachable on a physical interface
  (not a VPN tunnel). Useful when the same printer set spans home/office networks.
- Or skip switching entirely and pass `--printer <name>` to any script.

To add a printer: `setup_config.py --machine "<machine name>"` (auto-fills
compatible presets), then save it as `bambu.<name>.toml` and fill in ip/serial/code.

## Common mistakes

- **`send.py` says "could not connect" though `:8883` is open** → Developer/LAN
  Mode is OFF (print start is gated), or the access code rotated. Slicing and
  monitoring don't need Developer Mode; starting a print does. See
  `reference/developer-mode.md`. (Preflight's API probe catches this: it reports
  `api no` even when the TCP port is up.)
- **`ready_to_print=False` but the port is open** → the printer only answers over
  a **VPN tunnel**, or its API didn't respond. Preflight flags `[vpn via utunN]`
  and only sets `ready_to_print` when the authenticated channel actually answers.
- **Running a script with system `python3` that lacks bambulabs-api** → use the
  venv interpreter.
- **`process profile ✗ NOT compatible` in preflight** → the preset *exists* but
  doesn't list this machine in `compatible_printers`; the slicer will reject it
  (e.g. a P1S needs the `@BBL X1C` process family, not `@BBL P1P`). Run
  `list_presets.py --machine "<machine>"` to see compatible presets. A *filament*
  shown as "not listed" is only a warning (usually a nozzle-size mismatch) — it
  still slices.
- **`machine profile ✗` in preflight** → the slicer is too old for the model
  (e.g. a brand-new printer needs an updated Bambu Studio) or the preset name in
  `bambu.toml` is wrong. Names must match the slicer exactly.
- **Filament grams look wrong** → Bambu's CLI writes weight 0.00; `slice.py`
  re-computes it from length × diameter × density (marked `filament_g_estimated`).
- **`use_ams` mismatch** → set `[print].use_ams` to match (AMS vs external spool).

## Safety / distribution

`bambu.toml` (and any `bambu.<name>.toml` profile) holds the LAN access code and
is gitignored via `bambu.toml` + `bambu.*.toml` — never commit them. Only
`bambu.toml.example` (placeholders, kept via `!bambu.toml.example`) is committed.
