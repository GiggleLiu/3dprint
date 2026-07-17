# AGENTS.md

Guidance for any coding agent (Codex, Claude Code, Cursor, Gemini, …) working in
this repo. Claude Code reads this via [`CLAUDE.md`](CLAUDE.md), which imports it;
other agents read `AGENTS.md` directly. Human-facing overview is in
[`README.md`](README.md).

## What this repo is

A set of **3D-printing skills** that go from an idea to a finished print on a
Bambu Lab printer over the local network:

- **`design-stl`** — turn a natural-language description into a *printable* STL via
  a generate→verify loop (default engine: Python + trimesh; OpenSCAD optional).
- **`preview-stl`** — present STLs as one self-contained HTML WebGL viewer page
  (multi-part scenes, exploded/ghost/negative-space views) and physics-simulate a
  ball rolling through the printed geometry, animated in the viewer.
- **`print-to-bambu`** — slice an STL and print it over LAN, behind safety gates.
- **`onboard`** — one-time setup (slicer, venv, config, Developer/LAN Mode).

Each skill lives in `.claude/skills/<name>/`. **The authoritative procedure for a
skill is its `SKILL.md`** — read `.claude/skills/<name>/SKILL.md` before doing that
workflow. (Claude Code loads these through its Skill mechanism; other agents should
open and follow the file directly.)

## Environment & running scripts

- **Set up / check the environment first** (idempotent — run with the *system*
  `python3`, it bootstraps the venv): `python3
  .claude/skills/onboard/scripts/setup_env.py [--with-design] [--check]`. It verifies
  Python ≥ 3.11, creates `.venv` if missing, and installs any missing deps.
- Then run every skill script with the project venv: **`.venv/bin/python <script>`**.
  Slicing itself needs only Python 3.11+ (stdlib `tomllib`); only the LAN
  print/monitor step needs `bambulabs-api`.
- Dependencies are per-skill: `.claude/skills/<name>/requirements.txt`. The example
  models use `examples/requirements.txt`.
- Scripts print a human summary on **stderr** and machine-readable **JSON** on
  **stdout**.

## Hard rules (do not violate)

1. **Never start a print without explicit human approval.** Starting a print heats
   the printer and extrudes plastic, often unattended. After slicing, show the user
   print time + filament weight + temps + resolved parameters and wait for a "yes".
   Use `send.py --dry-run` for end-to-end tests (uploads, does not print). `send.py`
   additionally enforces a live *parameter gate* (it refuses to start if the
   configured filament source is empty/mismatched) — do not blindly `--force` past it.
2. **Never commit secrets.** `bambu.toml` and any `bambu.*.toml` profile hold the
   printer's LAN access code and are gitignored. Only `bambu.toml.example`
   (placeholders) is committed. Check `git status` before committing.
3. **Don't commit generated artifacts.** STLs, `.gcode.3mf`, `.viewer.html`, and
   preview PNGs are reproducible from their builders and are gitignored. Stash large
   stale ones in **`local/`** (gitignored scratch). Small curated example models that
   are worth keeping live in `examples/` (tracked).
4. **Starting a print requires the printer in Developer/LAN Mode.** Slicing and
   monitoring work without it.

## Layout

```
.claude/skills/        # the skills (design-stl, preview-stl, print-to-bambu, onboard) + SKILL.md each
docs/superpowers/specs/ # design notes for the skills
examples/              # curated, tracked example builders + assets (hydrogen_molecule.py, model.py)
local/                 # gitignored scratch: generated STLs & build artifacts
bambu.toml.example     # placeholder printer config; copy to bambu.toml (gitignored) and fill in
README.md              # human-facing overview
```

## Git conventions

- Do substantial work on a branch and open a PR; keep `main` releasable.
- Keep the working tree clean of secrets and large generated binaries (see rules 2–3).
- Commit messages: explain the *why*, not just the *what*.
