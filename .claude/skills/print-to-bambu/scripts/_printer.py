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


def connect(cfg: dict, timeout: float = 20.0, wait_state: bool = True):
    """Open an MQTT connection to the printer and wait until it is usable.

    Uses mqtt_start() (not connect(), which also starts the camera). When
    wait_state is True, also waits (within the same timeout) for the printer's
    first populated status report, so the first read isn't an empty UNKNOWN
    snapshot. Returns a live Printer. Raises SystemExit on missing creds or if
    the MQTT channel never connects.
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
    connected = False
    while time.time() < deadline:
        try:
            if not connected and printer.mqtt_client_connected():
                connected = True
            if connected:
                if not wait_state:
                    return printer
                # Wait for the first real status push so reads aren't empty.
                if _safe(printer.get_state) is not None:
                    return printer
        except Exception:
            pass
        time.sleep(0.5)
    # Connected but no status populated in time: still usable for control
    # (upload/start); callers that need status will see UNKNOWN.
    if connected:
        return printer
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


def _raw_print(printer) -> dict:
    dump = _safe(printer.mqtt_dump) or {}
    return (dump.get("print", {}) or {})


def _decode_dual_temp(value):
    """Decode X2D/H2 packed extruder temp fields.

    Dual-nozzle firmware may report an active extruder temp as a 32-bit packed
    value: low 16 bits = current temp, high 16 bits = target temp. Inactive or
    legacy fields are usually plain Celsius floats/ints.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None, None
    if n > 1000:
        current = n & 0xFFFF
        target = (n >> 16) & 0xFFFF
        return current, target
    return n, None


def read_dual_extruders(printer) -> list[dict]:
    pr = _raw_print(printer)
    infos = (((pr.get("device") or {}).get("extruder") or {}).get("info") or [])
    out = []
    for item in infos:
        current, target = _decode_dual_temp(item.get("temp"))
        out.append({
            "id": item.get("id"),
            "temp": current,
            "target": target,
            "hnow": item.get("hnow"),
            "htar": item.get("htar"),
            "slot_now": item.get("snow"),
            "slot_target": item.get("star"),
        })
    return out


def read_status(printer) -> dict:
    """Snapshot the printer status, tolerating fields a model may not report."""
    pr = _raw_print(printer)
    state = _safe(printer.get_state)
    state_str = str(state) if state is not None else None
    if not state_str or state_str.upper() == "UNKNOWN":
        state_str = pr.get("gcode_state") or state_str

    dual_extruders = read_dual_extruders(printer)
    return {
        "state": state_str,
        "percent": _safe(printer.get_percentage) if pr.get("mc_percent") is None
        else pr.get("mc_percent"),
        "remaining_min": _safe(printer.get_time)
        if pr.get("mc_remaining_time") is None else pr.get("mc_remaining_time"),
        "layer": _safe(printer.current_layer_num) if pr.get("layer_num") is None
        else pr.get("layer_num"),
        "total_layers": _safe(printer.total_layer_num)
        if pr.get("total_layer_num") is None else pr.get("total_layer_num"),
        "nozzle_temp": _safe(printer.get_nozzle_temperature),
        "nozzle_target": pr.get("nozzle_target_temper"),
        "bed_temp": _safe(printer.get_bed_temperature)
        if pr.get("bed_temper") is None else pr.get("bed_temper"),
        "bed_target": pr.get("bed_target_temper"),
        "file": _safe(printer.get_file_name) or pr.get("gcode_file")
        or pr.get("subtask_name"),
        "dual_extruders": dual_extruders,
    }


def _to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def read_sources(printer, settle: float = 6.0) -> dict:
    """Snapshot the printer's filament SOURCES: AMS units/trays + external spool.

    This is what the parameter-confirmation gate reconciles against the config
    (use_ams / ams_tray) so we never start a print whose source is empty.
    """
    import time as _t
    deadline = _t.time() + settle
    ams_root = {}
    while _t.time() < deadline:
        dump = _safe(printer.mqtt_dump) or {}
        ams_root = (dump.get("print", {}) or {}).get("ams", {}) or {}
        if ams_root.get("ams"):
            break
        _t.sleep(0.5)

    units = []
    for ui, unit in enumerate(ams_root.get("ams", []) or []):
        unit_id = _to_int(unit.get("id"), ui)
        for t in unit.get("tray", []) or []:
            local = _to_int(t.get("id"), 0)
            ttype = (t.get("tray_type") or "").strip()
            units.append({
                "slot": unit_id * 4 + local,   # global AMS index used by ams_mapping
                "type": ttype,
                "color": (t.get("tray_color") or "").strip(),
                "empty": ttype == "",
            })

    vt = _safe(printer.vt_tray)
    ext_type = (getattr(vt, "tray_type", "") or "").strip() if vt is not None else ""
    return {
        "ams_present": bool(ams_root.get("ams")),
        "trays": units,
        "tray_now": _to_int(ams_root.get("tray_now")),  # 255 = nothing loaded
        "external_type": ext_type,
        "external_loaded": bool(ext_type),
    }


def _publish(printer, payload: dict) -> bool:
    """Publish a raw MQTT command (the library exposes no tray-specific load)."""
    mc = getattr(printer, "mqtt_client", None)
    fn = getattr(mc, "_PrinterMQTTClient__publish_command", None)
    if fn is None:
        raise RuntimeError("cannot access MQTT publish on this bambulabs-api build")
    return fn(payload)


def _tray_now(printer):
    d = _safe(printer.mqtt_dump) or {}
    return ((d.get("print", {}) or {}).get("ams", {}) or {}).get("tray_now")


def load_ams_tray(printer, tray: int, temp: int = 220, timeout: float = 150.0) -> bool:
    """Load a specific AMS slot to the nozzle and wait until it's actually there.

    bambulabs-api's load_filament_spool() hardcodes target=255 (external spool),
    so we send ams_change_filament with the real tray index. A print started with
    use_ams + ams_mapping does NOT reliably trigger this load on its own (the
    printer leaves tray_now=255 and prints dry), so we pre-load explicitly and
    confirm tray_now == tray before printing. Returns True once loaded.
    """
    import time as _t
    if str(_tray_now(printer)) == str(int(tray)):
        return True  # already loaded
    _publish(printer, {"print": {"command": "ams_change_filament",
                                 "target": int(tray),
                                 "curr_temp": int(temp), "tar_temp": int(temp)}})
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        if str(_tray_now(printer)) == str(int(tray)):
            return True
        _t.sleep(3)
    return False


def start_project_file(printer, payload: dict) -> bool:
    """Start a 3MF project with an explicit MQTT project_file payload.

    bambulabs-api's start_print_3mf() uses a legacy payload that is not rich
    enough for newer dual-nozzle families. Keep the raw publish isolated here so
    send.py can build model-specific payloads without reaching into private API
    methods itself.
    """
    return _publish(printer, {"print": payload})


def disconnect(printer) -> None:
    try:
        printer.disconnect()
    except Exception:
        pass
