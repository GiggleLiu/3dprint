#!/usr/bin/env python3
"""Discover slicer presets so you never have to guess names in bambu.toml.

  list_presets.py                      # list selectable machine profiles
  list_presets.py --machine "<name>"   # process + filament presets COMPATIBLE
                                       #   with that machine (the only ones that
                                       #   will actually slice)
  list_presets.py --machine "<name>" --suggest   # also print ready-to-paste
                                       #   [slice] lines with sensible defaults

Human summary on stderr, JSON on stdout. Compatibility is read from each
preset's compatible_printers (following `inherits`); the slicer hard-rejects an
incompatible *process*, which is the trap this tool exists to avoid.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import (  # noqa: E402
    compatible_presets, eprint, find_slicer, list_machines, load_config,
)


def _pick(names: list[str], *prefer: str) -> str | None:
    """First name matching any preferred substring, else the first name."""
    for sub in prefer:
        for n in names:
            if sub.lower() in n.lower():
                return n
    return names[0] if names else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--machine", help="show presets compatible with this machine")
    ap.add_argument("--suggest", action="store_true",
                    help="print ready-to-paste [slice] defaults")
    ap.add_argument("--config", help="path to bambu.toml (for slicer discovery)")
    args = ap.parse_args()

    # Slicer can be found even without a full config; fall back to empty cfg.
    try:
        cfg = load_config(args.config)
    except Exception:
        cfg = {}
    slicer_path, kind = find_slicer(cfg)
    if slicer_path is None:
        eprint("✗ No slicer found. Install Bambu Studio/OrcaSlicer or set "
               "[slicer].binary.")
        return 1

    if not args.machine:
        machines = list_machines(slicer_path)
        eprint(f"Selectable machine profiles in {kind} ({len(machines)}):")
        for m in machines:
            eprint(f"  {m}")
        eprint("\nNext: list_presets.py --machine \"<name>\"")
        print(json.dumps({"slicer": kind, "machines": machines}, indent=2))
        return 0

    machine = args.machine
    procs = compatible_presets(slicer_path, "process", machine)
    filas = compatible_presets(slicer_path, "filament", machine)
    eprint(f"Presets compatible with '{machine}':")
    eprint(f"  process  ({len(procs)}):")
    for p in procs:
        eprint(f"    {p}")
    eprint(f"  filament ({len(filas)}):")
    for f in filas:
        eprint(f"    {f}")
    if not procs:
        eprint("  ⚠ no compatible process found — is the machine name exact?")

    result = {"machine": machine, "process": procs, "filament": filas}

    if args.suggest:
        proc = _pick(procs, "0.20mm Standard", "Standard")
        fila = _pick(filas, "Bambu PLA Basic", "PLA Basic", "PLA")
        result["suggested"] = {"machine": machine, "process": proc, "filament": fila}
        eprint("\nSuggested [slice] block:")
        eprint("  [slice]")
        eprint(f'  machine  = "{machine}"')
        eprint(f'  process  = "{proc}"')
        eprint(f'  filament = "{fila}"')
        eprint("  plate    = 1")

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
