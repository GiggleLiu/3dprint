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


def fmt(status: dict) -> str:
    pct = status.get("percent")
    rem = status.get("remaining_min")
    layer, total = status.get("layer"), status.get("total_layers")
    return (f"{status.get('state'):<8} "
            f"{pct if pct is not None else '?'}%  "
            f"layer {layer if layer is not None else '?'}/{total if total is not None else '?'}  "
            f"~{rem if rem is not None else '?'} min left  "
            f"nozzle {status.get('nozzle_temp')}C bed {status.get('bed_temp')}C  "
            f"[{status.get('file') or '-'}]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="path to bambu.toml (default: search upward)")
    ap.add_argument("--interval", type=float, default=4.0, help="poll seconds")
    ap.add_argument("--once", action="store_true", help="print one status and exit")
    ap.add_argument("--timeout-min", type=float, default=0,
                    help="give up after N minutes (0 = no limit)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    printer = connect(cfg)
    seen_running = False
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
