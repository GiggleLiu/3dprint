#!/usr/bin/env python3
"""Check — and, if missing, set up — the Python environment for these skills.

Run this with the **system** python3: it bootstraps the project virtualenv, so it
has to work *before* `.venv` exists and therefore uses only the standard library.

It verifies, in order, and fixes what it can:
  1. Python is new enough (>= 3.11, for the stdlib `tomllib` the slicer path uses).
     It can create a venv and pip-install packages, but it cannot install Python
     itself — if yours is older, it says so and stops.
  2. A project virtualenv (`.venv`) exists — it creates one if not.
  3. The required packages import inside that venv — it pip-installs them if not.

Scope: by default it sets up the PRINTING deps (bambulabs-api). Add --with-design
to also set up the design-stl deps (trimesh, …). With --check it only reports and
changes nothing (exit 1 if anything required is missing).

Human summary -> stderr, JSON -> stdout. Exit 0 when everything required is present.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MIN_PY = (3, 11)

GROUPS = {
    "print": {
        "req": ".claude/skills/print-to-bambu/requirements.txt",
        "modules": ["bambulabs_api"],
    },
    "design": {
        "req": ".claude/skills/design-stl/requirements.txt",
        "modules": ["trimesh", "manifold3d", "matplotlib", "scipy", "rtree", "networkx"],
    },
}


def eprint(*a):
    print(*a, file=sys.stderr)


def find_root() -> Path:
    """Repo root = the nearest ancestor containing `.claude` (works from any cwd)."""
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / ".claude").is_dir():
            return p
    return Path.cwd()


def venv_python(root: Path) -> Path:
    win = root / ".venv" / "Scripts" / "python.exe"
    return win if win.exists() else root / ".venv" / "bin" / "python"


def interp_version(interp: Path) -> tuple[tuple[int, ...], str]:
    """(version_tuple, version_str) for an interpreter, or ((0,0,0), '?')."""
    try:
        out = subprocess.run(
            [str(interp), "-c",
             "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
            capture_output=True, text=True, timeout=20)
        s = out.stdout.strip()
        return tuple(int(x) for x in s.split(".")[:3]), s
    except Exception:
        return (0, 0, 0), "?"


def probe(py: Path, modules: list[str]) -> list[str]:
    """Return the modules that are NOT importable under the given interpreter."""
    if not py.exists():
        return list(modules)
    code = ("import importlib.util, json, sys;"
            "print(json.dumps([m for m in sys.argv[1:]"
            " if importlib.util.find_spec(m) is None]))")
    try:
        out = subprocess.run([str(py), "-c", code, *modules],
                             capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout.strip() or "[]")
    except Exception:
        return list(modules)


def pip_install(py: Path, req: Path) -> tuple[bool, str]:
    if not req.is_file():
        return False, f"requirements file not found: {req}"
    try:
        out = subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(req)],
                             capture_output=True, text=True)
        if out.returncode == 0:
            return True, ""
        tail = (out.stderr or out.stdout).strip().splitlines()
        return False, tail[-1] if tail else "pip install failed"
    except Exception as e:
        return False, str(e)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-design", action="store_true",
                    help="also set up the design-stl deps (trimesh, …)")
    ap.add_argument("--check", action="store_true",
                    help="report only; make no changes (exit 1 if anything missing)")
    args = ap.parse_args()

    root = find_root()
    venv_dir = root / ".venv"
    py = venv_python(root)
    groups = ["print"] + (["design"] if args.with_design else [])
    report: dict = {"root": str(root), "python": {}, "venv": {},
                    "groups": {}, "changed": [], "ok": False}

    eprint("environment check/setup")

    # 1. Python version — judge the venv's interpreter if it exists, else this one.
    if venv_dir.exists():
        ver, vers = interp_version(py)
        src = ".venv"
    else:
        ver, vers = tuple(sys.version_info[:3]), \
            ".".join(map(str, sys.version_info[:3]))
        src = "python3"
    pyok = tuple(ver) >= MIN_PY
    report["python"] = {"ok": pyok, "version": vers,
                        "required": ".".join(map(str, MIN_PY)), "source": src}
    eprint(f"  {'✓' if pyok else '✗'} python {vers} ({src}; need "
           f">= {report['python']['required']})")
    if not pyok:
        eprint("    → install Python 3.11+ and re-run with it; can't auto-install "
               "Python.")

    # 2. venv — create if missing (needs a new-enough bootstrap python).
    if venv_dir.exists():
        report["venv"] = {"ok": True, "created": False, "path": str(venv_dir)}
        eprint(f"  ✓ venv: {venv_dir}")
    elif args.check:
        report["venv"] = {"ok": False, "created": False, "path": str(venv_dir)}
        eprint(f"  ✗ venv: missing ({venv_dir})")
    elif not pyok:
        report["venv"] = {"ok": False, "created": False, "path": str(venv_dir)}
        eprint(f"  ✗ venv: not creating one from Python {vers}; install 3.11+ first.")
    else:
        eprint(f"  • creating venv at {venv_dir} ...")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)],
                           check=True, capture_output=True, text=True)
            py = venv_python(root)
            report["venv"] = {"ok": True, "created": True, "path": str(venv_dir)}
            report["changed"].append("created .venv")
            eprint(f"  ✓ venv: {venv_dir} (created)")
        except Exception as e:
            report["venv"] = {"ok": False, "created": False, "path": str(venv_dir),
                              "error": str(e)}
            eprint(f"  ✗ venv: could not create ({e})")

    # 3. per-group dependencies
    for g in groups:
        spec = GROUPS[g]
        missing = probe(py, spec["modules"])
        info: dict = {"required_modules": spec["modules"], "missing": missing,
                      "installed": False, "ok": not missing}
        if not missing:
            eprint(f"  ✓ {g} deps: all present")
        elif args.check:
            eprint(f"  ✗ {g} deps: missing {', '.join(missing)}")
        elif report["venv"].get("ok"):
            eprint(f"  • installing {g} deps (missing {', '.join(missing)}; "
                   "may take a minute) ...")
            ok, err = pip_install(py, root / spec["req"])
            missing = probe(py, spec["modules"])
            info["missing"], info["installed"], info["ok"] = missing, ok, not missing
            if not missing:
                report["changed"].append(f"installed {g} deps")
                eprint(f"  ✓ {g} deps: installed")
            else:
                if err:
                    info["error"] = err
                eprint(f"  ✗ {g} deps: still missing {', '.join(missing)}"
                       f"{' — ' + err if err else ''}")
        else:
            eprint(f"  ✗ {g} deps: skipped (no usable venv)")
        report["groups"][g] = info

    report["ok"] = (report["python"]["ok"] and report["venv"].get("ok", False)
                    and all(report["groups"][g]["ok"] for g in groups))
    eprint(f"  => environment {'ready' if report['ok'] else 'NOT ready'}"
           + (f" — changed: {'; '.join(report['changed'])}" if report["changed"] else ""))
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
