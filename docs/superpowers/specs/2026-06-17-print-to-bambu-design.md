# Design: `print-to-bambu` skill

**Date:** 2026-06-17
**Status:** Approved design, pending spec review

## Summary

A Claude Code **project skill, committed to this repo**, that takes an STL file
(e.g. the repo's `hydrogen_molecule.stl`), slices it with OrcaSlicer's headless
CLI, shows the user a slice summary, and — only after explicit confirmation —
uploads it to a Bambu Lab printer over the **local network (LAN / Developer
Mode)** and monitors the print to completion.

The skill is **machine-agnostic** and ships with the repo so anyone who clones
it gets it. No printer credentials are ever committed.

## Goals

- One command path: STL in → physical print out, on a LAN Bambu printer.
- Reliable, scriptable slicing via a command-line slicer.
- A human confirmation gate before any plastic is extruded.
- Safe to distribute: zero secrets in version control; works for whatever Bambu
  model the user owns.

## Non-goals (YAGNI)

Bambu Cloud mode, multi-printer farms, AMS multi-color mapping, camera/video
feed, arbitrary mesh repair, and any GUI. The skill prints **one plate of one
STL on one LAN printer**, cleanly.

## Key decisions (from brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Pipeline scope | Full: slice + upload + print + monitor | User wants STL → physical print end to end |
| Connection | Local LAN mode (MQTT control + FTPS upload) | Offline, private, no Bambu account |
| Printer model | Configurable / machine-agnostic | User has multiple / unspecified models |
| Slicer | Auto-detect; **Bambu Studio preferred for the X2D** (see below), OrcaSlicer otherwise | Identical CLI flags (Orca is a fork); new models get profiles in Bambu Studio first |
| LAN library | `bambulabs-api` (pip) | Maintained Python lib for MQTT + FTPS + status |
| Safety gate | Confirm after slice, before print | Show size/time/filament/temps, then wait for go-ahead |
| Config storage | Local `bambu.toml`, gitignored | Set once, reused; secrets never committed |
| Location | In-repo project skill `.claude/skills/print-to-bambu/` | Ships with repo, usable by others |

## Critical prerequisite: Developer / LAN Mode

Since January 2025, Bambu firmware ships an **Authorization Control System** that
gates print *initiation* (and motion/fan/hotend/AMS control) behind Bambu's own
auth path. Third-party LAN printing — what this skill does — only works when the
printer has **Developer Mode** (a.k.a. "LAN Mode (Developer)") enabled, which
restores the legacy MQTT-control + FTPS-upload behavior without cloud.

- Plain **status/monitoring** over MQTT is *not* gated and works regardless.
- **Starting a print** *is* gated and requires Developer Mode.
- The skill detects this in preflight and fails with a clear, actionable message
  rather than hanging. `reference/developer-mode.md` documents how to enable it
  per model.

Sources: Bambu third-party integration wiki; Hackaday coverage of the
Authorization Control System (Jan 2025); OrcaSlicer/Bambu Studio CLI references
(Printago); `bambulabs-api` on PyPI.

## X2D-specific considerations

The target printer is a **Bambu Lab X2D** (launched April 2026): dual-nozzle
CoreXY, 256×256×260 mm, 90 °C heated chamber, Neural LiDAR 2.0. This is recent
enough to add three concrete constraints:

1. **Slicer profile availability.** Stable OrcaSlicer does **not** yet ship an
   X2D machine profile — only OrcaSlicer 2.4-Alpha / dev nightlies do; **Bambu
   Studio** has it officially. So for this machine the skill should prefer Bambu
   Studio (or a recent OrcaSlicer nightly). `preflight.py` must **validate that
   the configured `[slice].machine` profile actually exists in the detected
   slicer** and fail with a clear message ("this slicer has no X2D profile;
   install Bambu Studio or OrcaSlicer ≥2.4-alpha") rather than emitting a bad
   slice. The skill stays machine-agnostic; this is enforced by validation, not
   by hardcoding the X2D.
2. **Dual nozzle.** The X2D has two extruders. For our single-material,
   single-color PLA print the slice targets the **primary extruder only**;
   dual-material / support-interface / AMS mapping stays out of scope (YAGNI).
   The chosen X2D machine profile handles extruder assignment by default.
3. **LAN-library maturity risk.** `bambulabs-api` predates the X2D and may not
   yet model its status/telemetry schema or confirm Developer-Mode print
   initiation. Mitigation: keep `send.py`/`monitor.py` tolerant of unknown MQTT
   fields (degrade to a minimal "started / printing / done / error" view rather
   than crashing), and verify against the real printer in `--dry-run` first.
   Confirming X2D support is an explicit planning task below.

## Workflow

```
STL ─▶ preflight ─▶ slice (OrcaSlicer CLI) ─▶ summary ─▶ [USER CONFIRMS] ─▶ upload+start ─▶ monitor ─▶ done
                                                 │                                                │
                                          est. time, filament g,                          progress %, temps,
                                          dims, nozzle/bed temps                           layer, time left
```

Control flow (encoded in `SKILL.md`):

1. Run `preflight.py`. If `bambu.toml` is missing → run `setup_config.py`, tell
   the user to fill it in and enable Developer Mode, then stop.
2. Run `slice.py` on the target STL.
3. **Present the slice summary and STOP for explicit user confirmation** (safety
   gate). Slicing itself is automatic; printing is not.
4. On confirmation → `send.py` (upload via FTPS + start print via MQTT).
5. `monitor.py` streams progress until completion; report final status.

## Components

```
3dprint/                          # this repo
├── hydrogen_molecule.py
├── hydrogen_molecule.stl
├── README.md                     # + new "Printing on a Bambu printer" section
├── bambu.toml                    # user config — GITIGNORED, scaffolded on first run
├── bambu.toml.example            # committed template, no secrets
├── .gitignore                    # contains `bambu.toml`
└── .claude/
    └── skills/
        └── print-to-bambu/
            ├── SKILL.md
            ├── scripts/
            │   ├── preflight.py
            │   ├── setup_config.py
            │   ├── slice.py
            │   ├── send.py
            │   └── monitor.py
            ├── requirements.txt  # bambulabs-api, tomli (py<3.11)
            └── reference/
                └── developer-mode.md
```

Each script is an independently testable unit with a JSON-or-stream interface:

| Script | Input | Output | Depends on |
|--------|-------|--------|-----------|
| `preflight.py` | config | JSON `{slicer_ok, lib_ok, config_ok, printer_reachable, dev_mode_hint}` | slicer binary, network |
| `setup_config.py` | — | writes `bambu.toml` from template, adds it to `.gitignore` | filesystem |
| `slice.py <stl>` | STL + config | `<name>.gcode.3mf` + JSON `{time, filament_g, dims, nozzle_temp, bed_temp, plate, output}` | OrcaSlicer / Bambu Studio CLI |
| `send.py <3mf> [--dry-run]` | sliced 3mf + config | JSON `{uploaded, started, remote_name}` | `bambulabs-api` (FTPS + MQTT) |
| `monitor.py` | config | streamed progress lines until done/error | `bambulabs-api` (MQTT) |

## Config schema: `bambu.toml`

```toml
[printer]
ip          = "192.168.x.x"
serial      = "XXXXXXXXXXXXXXX"
# access_code resolved from env BAMBU_ACCESS_CODE first, then this field
access_code = ""

[slicer]
binary = ""            # blank = auto-detect OrcaSlicer, then Bambu Studio

[slice]
machine      = "Bambu Lab X2D 0.4 nozzle"   # exact string TBD from installed slicer; target is an X2D
filament     = "Bambu PLA Basic"
layer_height = 0.2
infill       = 0.15
supports     = false
plate        = 1
```

- `setup_config.py` copies `bambu.toml.example` → `bambu.toml` and appends
  `bambu.toml` to `.gitignore`.
- Access code precedence: `BAMBU_ACCESS_CODE` env var > `bambu.toml` field.
- The committed `bambu.toml.example` contains only placeholders.

## Slicing details

- Invoke OrcaSlicer/Bambu Studio CLI with `--slice`, `--load-settings`,
  `--load-filaments`, `--export-3mf` (output is a `.gcode.3mf` archive with the
  G-code embedded, not raw `.gcode`).
- Estimates (print time, filament weight, dimensions, nozzle/bed temps) are read
  back from the sliced output by unzipping the `.gcode.3mf` and parsing the
  embedded plate G-code header (OrcaSlicer writes estimated time + filament
  weight there).
- Binary auto-detection: prefer OrcaSlicer, fall back to Bambu Studio; honor an
  explicit `[slicer].binary` path. Flags are identical between the two.
- Note: a known mid-2026 OrcaSlicer CLI bug blocks re-slicing *Bambu-authored*
  `.3mf` project files. It does **not** affect slicing a fresh STL (our case).

## Send + monitor details

- `send.py` uses `bambulabs-api` to connect over LAN (MQTT + FTPS using IP +
  serial + access code), upload the `.gcode.3mf`, then issue the print-start
  command referencing the uploaded file and `[slice].plate`.
- `--dry-run` performs everything **except** the final print-start (optionally
  uploads but never starts). This is both the safety escape hatch and the
  end-to-end test path that is safe to run against a real printer.
- `monitor.py` polls MQTT status and streams progress (percentage, current
  layer, time remaining, nozzle/bed temps) until the print finishes or errors.

## Error handling

Every failure mode fails fast with a specific, actionable message and never
leaves a half-started print:

- `bambu.toml` missing → scaffold + instruct, stop.
- Slicer binary not found → name both slicers + install hint.
- `bambulabs-api` not installed → `pip install -r requirements.txt` hint.
- Printer unreachable (bad IP / off network) → connectivity message.
- Bad access code / auth failure → credential message.
- Print init gated (Developer Mode off) → point at `reference/developer-mode.md`.
- Slicing failure (bad mesh, profile mismatch) → surface slicer stderr.

## Testing

- **Unit:** config scaffold + validation; summary parsing from a fixture
  `.gcode.3mf`; `send.py` / `monitor.py` against a **mocked** `bambulabs-api`
  `Printer`.
- **Integration (skipped if slicer absent):** slice the repo's
  `hydrogen_molecule.stl`, assert a `.gcode.3mf` is produced and a summary
  parses.
- **`--dry-run` end-to-end:** slice → summary → connect → upload → stop before
  print. Safe to run against the real printer.

## Distribution notes

- This folder is **not yet a git repo**; committing the skill requires
  `git init` first (offered at implementation time).
- No secrets in version control: `bambu.toml` is gitignored; only
  `bambu.toml.example` (placeholders) is committed.
- The repo `README.md` gains a "Printing on a Bambu printer" section covering:
  install a supported slicer (Bambu Studio, or OrcaSlicer with a profile for your
  model — note the X2D needs Bambu Studio or OrcaSlicer ≥2.4-alpha),
  `pip install -r .claude/skills/print-to-bambu/requirements.txt`, enable
  Developer Mode, run `setup_config.py`, fill in `bambu.toml`.

## Implementation status (2026-06-17)

Implemented in `.claude/skills/`. Verified on this machine:
- Slicing the repo's `hydrogen_molecule.stl` for the **X2D** works in ~2s →
  valid `.gcode.3mf`, 19m print estimate, 4.28 g filament (weight recomputed from
  length, since Bambu's CLI writes 0.00 g). Bambu Studio 02.05.00.66 **does** ship
  the X2D profiles, so no slicer update was needed (preflight still validates this).
- `preflight.py` reports `ready_to_print=True`; printer is reachable on :8883.
- LAN print path (`send.py`/`monitor.py`) is coded against the real bambulabs-api
  2.6.6 surface, but a dry-run connect stays unauthenticated → **Developer/LAN
  Mode is currently OFF on the printer**. Enabling it is the only remaining step
  before a real print. (Matches the documented gate.)

Two additions beyond the original spec, by user request:
- `view.py` — self-contained three.js HTML viewer to orbit/zoom an STL pre-print.
- `onboard` skill (`/onboard`) — first-time setup walkthrough (slicer, venv,
  config, Developer Mode), driving `setup_config.py` + `preflight.py`.

Config gained a `[print].use_ams` toggle (AMS vs external spool).

## Open implementation questions (resolve during planning)

- Exact `bambulabs-api` method names for upload + start-print + status (verify
  against the installed version) **and whether that version supports the X2D**;
  if not, identify a fallback (newer release, fork, or raw MQTT/FTPS).
- Exact **X2D** machine/filament profile identifiers in the installed slicer
  (the `[slice].machine` / `filament` string values) — read from Bambu Studio's
  or OrcaSlicer-nightly's preset files / GUI dropdown.
- Confirm **Developer / LAN Mode exists and is enabled** on X2D firmware (the
  2026 Authorization Control system applies); confirm print initiation works
  over LAN before relying on it.
- Which slicer is actually installed on this machine (Bambu Studio vs OrcaSlicer
  nightly) — drives the auto-detect default for the X2D.
