#!/usr/bin/env python3
"""Upload a sliced .gcode.3mf to the Bambu printer over LAN and start the print.

REQUIRES the printer in Developer/LAN Mode (print initiation is otherwise gated
by Bambu's Authorization Control). With --dry-run, the file is uploaded but the
print is NOT started — the safe end-to-end test path.

The slice summary and live printer status should already have been shown to and
confirmed by the user before this runs with --status-confirmed. Without that
flag, send.py prints the live status/parameter block and exits before upload,
preload, or start.

Before starting a real print, send.py also runs a *parameter gate*: it reads the
printer's live filament sources (AMS slots / external spool) and reconciles them
with the config (use_ams / ams_tray) and the slice (filament type, bed type). If
the configured source is empty or mismatched it refuses to start (override with
--force). This catches the "moves but extrudes nothing" class of failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import eprint, load_config  # noqa: E402
from _printer import (  # noqa: E402
    connect, disconnect, load_ams_tray, read_sources, read_status,
    start_project_file, wait_filament_change_done, wait_print_started)


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


def read_project_meta(threemf: Path, plate: int) -> dict:
    """Read project-file metadata needed for a direct MQTT project_file start."""
    with zipfile.ZipFile(threemf) as z:
        names = set(z.namelist())
        gcode_path = f"Metadata/plate_{plate}.gcode"
        if gcode_path not in names:
            gcode_path = next((n for n in names if n.endswith(".gcode")), gcode_path)
        gcode = z.read(gcode_path)

        md5_path = f"{gcode_path}.md5"
        if md5_path in names:
            md5 = z.read(md5_path).decode("utf-8", "replace").strip()
        else:
            md5 = hashlib.md5(gcode).hexdigest().upper()

        plate_json_path = f"Metadata/plate_{plate}.json"
        plate_json = {}
        if plate_json_path in names:
            try:
                plate_json = json.loads(z.read(plate_json_path))
            except json.JSONDecodeError:
                plate_json = {}

        slice_filament_ids = []
        if "Metadata/slice_info.config" in names:
            try:
                root = ET.fromstring(z.read("Metadata/slice_info.config"))
                for elem in root.findall(".//filament"):
                    fid = elem.get("id")
                    if fid is not None:
                        slice_filament_ids.append(int(fid))
            except (ET.ParseError, TypeError, ValueError):
                slice_filament_ids = []

        sequence_filament_ids = []
        if "Metadata/filament_sequence.json" in names:
            try:
                sequence_data = json.loads(z.read("Metadata/filament_sequence.json"))
                sequence = (sequence_data.get(f"plate_{plate}", {}) or {}).get("sequence")
                if isinstance(sequence, list):
                    sequence_filament_ids = [int(v) for v in sequence]
            except (json.JSONDecodeError, TypeError, ValueError):
                sequence_filament_ids = []

        project_settings = {}
        if "Metadata/project_settings.config" in names:
            try:
                project_settings = json.loads(
                    z.read("Metadata/project_settings.config"))
            except json.JSONDecodeError:
                project_settings = {}

    return {
        "gcode_path": gcode_path,
        "md5": md5,
        "plate_json": plate_json,
        "slice_filament_ids": slice_filament_ids,
        "sequence_filament_ids": sequence_filament_ids,
        "project_settings": project_settings,
    }


def is_dual_nozzle_family(machine: str | None) -> bool:
    """True for printer families whose project_file payload needs H2/X2 routing."""
    m = (machine or "").lower()
    return any(token in m for token in ("x2d", "h2d", "h2c", "h2s"))


def _plate_filament_ids(project_meta: dict) -> list[int]:
    # X2D/H2 firmware keys the print-command mapping to the filament IDs used
    # by slice_info.config / filament_sequence.json. plate_1.json is zero-based
    # display metadata; using it mapped AMS slot 3 onto index 0 while the G-code
    # used filament 1, so firmware fell back to another loaded slot.
    for key in ("sequence_filament_ids", "slice_filament_ids"):
        ids = project_meta.get(key)
        if isinstance(ids, list) and ids:
            out = []
            for value in ids:
                try:
                    out.append(int(value))
                except (TypeError, ValueError):
                    pass
            if out:
                return sorted(set(out))

    ids = project_meta.get("plate_json", {}).get("filament_ids")
    if not isinstance(ids, list) or not ids:
        return [0]
    out = []
    for value in ids:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            pass
    return out or [0]


def build_project_payload(remote_name: str, plate: int, use_ams: bool,
                          ams_tray: int, project_meta: dict,
                          dual_nozzle_family: bool) -> dict:
    """Build a project_file payload.

    Older printers accepted bambulabs-api's compact ams_mapping=[slot] form.
    X2D/H2-family firmware is stricter: it expects mapping positions to line up
    with the project filament ids, plus the parallel ams_mapping2 table.
    """
    filament_ids = _plate_filament_ids(project_meta)
    map_len = max(filament_ids) + 1
    ams_mapping = [-1] * map_len
    ams_mapping2 = [{"ams_id": 255, "slot_id": 255} for _ in range(map_len)]
    if use_ams:
        ams_id, slot_id = divmod(int(ams_tray), 4)
        for fid in filament_ids:
            ams_mapping[fid] = int(ams_tray)
            ams_mapping2[fid] = {"ams_id": ams_id, "slot_id": slot_id}

    subtask = re.sub(r"(\.gcode)?\.3mf$", "", remote_name, flags=re.IGNORECASE)
    # BambuStudio-style fresh submission IDs. task_id=0 can make the printer
    # treat a reprint as a continuation and never cleanly transition into the
    # real print path on newer firmware.
    submission_id = str(int(time.time() * 1000) % 2_147_483_647 or 1)
    payload = {
        "sequence_id": "20000",
        "command": "project_file",
        "param": project_meta["gcode_path"],
        "url": f"ftp://{remote_name}",
        "file": remote_name,
        # Leave empty to match Bambuddy's current LAN dispatch behavior and
        # avoid activating validation with the wrong digest type.
        "md5": "",
        "bed_type": "auto",
        "timelapse": False,
        "bed_leveling": True,
        "bed_levelling": True,
        "auto_bed_leveling": 1,
        "flow_cali": False,
        "vibration_cali": True,
        "layer_inspect": False,
        "use_ams": bool(use_ams),
        "cfg": "0",
        "extrude_cali_flag": 0,
        "extrude_cali_manual_mode": 0,
        "nozzle_offset_cali": 0,
        "subtask_name": subtask,
        "profile_id": "0",
        "project_id": submission_id,
        "subtask_id": submission_id,
        "task_id": submission_id,
        "ams_mapping": ams_mapping,
    }
    if dual_nozzle_family:
        payload["ams_mapping2"] = ams_mapping2

    return payload


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


def status_gate(status: dict) -> dict:
    """Return printer-status blocks/warnings for the pre-start confirmation."""
    blocks, warnings = [], []
    state = (status.get("state") or "").upper()
    if not state or state == "UNKNOWN":
        blocks.append("printer live status is UNKNOWN; wait for a real status update.")
    if state in {"RUNNING", "PAUSE", "PAUSED", "PREPARE", "PREPARING", "HEATING"}:
        blocks.append(f"printer is not idle; current state is {state}.")

    try:
        nozzle_values = [float(status.get("nozzle_temp") or 0)]
        nozzle_values.extend(
            float(ex.get("temp") or 0)
            for ex in status.get("dual_extruders") or [])
        nozzle = max(nozzle_values or [0.0])
        bed = float(status.get("bed_temp") or 0)
    except (TypeError, ValueError):
        nozzle, bed = 0.0, 0.0
    if nozzle > 50 or bed > 45:
        warnings.append(f"printer is already warm: nozzle {nozzle:g}°C, bed {bed:g}°C.")

    active_file = (status.get("file") or "").strip()
    if active_file:
        warnings.append(f"printer reports current file: {active_file}.")

    return {"blocks": blocks, "warnings": warnings, "ok": not blocks}


def read_settled_status(printer, timeout: float = 12.0) -> dict:
    """Wait briefly for a meaningful MQTT status instead of a blank snapshot."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = read_status(printer)
        state = (last.get("state") or "").upper()
        has_live_fields = (
            last.get("percent") is not None
            or last.get("bed_temp") not in (None, 0, 0.0)
            or bool(last.get("dual_extruders"))
        )
        if state and state != "UNKNOWN" and has_live_fields:
            return last
        time.sleep(0.5)
    return last


def emit_status(status: dict, sources: dict) -> None:
    """Print the live printer state that must be shown before start."""
    eprint("── printer status ───────────────────────────────")
    eprint(f"  state    : {status.get('state') or 'UNKNOWN'}")
    eprint(f"  progress : {status.get('percent') if status.get('percent') is not None else '?'}%")
    eprint(f"  layer    : {status.get('layer')}/{status.get('total_layers')}")
    eprint(f"  temps    : nozzle {status.get('nozzle_temp')}°C / "
           f"bed {status.get('bed_temp')}°C")
    for ex in status.get("dual_extruders") or []:
        if ex.get("temp") is None:
            continue
        target = ex.get("target")
        eprint(f"  extruder {ex.get('id')} : {ex.get('temp')}°C"
               f"{' -> ' + str(target) + '°C' if target is not None else ''}"
               f"  slot {ex.get('slot_now')}")
    eprint(f"  file     : {status.get('file') or '-'}")
    eprint(f"  AMS      : {'present' if sources.get('ams_present') else 'not detected'}")
    eprint(f"  tray_now : {sources.get('tray_now')} (255 = nothing at nozzle)")
    loaded = [t for t in sources.get("trays", []) if not t.get("empty")]
    if loaded:
        for tray in loaded:
            color = (tray.get("color") or "")[:6] or "?"
            eprint(f"  slot {tray['slot']:<2}  : {tray.get('type') or '?'} #{color}")
    else:
        eprint("  slots    : all empty")
    ext = sources.get("external_type") or ""
    eprint(f"  external : {ext or 'empty'}")
    eprint("──────────────────────────────────────────────────")


def emit_plan(plan: dict, gate: dict | None = None) -> None:
    """Print the resolved print parameters and any status/parameter issues."""
    eprint("── print parameters ──────────────────────────────")
    eprint(f"  source   : {plan['source']}")
    eprint(f"  filament : {plan['filament']}")
    eprint(f"  bed      : {plan['bed']}")
    eprint(f"  nozzle   : {plan['nozzle']}")
    if gate:
        for w in gate["warnings"]:
            eprint(f"  ⚠ {w}")
        for b in gate["blocks"]:
            eprint(f"  ✗ {b}")
    for w in plan["warnings"]:
        eprint(f"  ⚠ {w}")
    for b in plan["blocks"]:
        eprint(f"  ✗ {b}")
    eprint("──────────────────────────────────────────────────")


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
    ap.add_argument("--status-confirmed", action="store_true",
                    help="assert the live printer status + resolved print "
                    "parameters were shown to and approved by the user")
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
        if not args.dry_run:
            # Live status confirmation gate. This runs before upload and before
            # any command that can heat, load filament, or start motion.
            meta = read_plate_meta(threemf, plate)
            project_meta = read_project_meta(threemf, plate)
            status = read_settled_status(printer)
            sources = read_sources(printer)
            bed_type_set = bool(cfg.get("slice", {}).get("bed_type"))
            plan = build_print_plan(meta, sources, use_ams, ams_tray, bed_type_set)
            gate = status_gate(status)
            result["status"] = status
            result["sources"] = sources
            result["status_gate"] = gate
            result["plan"] = plan
            emit_status(status, sources)
            emit_plan(plan, gate)

            if gate["blocks"]:
                eprint("✗ Not starting: printer status is not safe to start. "
                       "Resolve the status block above.")
                print(json.dumps(result, indent=2))
                return 1
            if plan["blocks"] and not args.force:
                eprint("✗ Not starting: the parameter gate found a blocking "
                       "mismatch above. Fix it, or pass --force to override.")
                print(json.dumps(result, indent=2))
                return 1
            if not args.status_confirmed:
                eprint("✗ Not starting: live printer status has not been "
                       "confirmed by the user. Show the status and parameters "
                       "above, wait for explicit approval, then rerun with "
                       "--status-confirmed.")
                print(json.dumps(result, indent=2))
                return 1

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
            # Pre-load the AMS slot to the nozzle — ALWAYS, even when the state
            # says it is already loaded. A print with use_ams alone does NOT
            # trigger the load (prints dry, tray_now=255), and the X2D's
            # end-of-print cut+retract can leave tray_now/snow stale at
            # "loaded", which once cost a full job printed with no filament.
            # A refresh load on a genuinely loaded slot is a quick
            # cut/re-feed/purge; the wasted minute is cheap insurance.
            if use_ams:
                noz = int(meta.get("nozzle_temp") or 220)
                eprint(f"Loading AMS slot {ams_tray} to the nozzle (refresh "
                       "load: heats + feeds + purges; ~1-2 min) ...")
                if load_ams_tray(printer, ams_tray, temp=noz, refresh=True):
                    eprint(f"✓ AMS slot {ams_tray} loaded (filament at nozzle).")
                    result["preloaded"] = True
                    # The firmware keeps its filament-change flow busy for a
                    # while after the tray reaches the nozzle; a start sent in
                    # that window is silently dropped (X2D/H2). Wait it out.
                    if not wait_filament_change_done(printer):
                        eprint("⚠ filament-change flow still busy after 90s — "
                               "the start command may be ignored.")
                elif not args.force:
                    eprint(f"✗ Not starting: AMS slot {ams_tray} did not load "
                           "(filament not feeding — check the spool is threaded "
                           "into the AMS). Override with --force.")
                    print(json.dumps(result, indent=2))
                    return 1

            ams_mapping = [ams_tray] if use_ams else [0]
            eprint(f"Starting print: plate {plate}, {plan['source']} ...")
            machine = (cfg.get("slice", {}) or {}).get("machine", "")
            if is_dual_nozzle_family(machine):
                payload = build_project_payload(
                    remote_name, plate, use_ams, ams_tray, project_meta,
                    dual_nozzle_family=True)
                ok = start_project_file(printer, payload)
                result["start_mode"] = "direct_project_file"
                result["ams_mapping"] = payload.get("ams_mapping")
                result["ams_mapping2"] = payload.get("ams_mapping2")
            else:
                ok = printer.start_print(remote_name, plate, use_ams=use_ams,
                                         ams_mapping=ams_mapping)
                result["start_mode"] = "bambulabs_api"
                result["ams_mapping"] = ams_mapping
            result["source"] = plan["source"]
            if not ok:
                result["started"] = False
                eprint("✗ Printer rejected start_print (Developer Mode off? "
                       "see reference/developer-mode.md).")
            else:
                # A successful publish proves nothing: X2D/H2 firmware takes
                # ~30-40s to act on project_file and silently drops it in some
                # states. Only a gcode_state transition counts as started.
                eprint("Start command sent — waiting for the printer to act "
                       "(can take ~40s on X2D/H2) ...")
                started_state = wait_print_started(printer)
                result["started"] = started_state in ("RUNNING", "PREPARE")
                result["observed_state"] = started_state
                if result["started"]:
                    eprint(f"✓ Print started (printer is {started_state}).")
                elif started_state == "FAILED":
                    eprint("✗ Print FAILED right after start — check the "
                           "printer screen / HMS errors.")
                else:
                    eprint("✗ Printer never transitioned to RUNNING within "
                           "120s — the firmware silently dropped the start "
                           "command (busy filament change? stale job?). "
                           "Rerun send.py to retry.")
            result["status"] = read_status(printer)
    finally:
        disconnect(printer)

    print(json.dumps(result, indent=2))
    if args.dry_run:
        return 0 if result["uploaded"] else 1
    return 0 if result["started"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
