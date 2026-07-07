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


def _tray_loaded(printer, tray: int) -> bool:
    """True when the tray is at a nozzle, per legacy OR dual-nozzle fields.

    Single-nozzle firmware reports ams.tray_now. Dual-nozzle (X2D/H2) firmware
    also packs the loaded slot into device.extruder.info[*].snow as
    (ams_id << 8) | slot_id; 0xFFFF / 0xFEFF mean nothing loaded (255/254 are
    the external-spool virtual trays, slot 0xFF is none).
    """
    if str(_tray_now(printer)) == str(int(tray)):
        return True
    ams_id, slot_id = divmod(int(tray), 4)
    packed = (ams_id << 8) | slot_id
    d = _safe(printer.mqtt_dump) or {}
    infos = ((((d.get("print", {}) or {}).get("device") or {})
              .get("extruder") or {}).get("info") or [])
    return any(item.get("snow") == packed for item in infos)


def _ams_status(printer) -> int:
    d = _safe(printer.mqtt_dump) or {}
    try:
        return int((d.get("print", {}) or {}).get("ams_status") or 0)
    except (TypeError, ValueError):
        return 0


def load_ams_tray(printer, tray: int, temp: int = 220, timeout: float = 240.0,
                  refresh: bool = False) -> bool:
    """Load a specific AMS slot to the nozzle and wait until it's actually there.

    bambulabs-api's load_filament_spool() hardcodes target=255 (external spool),
    so we publish ams_change_filament ourselves. Dual-nozzle (X2D/H2) firmware
    SILENTLY IGNORES the legacy target-only form — it requires the explicit
    ams_id + slot_id fields Bambu Studio sends — so we always send the full
    Studio-style payload (old firmware ignores the extra keys and uses target).

    refresh=True re-runs the load even when the state says the tray is at the
    nozzle. The X2D's end-of-print sequence cuts + retracts the filament but
    can leave BOTH tray_now and extruder snow stale at "loaded" — trusting them
    across a job boundary printed a whole job with no filament. A refresh load
    on an actually-loaded slot is a quick cut/re-feed/purge (~1 min).

    The command gets no error when the firmware is in a busy window (e.g. right
    after an unload) — it is silently dropped — so we resend until the firmware
    visibly acts (tray_tar / ams_status), then wait for the flow to finish
    (tray at nozzle + filament-change flow idle). Returns True once loaded.
    """
    import time as _t
    if not refresh and _tray_loaded(printer, tray):
        return True  # already loaded (only trusted mid-session)
    ams_id, slot_id = divmod(int(tray), 4)
    payload = {"print": {"command": "ams_change_filament",
                         "ams_id": ams_id, "slot_id": slot_id,
                         "target": int(tray),
                         "curr_temp": int(temp), "tar_temp": int(temp)}}

    acked = False
    for _attempt in range(4):
        _publish(printer, payload)
        ack_deadline = _t.time() + 15
        while _t.time() < ack_deadline:
            d = _safe(printer.mqtt_dump) or {}
            ams = ((d.get("print", {}) or {}).get("ams", {}) or {})
            in_change = (_ams_status(printer) >> 8) == 1
            if str(ams.get("tray_tar")) == str(int(tray)) and \
                    (in_change or filament_change_busy(printer)):
                acked = True
                break
            _t.sleep(2)
        if acked:
            break
    if not acked:
        return False

    deadline = _t.time() + timeout
    while _t.time() < deadline:
        if _tray_loaded(printer, tray) \
                and (_ams_status(printer) >> 8) != 1 \
                and not filament_change_busy(printer):
            return True
        _t.sleep(3)
    return False


def filament_change_busy(printer) -> bool:
    """True while the firmware's filament-change flow is still active.

    device.extruder.state bit 19 is the busy-loading flag (Bambu Studio's
    ExtderSystemParser). A print start published while it is set is SILENTLY
    dropped by X2D/H2 firmware — no error reply, no state change.
    """
    d = _safe(printer.mqtt_dump) or {}
    st = (((d.get("print", {}) or {}).get("device") or {})
          .get("extruder") or {}).get("state")
    try:
        return bool((int(st) >> 19) & 1)
    except (TypeError, ValueError):
        return False


def wait_filament_change_done(printer, timeout: float = 90.0) -> bool:
    """Wait for the filament-change flow to finish after a load. True if idle."""
    import time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        if not filament_change_busy(printer):
            return True
        _t.sleep(2)
    return not filament_change_busy(printer)


def wait_print_started(printer, timeout: float = 120.0) -> str | None:
    """Wait for the firmware to actually act on a start command.

    X2D/H2 firmware takes ~30-40 s to process project_file and silently drops
    it in some states, so a successful MQTT publish means nothing. Returns the
    observed state: "RUNNING"/"PREPARE" on success, "FAILED" if the job errored
    immediately, None if nothing happened within the timeout (treat as NOT
    started).
    """
    import time as _t

    def _gs():
        d = _safe(printer.mqtt_dump) or {}
        return ((d.get("print", {}) or {}).get("gcode_state") or "").upper()

    # The previous job's terminal state (FINISH/FAILED) lingers until the new
    # job takes over — only a state that CHANGED counts as this job's outcome.
    stale = _gs()
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        gs = _gs()
        if gs in {"RUNNING", "PREPARE"}:
            return gs
        if gs == "FAILED" and gs != stale:
            return gs
        _t.sleep(3)
    return None


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
