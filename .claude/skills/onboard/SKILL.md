---
name: onboard
description: Use when setting up the Bambu LAN printing workflow for the first time on a machine, or when print-to-bambu preflight is not all green — installs/locates the slicer, sets up the Python venv, scaffolds bambu.toml, helps find the printer IP/serial/access code, and walks through enabling Developer/LAN Mode so prints can start.
---

# Onboard: set up Bambu LAN printing

Goal: take the user from nothing to a green `preflight.py` (`ready_to_print=True`).
Do the steps in order. Some require the user to act on the **physical printer** —
stop and ask them to do it; never invent an IP, serial, or access code.

Paths below assume the repo root is the current directory.

## 1. Slicer
Detect Bambu Studio / OrcaSlicer:
- macOS: `ls -d /Applications/BambuStudio.app /Applications/OrcaSlicer.app 2>/dev/null`
- PATH: `which bambu-studio orca-slicer`

If none, have the user install **Bambu Studio** (<https://bambulab.com/en/download>).
Newest printers (X2D, H2 series) need an up-to-date build, or the model's slice
profile will be missing.

## 2. Python environment (check, then set up if missing)
One command — run with the **system** `python3` — checks Python, the virtualenv, and
the required packages, and sets up whatever is missing (it bootstraps `.venv`, so it
must run *before* the venv exists):
```
python3 .claude/skills/onboard/scripts/setup_env.py                # printing deps
python3 .claude/skills/onboard/scripts/setup_env.py --with-design  # + design-stl deps
```
It needs **Python 3.11+** (it creates the venv and pip-installs, but can't install
Python itself — if yours is older it says so and stops). Pass `--check` to verify
without changing anything (exit 1 if something's missing). After it reports
`environment ready`, run every later script with `.venv/bin/python`.

## 3. Config file
```
# Pass --machine to auto-fill COMPATIBLE process/filament presets (no guessing):
.venv/bin/python .claude/skills/print-to-bambu/scripts/setup_config.py \
    --machine "Bambu Lab P1S 0.4 nozzle"
```
This writes a gitignored `bambu.toml`. Use `list_presets.py` to find the exact
machine name. Then help the user fill it in:
- `[printer] ip` and `serial` — from the printer screen (Settings → WLAN / Device).
- `[slice] machine/process/filament` — `--machine` auto-fills compatible presets;
  preflight verifies both existence **and** machine-compatibility.
- access code — prefer `export BAMBU_ACCESS_CODE=...` over writing it to the file.

## 4. Developer / LAN Mode (required to START prints)
Slicing and monitoring work without it; **starting a print does not**. Walk the
user through `.claude/skills/print-to-bambu/reference/developer-mode.md` and have
them read the **access code** off the printer screen.

## 5. Confirm hardware — the set-once print params
These rarely change, so confirm them **now** and store them in `bambu.toml`; the
per-print parameter gate then trusts them instead of re-asking every print.
- **Build plate** → `[slice].bed_type`. Ask which plate is physically on the bed
  (P1S/X1 default is `"Textured PEI Plate"`). Unset defaults to *Cool Plate* (~35 °C)
  — too cold for PLA and a classic first-layer-fail.
- **AMS?** → `[print].use_ams` and `[print].ams_tray`. If an AMS is attached and
  loaded, set `use_ams = true`. You can confirm what the printer actually sees
  (once creds + LAN Mode are set) — it reports the AMS and which slots hold
  filament. **`use_ams = false` while filament is only in the AMS prints nothing.**

## 6. Verify
```
.venv/bin/python .claude/skills/print-to-bambu/scripts/preflight.py
```
Read each line. Resolve every ✗ (see mapping below). Aim for `ready_to_print=True`.
Then confirm the LAN path without printing:
```
.venv/bin/python .claude/skills/print-to-bambu/scripts/send.py <file>.gcode.3mf --dry-run
```
A successful dry-run (uploads, does not print) means everything is wired up.

## Preflight ✗ → fix
| Symptom | Fix |
|---------|-----|
| config ✗ | run setup_config.py; set ip/serial |
| slicer ✗ | install Bambu Studio / OrcaSlicer, or set `[slicer].binary` |
| machine profile ✗ | slicer too old for the model, or wrong preset name |
| process profile ✗ NOT compatible | wrong process family — run `list_presets.py --machine "<machine>"` (e.g. P1S uses `@BBL X1C`, not `@BBL P1P`) |
| bambulabs-api ✗ | re-run step 2: `setup_env.py` (installs it into `.venv`) |
| printer `api no` / `tcp down` | printer off, wrong IP/subnet, or only reachable over a VPN (`[vpn via utunN]`) |
| `tcp up` but `api no` | Developer/LAN Mode is OFF, or the access code rotated |

When `ready_to_print=True`, hand off to the **print-to-bambu** skill.

## (Optional) design-stl deps

If the user also wants to *design* models from descriptions (the **design-stl**
skill, default engine trimesh):
- **Python deps** (required): re-run step 2 with `--with-design`
  (`python3 .claude/skills/onboard/scripts/setup_env.py --with-design`) — it adds
  trimesh, manifold3d, matplotlib, scipy, rtree, networkx.
- **OpenSCAD** (optional, only for the `.scad` path): `brew install --cask openscad`.

Verify: `.venv/bin/python .claude/skills/design-stl/scripts/validate.py examples/hydrogen_molecule.stl`
should print a printability report.
