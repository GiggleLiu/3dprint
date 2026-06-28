#!/usr/bin/env python3
"""Readiness checks for the print-to-bambu skill.

Emits a JSON report on stdout and a human-readable summary on stderr. Checks:
config present/valid, slicer found, machine/process/filament presets exist AND
are mutually compatible, bambulabs-api importable, and the printer's authenticated
MQTT channel actually answers (not just an open TCP port — it also flags a printer
reachable only over a VPN tunnel).

Exit code: 0 if ready to slice, 1 otherwise. `ready_to_print` additionally
requires the library and the live API probe to succeed (see the JSON).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import (  # noqa: E402
    eprint, find_slicer, load_config, locality, preset_compatible_with,
    preset_json_path, route_iface, tcp_open,
)

MQTT_TLS_PORT = 8883


def probe_api(cfg: dict, timeout: float = 8.0) -> tuple[bool, str]:
    """Best-effort: does the authenticated MQTT channel answer with a state?

    Returns (api_responds, note). Needs bambulabs-api and the printer in
    LAN/Developer Mode; status push is not print-gated, so this is a faithful
    "the print channel is live" signal — far better than a bare TCP probe.
    """
    try:
        from _printer import connect, disconnect, read_status
    except Exception as e:  # library missing
        return False, f"cannot probe API ({e})"
    printer = None
    try:
        printer = connect(cfg, timeout=timeout, wait_state=True)
        state = read_status(printer).get("state")
        if state:
            return True, f"API responded (state={state})"
        return False, "connected but no status report (printer busy or LAN Mode off)"
    except SystemExit as e:
        return False, str(e).lstrip("✗ ").strip()
    except Exception as e:
        return False, f"API probe error: {e}"
    finally:
        if printer is not None:
            try:
                disconnect(printer)
            except Exception:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    ap.add_argument("--printer", help="use the bambu.<name>.toml profile")
    ap.add_argument("--no-api-probe", action="store_true",
                    help="skip the live MQTT probe (TCP reachability only)")
    args = ap.parse_args()

    report: dict = {
        "config": {"ok": False, "path": None, "error": None},
        "slicer": {"ok": False, "path": None, "kind": "unknown"},
        "machine_profile": {"ok": False, "name": None, "note": ""},
        "process_profile": {"ok": False, "name": None, "note": ""},
        "filament_profile": {"ok": False, "name": None, "note": ""},
        "library": {"ok": False, "note": ""},
        "printer": {"reachable": False, "ip": None, "note": "",
                    "interface": None, "network": "unknown", "api_responds": False},
        "ready_to_slice": False,
        "ready_to_print": False,
    }

    cfg = None
    try:
        cfg = load_config(args.config, printer=args.printer)
        report["config"]["ok"] = True
        report["config"]["path"] = str(cfg["_path"])
    except (FileNotFoundError, ValueError) as e:
        report["config"]["error"] = str(e)

    # Slicer + profiles
    if cfg is not None:
        slicer_path, kind = find_slicer(cfg)
        report["slicer"]["kind"] = kind
        if slicer_path is not None:
            report["slicer"]["ok"] = True
            report["slicer"]["path"] = str(slicer_path)
            sl = cfg.get("slice", {})
            machine_name = sl.get("machine")
            for key, field in (("machine", "machine_profile"),
                               ("process", "process_profile"),
                               ("filament", "filament_profile")):
                name = sl.get(key)
                report[field]["name"] = name
                exists = bool(name and preset_json_path(slicer_path, key, name))
                report[field]["ok"] = exists
                if not exists:
                    continue
                # Fix 1: existence isn't enough. The slicer HARD-rejects a
                # process whose compatible_printers omits the machine (that was
                # the "process not compatible with printer" failure). It is, by
                # contrast, lenient about filament compatibility (it will slice a
                # filament that only lists other nozzle sizes), so that's a
                # warning, not a blocker.
                if key in ("process", "filament") and machine_name:
                    compat = preset_compatible_with(slicer_path, key, name, machine_name)
                    if compat is False and key == "process":
                        report[field]["ok"] = False
                        report[field]["note"] = (
                            f"NOT compatible with '{machine_name}' — the slicer will "
                            "reject it. See: list_presets.py --machine \"<machine>\".")
                    elif compat is False and key == "filament":
                        report[field]["note"] = (
                            f"not listed for '{machine_name}' (usually a nozzle-size "
                            "mismatch); slices anyway — verify the result.")
                    elif compat is None:
                        report[field]["note"] = "compatibility unverified (no list)"
            if report["machine_profile"]["name"] and not report["machine_profile"]["ok"]:
                report["machine_profile"]["note"] = (
                    f"'{report['machine_profile']['name']}' not found in this slicer. "
                    "Update the slicer (X2D needs a 2026+ build) or fix the name.")

    # Library
    report["library"]["ok"] = importlib.util.find_spec("bambulabs_api") is not None
    if not report["library"]["ok"]:
        report["library"]["note"] = (
            "pip install -r .claude/skills/print-to-bambu/requirements.txt")

    # Printer: TCP reachability (informational) vs API actually answering (Fix 3).
    if cfg is not None:
        pr = report["printer"]
        ip = cfg.get("printer", {}).get("ip")
        pr["ip"] = ip
        placeholder = not ip or ip.startswith("192.168.x") or "x" in (ip or "").lower()
        if not placeholder:
            pr["reachable"] = tcp_open(ip, MQTT_TLS_PORT)
            iface = route_iface(ip)
            pr["interface"] = iface
            pr["network"] = locality(iface)
        notes = []
        if placeholder:
            notes.append("IP not set (placeholder).")
        elif not pr["reachable"]:
            notes.append("No TCP connect on :8883 — printer off, wrong IP, or different subnet.")
        else:
            if pr["network"] == "vpn":
                notes.append(f"reachable only via VPN tunnel ({iface}); "
                             "not on your local network.")
            # API probe: the honest "can I actually use this printer" signal.
            if report["library"]["ok"] and not args.no_api_probe:
                pr["api_responds"], api_note = probe_api(cfg)
                if not pr["api_responds"]:
                    notes.append(api_note)
            elif args.no_api_probe:
                notes.append("API probe skipped (--no-api-probe).")
        pr["note"] = " ".join(notes)

    report["ready_to_slice"] = (
        report["config"]["ok"] and report["slicer"]["ok"]
        and report["machine_profile"]["ok"]
        and report["process_profile"]["ok"] and report["filament_profile"]["ok"])
    # ready_to_print requires the authenticated channel to actually answer.
    pr = report["printer"]
    if pr["api_responds"]:
        channel_ok = True
    elif args.no_api_probe:
        # Told not to verify the live channel; the best proxy is a LOCAL open
        # port. A VPN-only route is never a usable print channel.
        channel_ok = pr["reachable"] and pr["network"] != "vpn"
    else:
        channel_ok = False
    report["ready_to_print"] = (
        report["ready_to_slice"] and report["library"]["ok"] and channel_ok)

    # Human summary -> stderr; JSON -> stdout
    def mark(ok: bool) -> str:
        return "✓" if ok else "✗"

    eprint("print-to-bambu preflight")
    eprint(f"  {mark(report['config']['ok'])} config: "
           f"{report['config']['path'] or report['config']['error']}")
    eprint(f"  {mark(report['slicer']['ok'])} slicer: "
           f"{report['slicer']['path'] or 'not found'} ({report['slicer']['kind']})")
    eprint(f"  {mark(report['machine_profile']['ok'])} machine profile: "
           f"{report['machine_profile']['name']}"
           f"{' — ' + report['machine_profile']['note'] if report['machine_profile']['note'] else ''}")
    for f in ("process_profile", "filament_profile"):
        label = f.replace("_", " ")
        eprint(f"  {mark(report[f]['ok'])} {label}: {report[f]['name']}"
               f"{' — ' + report[f]['note'] if report[f]['note'] else ''}")
    eprint(f"  {mark(report['library']['ok'])} bambulabs-api"
           f"{' — ' + report['library']['note'] if report['library']['note'] else ''}")
    pr = report["printer"]
    net = f" [{pr['network']} via {pr['interface']}]" if pr["interface"] else ""
    eprint(f"  {mark(pr['api_responds'])} printer {pr['ip']}{net} "
           f"(tcp {'up' if pr['reachable'] else 'down'}, "
           f"api {'ok' if pr['api_responds'] else 'no'})"
           f"{' — ' + pr['note'] if pr['note'] else ''}")
    eprint(f"  => ready_to_slice={report['ready_to_slice']} "
           f"ready_to_print={report['ready_to_print']}")

    print(json.dumps(report, indent=2))
    return 0 if report["ready_to_slice"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
