#!/usr/bin/env python3
"""Scaffold a local bambu.toml from bambu.toml.example and gitignore it.

Idempotent: refuses to overwrite an existing bambu.toml unless --force.
Writes bambu.toml into the current working directory (your project root).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="overwrite existing bambu.toml")
    args = ap.parse_args()

    dest = Path.cwd() / "bambu.toml"
    if dest.exists() and not args.force:
        print(f"✓ {dest} already exists (use --force to overwrite). Nothing changed.")
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
    print()
    print("Next steps:")
    print("  1. Edit bambu.toml: set printer ip, serial, and slice preset names.")
    print("  2. Put your LAN access code in the BAMBU_ACCESS_CODE env var")
    print("     (export BAMBU_ACCESS_CODE=...) or in bambu.toml.")
    print("  3. Enable Developer/LAN Mode on the printer — see")
    print("     .claude/skills/print-to-bambu/reference/developer-mode.md")
    print("  4. Run preflight.py to verify everything is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
