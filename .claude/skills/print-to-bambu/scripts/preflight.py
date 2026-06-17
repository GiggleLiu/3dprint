#!/usr/bin/env python3
"""Readiness checks for the print-to-bambu skill.

Emits a JSON report on stdout and a human-readable summary on stderr. Checks:
config present/valid, slicer found, machine profile exists in that slicer,
bambulabs-api importable, printer reachable on the network.

Exit code: 0 if ready to slice, 1 otherwise. (Printing also needs the library +
a reachable printer + Developer Mode; see `ready_to_print` in the JSON.)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import (  # noqa: E402
    eprint, find_slicer, load_config, machine_profile_exists, preset_json_path,
)

MQTT_TLS_PORT = 8883


def tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    args = ap.parse_args()

    report: dict = {
        "config": {"ok": False, "path": None, "error": None},
        "slicer": {"ok": False, "path": None, "kind": "unknown"},
        "machine_profile": {"ok": False, "name": None, "note": ""},
        "process_profile": {"ok": False, "name": None},
        "filament_profile": {"ok": False, "name": None},
        "library": {"ok": False, "note": ""},
        "printer": {"reachable": False, "ip": None, "note": ""},
        "ready_to_slice": False,
        "ready_to_print": False,
    }

    cfg = None
    try:
        cfg = load_config(args.config)
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
            for key, field in (("machine", "machine_profile"),
                               ("process", "process_profile"),
                               ("filament", "filament_profile")):
                name = sl.get(key)
                report[field]["name"] = name
                kind_dir = {"machine": "machine", "process": "process",
                            "filament": "filament"}[key]
                report[field]["ok"] = bool(
                    name and preset_json_path(slicer_path, kind_dir, name))
            if report["machine_profile"]["name"] and not report["machine_profile"]["ok"]:
                report["machine_profile"]["note"] = (
                    f"'{report['machine_profile']['name']}' not found in this slicer. "
                    "Update the slicer (X2D needs a 2026+ build) or fix the name.")

    # Library
    report["library"]["ok"] = importlib.util.find_spec("bambulabs_api") is not None
    if not report["library"]["ok"]:
        report["library"]["note"] = (
            "pip install -r .claude/skills/print-to-bambu/requirements.txt")

    # Printer reachability
    if cfg is not None:
        ip = cfg.get("printer", {}).get("ip")
        report["printer"]["ip"] = ip
        if ip and not ip.startswith("192.168.x"):
            report["printer"]["reachable"] = tcp_reachable(ip, MQTT_TLS_PORT)
        if not report["printer"]["reachable"]:
            report["printer"]["note"] = (
                "No TCP connect on :8883 — printer off, wrong IP, or different subnet.")

    report["ready_to_slice"] = (
        report["config"]["ok"] and report["slicer"]["ok"]
        and report["machine_profile"]["ok"])
    report["ready_to_print"] = (
        report["ready_to_slice"] and report["library"]["ok"]
        and report["printer"]["reachable"])

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
    eprint(f"  {mark(report['process_profile']['ok'])} process profile: "
           f"{report['process_profile']['name']}")
    eprint(f"  {mark(report['filament_profile']['ok'])} filament profile: "
           f"{report['filament_profile']['name']}")
    eprint(f"  {mark(report['library']['ok'])} bambulabs-api"
           f"{' — ' + report['library']['note'] if report['library']['note'] else ''}")
    eprint(f"  {mark(report['printer']['reachable'])} printer {report['printer']['ip']}"
           f"{' — ' + report['printer']['note'] if report['printer']['note'] else ''}")
    eprint(f"  => ready_to_slice={report['ready_to_slice']} "
           f"ready_to_print={report['ready_to_print']}")

    print(json.dumps(report, indent=2))
    return 0 if report["ready_to_slice"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
