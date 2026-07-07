#!/usr/bin/env python3
"""Monitor a Bambu print over LAN: stream progress until it finishes or fails.

Monitoring (status push over MQTT) is NOT gated by Authorization Control, so this
works whether or not Developer Mode is on. Ctrl-C disconnects cleanly.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import eprint, load_config  # noqa: E402
from _printer import connect, disconnect, read_status  # noqa: E402

TERMINAL = {"FINISH", "FAILED"}


def fmt_extruders(status: dict) -> str:
    parts = []
    for ex in status.get("dual_extruders") or []:
        if ex.get("temp") is None:
            continue
        target = ex.get("target")
        if target is not None:
            parts.append(f"E{ex.get('id')} {ex.get('temp')}->{target}C")
        else:
            parts.append(f"E{ex.get('id')} {ex.get('temp')}C")
    return " ".join(parts)


def fmt(status: dict) -> str:
    pct = status.get("percent")
    rem = status.get("remaining_min")
    layer, total = status.get("layer"), status.get("total_layers")
    extruders = fmt_extruders(status)
    nozzle = (extruders or
              f"nozzle {status.get('nozzle_temp')}C"
              f"{'->' + str(status.get('nozzle_target')) + 'C' if status.get('nozzle_target') is not None else ''}")
    return (f"{status.get('state'):<8} "
            f"{pct if pct is not None else '?'}%  "
            f"layer {layer if layer is not None else '?'}/{total if total is not None else '?'}  "
            f"~{rem if rem is not None else '?'} min left  "
            f"{nozzle} bed {status.get('bed_temp')}C  "
            f"[{status.get('file') or '-'}]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    ap.add_argument("--printer", help="use the bambu.<name>.toml profile")
    ap.add_argument("--interval", type=float, default=4.0, help="poll seconds")
    ap.add_argument("--once", action="store_true", help="print one status and exit")
    ap.add_argument("--timeout-min", type=float, default=0,
                    help="give up after N minutes (0 = no limit)")
    args = ap.parse_args()

    cfg = load_config(args.config, printer=args.printer)
    printer = connect(cfg)
    seen_running = False
    stale_terminal = None   # terminal state already present at startup (old job)
    first_meaningful = True
    start = time.time()
    rc = 0
    try:
        while True:
            status = read_status(printer)
            eprint(fmt(status))
            state = (status.get("state") or "").upper()
            if state == "RUNNING":
                seen_running = True
            if args.once:
                break
            # A terminal state that is already there on the FIRST meaningful read
            # belongs to the PREVIOUS job (send.py starts a print while the printer
            # still reports the old FINISH). Don't declare victory on it — wait for
            # the state to change, then resume normal termination logic.
            if first_meaningful and state and state != "UNKNOWN":
                first_meaningful = False
                if state in TERMINAL:
                    stale_terminal = state
                    eprint(f"• Printer still reports {state} from a previous job — "
                           "waiting for the new job to start (use --once for a "
                           "snapshot).")
            if stale_terminal:
                if state == stale_terminal:
                    if args.timeout_min and (time.time() - start) > args.timeout_min * 60:
                        eprint(f"• Monitor timed out after {args.timeout_min} min.")
                        break
                    time.sleep(args.interval)
                    continue
                stale_terminal = None
            if state == "FINISH":
                eprint("✓ Print finished.")
                break
            if state == "FAILED":
                eprint("✗ Print failed.")
                rc = 1
                break
            if seen_running and state == "IDLE":
                eprint("• Printer returned to idle.")
                break
            if args.timeout_min and (time.time() - start) > args.timeout_min * 60:
                eprint(f"• Monitor timed out after {args.timeout_min} min.")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        eprint("\n• Stopped monitoring (print continues on the printer).")
    finally:
        disconnect(printer)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
