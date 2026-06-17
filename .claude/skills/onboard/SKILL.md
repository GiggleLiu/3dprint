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

## 2. Python deps
```
python3 -m venv .venv
.venv/bin/pip install -r .claude/skills/print-to-bambu/requirements.txt
```
Run every later script with `.venv/bin/python` (that interpreter has bambulabs-api).

## 3. Config file
```
.venv/bin/python .claude/skills/print-to-bambu/scripts/setup_config.py
```
This writes a gitignored `bambu.toml`. Then help the user fill it in:
- `[printer] ip` and `serial` — from the printer screen (Settings → WLAN / Device).
- `[slice] machine/process/filament` — preset names EXACTLY as they appear in the
  slicer's dropdowns (preflight verifies they exist).
- access code — prefer `export BAMBU_ACCESS_CODE=...` over writing it to the file.

## 4. Developer / LAN Mode (required to START prints)
Slicing and monitoring work without it; **starting a print does not**. Walk the
user through `.claude/skills/print-to-bambu/reference/developer-mode.md` and have
them read the **access code** off the printer screen.

## 5. Verify
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
| machine/process/filament profile ✗ | slicer too old for the model, or wrong preset name |
| bambulabs-api ✗ | `pip install -r` into the interpreter you run scripts with |
| printer unreachable | wrong IP, printer off, or different subnet |
| connects (TCP) but dry-run send times out | Developer/LAN Mode is OFF, or access code rotated |

When `ready_to_print=True`, hand off to the **print-to-bambu** skill.

## (Optional) design-stl deps

If the user also wants to *design* models from descriptions (the **design-stl**
skill), set up two extra things:
- **OpenSCAD binary**: `brew install --cask openscad` (macOS).
- **trimesh**: `.venv/bin/pip install -r .claude/skills/design-stl/requirements.txt`

Verify: `.venv/bin/python .claude/skills/design-stl/scripts/validate.py hydrogen_molecule.stl`
should print a printability report.
