#!/usr/bin/env python3
"""Check (and optionally install) the small set of libraries this skill needs.

Modern macOS/Linux Python installs (Homebrew, apt) are often "externally
managed" (PEP 668) and refuse a plain `pip install --user`. Rather than fail
there, this script falls back to a private virtual environment under
~/.school-calendar/.venv — that's always writable and never "externally
managed", so it works regardless of how the user's system Python is set up.

Once a working interpreter is found (system Python, or the private venv), its
path is cached in ~/.school-calendar/environment.json so future runs (and
every other script in this skill) reuse it directly instead of re-probing
pip every time.

Usage:
    python3 check_dependencies.py              # just report
    python3 check_dependencies.py --install     # install anything missing, then report

Output JSON always includes "python_interpreter" — the path SKILL.md should
use to invoke every other script in this skill for the rest of the session.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

# import-name -> pip-package-name
PACKAGES = {
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "dateutil": "python-dateutil",
    "pypdf": "pypdf",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
}

ENV_ROOT = Path(os.environ.get("SCHOOL_CALENDAR_HOME") or os.path.expanduser("~/.school-calendar"))
ENV_FILE = ENV_ROOT / "environment.json"
VENV_DIR = ENV_ROOT / ".venv"


def _check_with_interpreter(python_path: str) -> dict:
    """Run a tiny import-check script under the given interpreter."""
    probe = (
        "import importlib, json; "
        f"mods = {list(PACKAGES.keys())!r}; "
        "out = {}\n"
        "for m in mods:\n"
        "    try:\n"
        "        importlib.import_module(m)\n"
        "        out[m] = True\n"
        "    except ImportError:\n"
        "        out[m] = False\n"
        "print(json.dumps(out))"
    )
    try:
        result = subprocess.run(
            [python_path, "-c", probe], capture_output=True, text=True, timeout=30
        )
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        return {m: False for m in PACKAGES}


def _all_ok(status: dict) -> bool:
    return all(status.get(m) for m in PACKAGES)


def _pip_install(python_path: str, modules: list[str], user: bool = True) -> subprocess.CompletedProcess:
    pip_names = [PACKAGES[m] for m in modules]
    cmd = [python_path, "-m", "pip", "install"]
    if user:
        cmd.append("--user")  # venvs reject --user outright (already isolated)
    cmd.extend(pip_names)
    return subprocess.run(cmd, capture_output=True, text=True)


def _ensure_venv() -> str:
    venv_python = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
    if not venv_python.exists():
        # --system-site-packages: inherit whatever's already importable on the
        # system Python (e.g. requests/bs4 may already be installed there),
        # so the venv only needs to supply what the system pip refused to.
        venv.EnvBuilder(with_pip=True, clear=False, system_site_packages=True).create(str(VENV_DIR))
    return str(venv_python)


def _save_environment(python_path: str, status: dict) -> None:
    ENV_ROOT.mkdir(parents=True, exist_ok=True)
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        json.dump({"python_interpreter": python_path, "last_check": status}, f, indent=2)


def _cached_interpreter() -> str | None:
    if not ENV_FILE.exists():
        return None
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        candidate = data.get("python_interpreter")
        if candidate and Path(candidate).exists():
            return candidate
    except (json.JSONDecodeError, OSError):
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true", help="Install missing packages, falling back to a private venv if the system Python refuses (PEP 668)")
    args = parser.parse_args()

    # Prefer a previously-resolved interpreter (e.g. an already-created venv)
    # over re-probing sys.executable, so we don't flip-flop between system
    # Python and the venv across separate runs.
    python_path = _cached_interpreter() or sys.executable
    status = _check_with_interpreter(python_path)

    if _all_ok(status):
        _save_environment(python_path, status)
        print(json.dumps({**status, "python_interpreter": python_path, "install_attempted": False}, indent=2))
        return

    if not args.install:
        missing = [m for m, ok in status.items() if not ok]
        print(json.dumps({
            **status,
            "python_interpreter": python_path,
            "install_attempted": False,
            "missing": missing,
        }, indent=2))
        return

    missing = [m for m, ok in status.items() if not ok]
    attempt_log = []

    # Attempt 1: plain --user install on whichever interpreter we started with.
    result = _pip_install(python_path, missing)
    attempt_log.append({"interpreter": python_path, "returncode": result.returncode})
    status = _check_with_interpreter(python_path)

    # Attempt 2: system pip refused (PEP 668 externally-managed-environment,
    # or any other reason) -> fall back to a private venv, which is always
    # writable and never externally managed.
    if not _all_ok(status):
        venv_python = _ensure_venv()
        still_missing = [m for m, ok in status.items() if not ok]
        result = _pip_install(venv_python, still_missing, user=False)
        attempt_log.append({"interpreter": venv_python, "returncode": result.returncode})
        venv_status = _check_with_interpreter(venv_python)
        if _all_ok(venv_status):
            python_path = venv_python
            status = venv_status

    _save_environment(python_path, status)
    output = {
        **status,
        "python_interpreter": python_path,
        "install_attempted": True,
        "attempts": attempt_log,
        "still_missing": [m for m, ok in status.items() if not ok],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
