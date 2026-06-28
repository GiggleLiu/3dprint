#!/usr/bin/env python3
"""Upload a sliced .gcode.3mf to the Bambu printer over LAN and start the print.

REQUIRES the printer in Developer/LAN Mode (print initiation is otherwise gated
by Bambu's Authorization Control). With --dry-run, the file is uploaded but the
print is NOT started — the safe end-to-end test path.

The slice summary should already have been shown to and confirmed by the user
before this runs (the confirmation gate lives in SKILL.md, not here).

Before starting a real print, send.py also runs a *parameter gate*: it reads the
printer's live filament sources (AMS slots / external spool) and reconciles them
with the config (use_ams / ams_tray) and the slice (filament type, bed type). If
the configured source is empty or mismatched it refuses to start (override with
--force). This catches the "moves but extrudes nothing" class of failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import eprint, load_config  # noqa: E402
from _printer import (  # noqa: E402
    connect, disconnect, load_ams_tray, read_sources, read_status)


def read_plate_meta(threemf: Path, plate: int) -> dict:
    """Pull the slice's key parameters from the embedded G-code (best effort)."""
    try:
        with zipfile.ZipFile(threemf) as z:
            names = z.namelist()
            target = next((n for n in (f"Metadata/plate_{plate}.gcode",
                                       "Metadata/plate_1.gcode") if n in names),
                          next((n for n in names if n.endswith(".gcode")), None))
            g = z.read(target).decode("utf-8", "replace") if target else ""
    except (zipfile.BadZipFile, OSError, KeyError):
        g = ""

    def find(*pats):
        for p in pats:
            m = re.search(p, g, re.IGNORECASE | re.MULTILINE)
            if m:
                return m.group(1).strip()
        return None

    return {
        "filament_type": find(r";\s*filament_type\s*[:=]\s*\"?([A-Za-z0-9+\- ]+)"),
        "bed_temp": find(r"^M190\s+S(\d+)", r"^M140\s+S(\d+)"),
        "bed_type": find(r";\s*curr_bed_type\s*[:=]\s*([^\n;]+)"),
        "nozzle_temp": find(r"^M109\s+S(\d+)", r";\s*nozzle_temperature\s*[:=]\s*\[?(\d+)"),
    }


def build_print_plan(meta: dict, sources: dict, use_ams: bool, ams_tray: int,
                     bed_type_configured: bool = True) -> dict:
    """Reconcile config (use_ams/ams_tray) + slice against the printer's live
    filament sources. Returns resolved params with blocking errors / warnings.

    This is the parameter-confirmation gate's brain: it exists so we never start
    a print whose filament source is empty (the failure that wasted a run).

    Setup-time parameters (the build plate, whether there's an AMS) are confirmed
    once and live in the config — when present they're trusted and only shown, not
    re-warned. Only volatile, per-print facts (is the chosen slot actually loaded?
    does its filament type match the slice?) are re-checked every print. That's
    why bed_type_configured suppresses the plate nags.
    """
    blocks, warns = [], []
    fil = (meta.get("filament_type") or "").strip()

    if use_ams:
        tray = next((t for t in sources["trays"] if t["slot"] == ams_tray), None)
        if not sources["ams_present"]:
            blocks.append(f"use_ams=true but no AMS is detected on the printer.")
            source = f"AMS slot {ams_tray} (AMS NOT FOUND)"
        elif tray is None:
            blocks.append(f"AMS slot {ams_tray} does not exist on this AMS.")
            source = f"AMS slot {ams_tray} (missing)"
        elif tray["empty"]:
            blocks.append(f"AMS slot {ams_tray} is EMPTY — nothing to extrude.")
            source = f"AMS slot {ams_tray} (empty)"
        else:
            source = f"AMS slot {ams_tray}: {tray['type']} #{tray['color'][:6]}"
            if fil and tray["type"] and fil.upper() not in tray["type"].upper() \
                    and tray["type"].upper() not in fil.upper():
                warns.append(f"slice uses {fil} but AMS slot {ams_tray} is "
                             f"{tray['type']} — filament type mismatch.")
            if "support" in tray["type"].lower() or tray["type"].upper().endswith("-S"):
                warns.append(f"AMS slot {ams_tray} ({tray['type']}) looks like a "
                             "SUPPORT filament — is that intended for the model?")
    else:
        source = "external spool"
        loaded_ams = [t for t in sources["trays"] if not t["empty"]]
        if not sources["external_loaded"] and loaded_ams:
            blocks.append("use_ams=false but the external spool is empty AND your "
                          f"AMS has filament ({len(loaded_ams)} slot(s)). The printer "
                          "would extrude nothing. Set [print].use_ams=true.")
        elif not sources["external_loaded"]:
            warns.append("external spool reports no filament — confirm it is loaded "
                         "to the nozzle.")

    # Bed / plate: a SETUP-time parameter. If the plate was chosen at setup
    # (bed_type in config) we trust it and only display it — no per-print nag.
    # We only warn when it was never set (setup is incomplete).
    bed_t = meta.get("bed_temp")
    if not bed_type_configured:
        warns.append("no build-plate type set in config — slicer used its default "
                     "(often Cool Plate, too cold for PLA on textured PEI). Set "
                     "[slice].bed_type once, at setup.")
        try:
            if bed_t is not None and int(bed_t) < 40 and fil.upper().startswith("PLA"):
                warns.append(f"bed is only {bed_t}°C for PLA — likely won't stick.")
        except ValueError:
            pass

    return {
        "source": source,
        "filament": fil or "?",
        "bed": f"{bed_t}°C on {meta.get('bed_type') or '(default plate)'}",
        "nozzle": f"{meta.get('nozzle_temp') or '?'}°C",
        "blocks": blocks,
        "warnings": warns,
        "ok": not blocks,
    }


def _verify_upload(printer, remote_name: str) -> bool:
    """Confirm the file is actually on the printer after STOR.

    bambulabs-api's FTP layer swallows errors (e.g. 553 'Could not create
    file') and returns None, so a STOR that never wrote still looks like it
    succeeded. We re-list the target directory and check the file is there.
    """
    base = remote_name.rsplit("/", 1)[-1]
    folder = remote_name.rsplit("/", 1)[0] if "/" in remote_name else ""
    try:
        _res, lines = printer.ftp_client.list_directory(folder)
    except Exception:
        return False
    return any(base in line for line in (lines or []))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("threemf", help="path to the sliced .gcode.3mf to print")
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    ap.add_argument("--printer", help="use the bambu.<name>.toml profile")
    ap.add_argument("--dry-run", action="store_true",
                    help="upload but do NOT start the print")
    ap.add_argument("--remote-name", help="filename to store on the printer "
                    "(default: basename of the 3mf)")
    ap.add_argument("--ams-tray", type=int,
                    help="AMS slot (0-3) to print from; overrides [print].ams_tray "
                    "(only used when use_ams is true)")
    ap.add_argument("--force", action="store_true",
                    help="start the print even if the parameter gate finds a "
                    "blocking mismatch (e.g. empty source). Use with care.")
    args = ap.parse_args()

    threemf = Path(args.threemf).expanduser().resolve()
    if not threemf.is_file():
        eprint(f"✗ File not found: {threemf}")
        return 1
    if not threemf.name.endswith(".3mf"):
        eprint(f"✗ Expected a .gcode.3mf file, got: {threemf.name}")
        return 1

    cfg = load_config(args.config, printer=args.printer)
    print_cfg = cfg.get("print", {}) or {}
    plate = int(cfg.get("slice", {}).get("plate", 1))
    use_ams = bool(print_cfg.get("use_ams", False))
    ams_tray = args.ams_tray if args.ams_tray is not None else \
        int(print_cfg.get("ams_tray", 0))
    remote_name = args.remote_name or threemf.name

    printer = connect(cfg)
    result: dict = {"uploaded": False, "started": False, "remote_name": remote_name,
                    "dry_run": args.dry_run}
    try:
        eprint(f"Uploading {threemf.name} -> {remote_name} ...")
        with threemf.open("rb") as fh:
            ret = printer.upload_file(fh, remote_name)  # closes fh internally
        if not _verify_upload(printer, remote_name):
            result["uploaded"] = False
            eprint(f"✗ Upload FAILED — {remote_name} is not on the printer after "
                   f"STOR (library returned {ret!r}).")
            eprint("  The printer's FTP refused to create the file (typically "
                   "'553 Could not create file'). It could not write to storage.")
            eprint("  Common causes / fixes:")
            eprint("   • microSD card missing, full, or write-locked — uploads are "
                   "stored there. Insert / free / unlock a FAT32 card.")
            eprint("   • Developer/LAN Mode enabled without the required reboot — "
                   "power-cycle the printer, then retry.")
            print(json.dumps(result, indent=2))
            return 1
        result["uploaded"] = True
        eprint("✓ Uploaded (verified present on printer).")

        if args.dry_run:
            eprint("• --dry-run: NOT starting the print.")
        else:
            # Parameter-confirmation gate: reconcile the slice + config against
            # the printer's live filament sources before extruding anything.
            meta = read_plate_meta(threemf, plate)
            sources = read_sources(printer)
            bed_type_set = bool(cfg.get("slice", {}).get("bed_type"))
            plan = build_print_plan(meta, sources, use_ams, ams_tray, bed_type_set)
            result["plan"] = plan
            eprint("── print parameters ──────────────────────────────")
            eprint(f"  source   : {plan['source']}")
            eprint(f"  filament : {plan['filament']}")
            eprint(f"  bed      : {plan['bed']}")
            eprint(f"  nozzle   : {plan['nozzle']}")
            for w in plan["warnings"]:
                eprint(f"  ⚠ {w}")
            for b in plan["blocks"]:
                eprint(f"  ✗ {b}")
            eprint("──────────────────────────────────────────────────")
            if plan["blocks"] and not args.force:
                eprint("✗ Not starting: the parameter gate found a blocking "
                       "mismatch above. Fix it, or pass --force to override.")
                print(json.dumps(result, indent=2))
                return 1

            # Pre-load the AMS slot to the nozzle. A print with use_ams alone does
            # NOT reliably trigger the load (printer prints dry, tray_now=255), so
            # we load it explicitly and confirm before starting.
            if use_ams and sources.get("tray_now") != ams_tray:
                noz = int(meta.get("nozzle_temp") or 220)
                eprint(f"Loading AMS slot {ams_tray} to the nozzle (this heats + "
                       "feeds; ~1-2 min) ...")
                if load_ams_tray(printer, ams_tray, temp=noz):
                    eprint(f"✓ AMS slot {ams_tray} loaded (filament at nozzle).")
                    result["preloaded"] = True
                elif not args.force:
                    eprint(f"✗ Not starting: AMS slot {ams_tray} did not load "
                           "(filament not feeding — check the spool is threaded "
                           "into the AMS). Override with --force.")
                    print(json.dumps(result, indent=2))
                    return 1

            ams_mapping = [ams_tray] if use_ams else [0]
            eprint(f"Starting print: plate {plate}, {plan['source']} ...")
            ok = printer.start_print(remote_name, plate, use_ams=use_ams,
                                     ams_mapping=ams_mapping)
            result["started"] = bool(ok)
            result["source"] = plan["source"]
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
