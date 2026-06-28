#!/usr/bin/env python3
"""Switch the active Bambu printer profile (multi-printer support).

All the other print-to-bambu scripts read a single `bambu.toml`. This helper lets
you keep several `bambu.<name>.toml` profiles side by side (e.g. `bambu.p1s.toml`,
`bambu.x2d.toml`) and choose which one is active by copying it onto `bambu.toml`.

Usage:
  use_printer.py                 # list profiles + live network status (no change)
  use_printer.py --list          # same as above
  use_printer.py <name>          # activate bambu.<name>.toml  (e.g. `use_printer.py p1s`)
  use_printer.py --auto          # auto-pick the profile reachable on the LOCAL network
                                 #   (a printer routed over a physical interface, not a VPN tunnel)

Human summary on stderr, JSON on stdout. Never starts a print; only swaps configs.
"""
from __future__ import annotations

import json
import shutil
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import eprint, locality, route_iface, tcp_open  # noqa: E402

CONFIG_NAME = "bambu.toml"


def find_root() -> Path:
    """Walk up from cwd to the first dir holding bambu.toml or a bambu.<name>.toml."""
    cur = Path.cwd().resolve()
    for d in [cur, *cur.parents]:
        if (d / CONFIG_NAME).is_file() or list(d.glob("bambu.*.toml")):
            return d
    return cur


def discover_profiles(root: Path) -> dict[str, Path]:
    """Map profile name -> path for every bambu.<name>.toml (excludes the example)."""
    out = {}
    for p in sorted(root.glob("bambu.*.toml")):
        if p.name == "bambu.toml.example":
            continue
        name = p.name[len("bambu."):-len(".toml")]
        out[name] = p
    return out


def read_printer(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception as e:
        return {"error": str(e)}
    pr = data.get("printer", {}) or {}
    sl = data.get("slice", {}) or {}
    return {"ip": pr.get("ip"), "serial": pr.get("serial"), "machine": sl.get("machine")}


def active_name(root: Path, profiles: dict[str, Path]) -> str | None:
    """Which profile bambu.toml currently mirrors (matched by ip+serial)."""
    active = root / CONFIG_NAME
    if not active.is_file():
        return None
    cur = read_printer(active)
    for name, path in profiles.items():
        info = read_printer(path)
        if info.get("ip") == cur.get("ip") and info.get("serial") == cur.get("serial"):
            return name
    return None


def status_rows(profiles: dict[str, Path], active: str | None) -> list[dict]:
    rows = []
    for name, path in profiles.items():
        info = read_printer(path)
        ip = info.get("ip")
        iface = route_iface(ip)
        loc = locality(iface)
        reachable = tcp_open(ip)
        rows.append({
            "name": name,
            "active": name == active,
            "ip": ip,
            "machine": info.get("machine"),
            "interface": iface,
            "network": loc,
            "reachable": reachable,
            "local_and_reachable": reachable and loc == "lan",
        })
    return rows


def print_table(rows: list[dict]):
    eprint("Bambu printer profiles:")
    for r in rows:
        mark = "*" if r["active"] else " "
        net = r["network"]
        via = f"{net} via {r['interface']}" if r["interface"] else net
        reach = "reachable" if r["reachable"] else "unreachable"
        flag = "  <- LOCAL" if r["local_and_reachable"] else ""
        eprint(f"  {mark} {r['name']:<6} {str(r['machine'] or '?'):<26} "
               f"{str(r['ip'] or '?'):<15} [{via}, {reach}]{flag}")
    eprint("  (* = active)")


def activate(root: Path, profiles: dict[str, Path], name: str) -> dict:
    if name not in profiles:
        raise SystemExit(
            f"✗ No profile '{name}'. Available: {', '.join(profiles) or '(none)'}")
    src = profiles[name]
    dst = root / CONFIG_NAME
    shutil.copyfile(src, dst)
    info = read_printer(dst)
    eprint(f"✓ Activated '{name}' -> {CONFIG_NAME}  ({info.get('machine')} @ {info.get('ip')})")
    return {"activated": name, "ip": info.get("ip"), "machine": info.get("machine")}


def auto_pick(root: Path, profiles: dict[str, Path], rows: list[dict]) -> dict:
    local = [r for r in rows if r["local_and_reachable"]]
    if len(local) == 1:
        eprint(f"Auto: '{local[0]['name']}' is the only printer on the local network.")
        return activate(root, profiles, local[0]["name"])
    if len(local) > 1:
        print_table(rows)
        raise SystemExit(
            "✗ Auto is ambiguous: more than one printer is local. "
            f"Pick one explicitly: {', '.join(r['name'] for r in local)}")
    # No local printer; fall back only if exactly one is reachable at all.
    reachable = [r for r in rows if r["reachable"]]
    if len(reachable) == 1:
        eprint(f"Auto: no on-LAN printer; '{reachable[0]['name']}' is the only "
               "reachable one (note: via VPN/tunnel).")
        return activate(root, profiles, reachable[0]["name"])
    print_table(rows)
    raise SystemExit(
        "✗ Auto could not decide (no single local/reachable printer). Pick one explicitly.")


def main(argv: list[str]) -> int:
    root = find_root()
    profiles = discover_profiles(root)
    if not profiles:
        eprint(f"No bambu.<name>.toml profiles found in {root}.")
        print(json.dumps({"profiles": [], "root": str(root)}))
        return 1

    arg = argv[1] if len(argv) > 1 else "--list"
    active = active_name(root, profiles)

    if arg in ("--list", "-l", "list"):
        rows = status_rows(profiles, active)
        print_table(rows)
        print(json.dumps({"active": active, "profiles": rows}, indent=2))
        return 0

    if arg in ("--auto", "-a", "auto"):
        rows = status_rows(profiles, active)
        result = auto_pick(root, profiles, rows)
        print(json.dumps(result, indent=2))
        return 0

    name = arg.lstrip("-")
    result = activate(root, profiles, name)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
