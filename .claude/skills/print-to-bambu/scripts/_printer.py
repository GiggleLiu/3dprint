"""Shared LAN-printer helpers (bambulabs-api) for send.py and monitor.py.

bambulabs-api is imported lazily so the slicing path never needs it installed.
"""
from __future__ import annotations

import time
from pathlib import Path

REQ_HINT = "pip install -r .claude/skills/print-to-bambu/requirements.txt"


def load_api():
    try:
        import bambulabs_api as bl  # noqa
        return bl
    except ImportError as e:
        raise SystemExit(f"✗ bambulabs-api not installed ({e}).\n  {REQ_HINT}")


def connect(cfg: dict, timeout: float = 20.0):
    """Open an MQTT connection to the printer and wait until it is connected.

    Uses mqtt_start() (not connect(), which also starts the camera). Returns a
    live Printer. Raises SystemExit on missing creds or connection timeout.
    """
    bl = load_api()
    printer_cfg = cfg.get("printer", {})
    ip = printer_cfg.get("ip")
    serial = printer_cfg.get("serial")
    code = cfg.get("access_code", "")
    if not code:
        raise SystemExit(
            "✗ No LAN access code. Set BAMBU_ACCESS_CODE or [printer].access_code.")

    printer = bl.Printer(ip, code, serial)
    printer.mqtt_start()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if printer.mqtt_client_connected():
                return printer
        except Exception:
            pass
        time.sleep(0.5)
    try:
        printer.disconnect()
    except Exception:
        pass
    raise SystemExit(
        f"✗ Could not connect to {ip} within {timeout:.0f}s. "
        "Check IP/serial/access code, that the printer is on, and LAN/Developer Mode.")


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def read_status(printer) -> dict:
    """Snapshot the printer status, tolerating fields a model may not report."""
    state = _safe(printer.get_state)
    return {
        "state": str(state) if state is not None else None,
        "percent": _safe(printer.get_percentage),
        "remaining_min": _safe(printer.get_time),
        "layer": _safe(printer.current_layer_num),
        "total_layers": _safe(printer.total_layer_num),
        "nozzle_temp": _safe(printer.get_nozzle_temperature),
        "bed_temp": _safe(printer.get_bed_temperature),
        "file": _safe(printer.get_file_name),
    }


def disconnect(printer) -> None:
    try:
        printer.disconnect()
    except Exception:
        pass
