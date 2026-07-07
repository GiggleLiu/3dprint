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
4. **Live status check (required)** — before any real print, run
   `scripts/send.py <stl>.gcode.3mf` **without** `--status-confirmed`. It prints
   the live printer status plus resolved print parameters, then refuses before
   upload, AMS preload, heating, or start.
5. **CONFIRM (required)** — show the user the slice summary **and the live
   printer status / resolved print parameters** (printer state, temps, current
   file, AMS/external source, plate/bed, nozzle). WAIT for explicit approval of
   this exact slice and current printer state. Slicing/status checks are
   automatic; **printing is not**.
6. **Send** — only after approval: `scripts/send.py <stl>.gcode.3mf
   --status-confirmed`. Add `--dry-run` to upload without starting (safe test).
   Before it starts a real print, `send.py` re-runs the live status and
   **parameter gate** (below), refuses if the printer is busy or the configured
   filament source is empty/mismatched, and only then may preload AMS/start.
7. **Monitor** — `scripts/monitor.py` streams progress until FINISH / FAILED.

## The confirmation gate (do not skip)

Starting a print heats the printer and extrudes plastic, often unattended. After
slicing, present print time + filament weight + temps, then run the live status
check and present the printer status block. Stop for a yes after both the slice
and live status are visible. If the user has not explicitly approved THIS slice
and THIS live printer status, do not run `send.py --status-confirmed`. Violating
the letter of this gate violates its spirit.

`send.py` enforces this mechanically: without `--status-confirmed`, a real print
command prints the status/parameter blocks and exits before upload, AMS preload,
heating, or print start.

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

`send.py` prints a concise `── printer status ──` block (state / progress /
temps / current file / AMS slots / external spool) and `── print parameters ──`
block (source / filament / bed / nozzle). Stable params appear as plain info,
only genuine per-print problems get ⚠/✗. Show both blocks to the user as part of
CONFIRM. Printer-status ✗ blocks are not force-overridable; override a parameter
✗ block only deliberately with `--force`.

## Scripts

| Script | Does |
|--------|------|
| `setup_config.py` | scaffold gitignored `bambu.toml` (`--machine "<name>"` auto-fills compatible presets) |
| `list_presets.py` | list machines, or `--machine "<name>"` → compatible process/filament presets (`--suggest` for paste-ready `[slice]`) |
| `preflight.py` | check config, slicer, preset **compatibility**, library, live API → JSON |
| `view.py <stl>` | self-contained 3D HTML viewer (`--open` to launch) |
| `slice.py <stl>` | STL → `.gcode.3mf` + summary (time, filament, temps) |
| `send.py <3mf>` | live status/parameter check; refuses to start until rerun with `--status-confirmed` |
| `send.py <3mf> --status-confirmed` | upload over LAN + start print (`--dry-run` = upload only) |
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
- **X2D/H2 legacy nozzle target says 0°C while a print is RUNNING** → do not
  assume the print is cold. Dual-nozzle firmware may report the inactive/legacy
  nozzle in `nozzle_target_temper` while the active nozzle lives under
  `device.extruder.info[*].temp` as a packed current/target value. `monitor.py`
  and `send.py` decode and display `E0` / `E1`; use those fields before calling
  a run dry. If the active extruder is genuinely cold, suspect a bad
  `project_file` payload and capture `device.extruder.info`, `tray_now`,
  `mc_percent`, and the exact start payload. Do not start a second job until the
  printer is idle or the user explicitly stops the current run at the printer.
- **X2D/H2 print heats but AMS does not feed the requested slot** → check the
  project-file filament IDs. `Metadata/plate_1.json` can use zero-based display
  IDs (`filament_ids: [0]`) while `Metadata/slice_info.config` and
  `Metadata/filament_sequence.json` use the firmware-facing ID (`1`). The MQTT
  `ams_mapping` / `ams_mapping2` must be keyed to the slice/sequence ID, not the
  plate display ID. For a one-filament X2D file whose sequence is `[1]` and the
  desired AMS tray is `3`, send `ams_mapping: [-1, 3]` and
  `ams_mapping2: [{ams_id:255, slot_id:255}, {ams_id:0, slot_id:3}]`.
- **X2D/H2 "started" but the printer never prints** → a successful MQTT publish
  proves nothing: this firmware takes ~30–40 s to act on `project_file`, and it
  *silently drops* a start sent while the filament-change flow is still busy
  (`device.extruder.state` bit 19 set right after a load) — no error reply, no
  state change, nozzle just cools back down. `send.py` now waits out the busy
  flag after preloading and only reports "started" after seeing the
  RUNNING/PREPARE transition. If it reports the printer never transitioned,
  simply rerun it — do not trust a bare publish.
- **Print sticks then peels off / "filament not attached"** → the *model*, not
  the printer: a mesh that meets the plate in points or thin edges (e.g. full
  spheres) slices and uploads fine but cannot adhere; a brim only grips a tiny
  neck. `slice.py` measures this (`base_contact_mm2` from the STL geometry +
  `first_layer_mm2` from the G-code) and warns. Fix the geometry — cut the
  underside flat — rather than forcing it with adhesion tricks.
- **X2D/H2 silently ignores `ams_change_filament` with only `target`** → no
  error, no AMS motion, `tray_tar` stays 255, and the preload gate reports "slot
  did not load" even though the spool is fine. Dual-nozzle firmware requires the
  Bambu-Studio-style payload with explicit `ams_id` and `slot_id` (keep legacy
  `target` for older printers). Success shows within seconds as `tray_tar`, then
  `tray_now` and `device.extruder.info[*].snow == (ams_id<<8)|slot_id`; `snow`
  values 0xFFFF/0xFEFF mean "nothing loaded" (254/255 are the per-nozzle
  external-spool virtual trays), not real slots. `load_ams_tray` in
  `scripts/_printer.py` sends the full payload and checks both fields — don't
  hand-roll the command.

## Safety / distribution

`bambu.toml` (and any `bambu.<name>.toml` profile) holds the LAN access code and
is gitignored via `bambu.toml` + `bambu.*.toml` — never commit them. Only
`bambu.toml.example` (placeholders, kept via `!bambu.toml.example`) is committed.
