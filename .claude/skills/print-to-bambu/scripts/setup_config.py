#!/usr/bin/env python3
"""Scaffold a local bambu.toml from bambu.toml.example and gitignore it.

Idempotent: refuses to overwrite an existing bambu.toml unless --force.
Writes bambu.toml into the current working directory (your project root).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import (  # noqa: E402
    compatible_presets, find_slicer, list_machines,
)

SKILL_DIR = Path(__file__).resolve().parents[1]  # .../.claude/skills/print-to-bambu
# The committed template lives at the repo root in this project, but also ship a
# copy resolution that works if the skill is dropped into another repo.
TEMPLATE_CANDIDATES = [
    Path.cwd() / "bambu.toml.example",
    SKILL_DIR / "bambu.toml.example",
]


def find_template() -> Path | None:
    for c in TEMPLATE_CANDIDATES:
        if c.is_file():
            return c
    return None


def ensure_gitignored(root: Path) -> str:
    gi = root / ".gitignore"
    entry = "bambu.toml"
    if gi.is_file():
        lines = gi.read_text().splitlines()
        if any(line.strip() == entry for line in lines):
            return "already gitignored"
        with gi.open("a") as fh:
            if lines and lines[-1].strip():
                fh.write("\n")
            fh.write(f"# Printer credentials — never commit\n{entry}\n")
        return "appended to .gitignore"
    gi.write_text(f"# Printer credentials — never commit\n{entry}\n")
    return "created .gitignore"


def _pick(names: list[str], *prefer: str) -> str | None:
    for sub in prefer:
        for n in names:
            if sub.lower() in n.lower():
                return n
    return names[0] if names else None


def fill_slice_block(text: str, machine: str, process: str, filament: str) -> str:
    """Substitute machine/process/filament values in the [slice] block."""
    repl = {"machine": machine, "process": process, "filament": filament}
    for key, val in repl.items():
        if val is None:
            continue
        text = re.sub(rf'(?m)^(\s*{key}\s*=\s*)"[^"]*"', rf'\g<1>"{val}"', text)
    return text


def autofill_machine(dest: Path, machine: str) -> int:
    """Rewrite the [slice] block for a machine, choosing compatible defaults."""
    slicer_path, kind = find_slicer({})
    if slicer_path is None:
        print("✗ No slicer found; cannot auto-fill presets. Set them by hand.",
              file=sys.stderr)
        return 1
    machines = list_machines(slicer_path)
    if machine not in machines:
        print(f"✗ '{machine}' is not a selectable machine in {kind}.", file=sys.stderr)
        near = [m for m in machines if machine.split()[0].lower() in m.lower()][:8] \
            or machines[:8]
        print("  Did you mean one of:", file=sys.stderr)
        for m in near:
            print(f"    {m}", file=sys.stderr)
        return 1
    procs = compatible_presets(slicer_path, "process", machine)
    filas = compatible_presets(slicer_path, "filament", machine)
    process = _pick(procs, "0.20mm Standard", "Standard")
    filament = _pick(filas, "Bambu PLA Basic", "PLA Basic", "PLA")
    if not process:
        print(f"✗ No compatible process preset found for '{machine}'.", file=sys.stderr)
        return 1
    dest.write_text(fill_slice_block(dest.read_text(), machine, process, filament))
    print(f"✓ Auto-filled [slice] for {machine}:")
    print(f"    process  = {process}")
    print(f"    filament = {filament}")
    print(f"  ({len(procs)} compatible processes, {len(filas)} filaments — see "
          "list_presets.py --machine for alternatives.)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="overwrite existing bambu.toml")
    ap.add_argument("--machine", help="auto-fill [slice] with presets compatible "
                    "with this machine (e.g. \"Bambu Lab P1S 0.4 nozzle\")")
    args = ap.parse_args()

    dest = Path.cwd() / "bambu.toml"
    if dest.exists() and not args.force:
        # Allow --machine to (re)fill the [slice] block of an existing config
        # without touching credentials; otherwise leave it untouched.
        if args.machine:
            return autofill_machine(dest, args.machine)
        print(f"✓ {dest} already exists (use --force to overwrite, or pass "
              "--machine to refill presets). Nothing changed.")
        return 0

    template = find_template()
    if template is None:
        print("✗ Could not find bambu.toml.example. Run from your project root.",
              file=sys.stderr)
        return 1

    dest.write_text(template.read_text())
    gi_status = ensure_gitignored(Path.cwd())

    print(f"✓ Wrote {dest} (from {template.name})")
    print(f"✓ .gitignore: {gi_status}")
    if args.machine:
        print()
        autofill_machine(dest, args.machine)
    print()
    print("Next steps:")
    print("  1. Edit bambu.toml: set printer ip, serial"
          + ("." if args.machine else ", and slice preset names."))
    print("  2. Put your LAN access code in the BAMBU_ACCESS_CODE env var")
    print("     (export BAMBU_ACCESS_CODE=...) or in bambu.toml.")
    print("  3. Enable Developer/LAN Mode on the printer — see")
    print("     .claude/skills/print-to-bambu/reference/developer-mode.md")
    print("  4. Run preflight.py to verify everything is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
