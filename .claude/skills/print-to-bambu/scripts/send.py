#!/usr/bin/env python3
"""Upload a sliced .gcode.3mf to the Bambu printer over LAN and start the print.

REQUIRES the printer in Developer/LAN Mode (print initiation is otherwise gated
by Bambu's Authorization Control). With --dry-run, the file is uploaded but the
print is NOT started — the safe end-to-end test path.

The slice summary should already have been shown to and confirmed by the user
before this runs (the confirmation gate lives in SKILL.md, not here).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import eprint, load_config  # noqa: E402
from _printer import connect, disconnect, read_status  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("threemf", help="path to the sliced .gcode.3mf to print")
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    ap.add_argument("--dry-run", action="store_true",
                    help="upload but do NOT start the print")
    ap.add_argument("--remote-name", help="filename to store on the printer "
                    "(default: basename of the 3mf)")
    args = ap.parse_args()

    threemf = Path(args.threemf).expanduser().resolve()
    if not threemf.is_file():
        eprint(f"✗ File not found: {threemf}")
        return 1
    if not threemf.name.endswith(".3mf"):
        eprint(f"✗ Expected a .gcode.3mf file, got: {threemf.name}")
        return 1

    cfg = load_config(args.config)
    print_cfg = cfg.get("print", {}) or {}
    plate = int(cfg.get("slice", {}).get("plate", 1))
    use_ams = bool(print_cfg.get("use_ams", False))
    remote_name = args.remote_name or threemf.name

    printer = connect(cfg)
    result: dict = {"uploaded": False, "started": False, "remote_name": remote_name,
                    "dry_run": args.dry_run}
    try:
        eprint(f"Uploading {threemf.name} -> {remote_name} ...")
        with threemf.open("rb") as fh:
            printer.upload_file(fh, remote_name)  # closes fh internally
        result["uploaded"] = True
        eprint("✓ Uploaded.")

        if args.dry_run:
            eprint("• --dry-run: NOT starting the print.")
        else:
            eprint(f"Starting print: plate {plate}, use_ams={use_ams} ...")
            ok = printer.start_print(remote_name, plate, use_ams=use_ams)
            result["started"] = bool(ok)
            if ok:
                eprint("✓ Print started.")
            else:
                eprint("✗ Printer rejected start_print (Developer Mode off? "
                       "see reference/developer-mode.md).")
            result["status"] = read_status(printer)
    finally:
        disconnect(printer)

    print(json.dumps(result, indent=2))
    if args.dry_run:
        return 0 if result["uploaded"] else 1
    return 0 if result["started"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
