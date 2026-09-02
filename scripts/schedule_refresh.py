#!/usr/bin/env python3
"""Set up, change, cancel, or list the automatic refresh check for one school.

Runs locally via crontab (macOS/Linux) or Task Scheduler (Windows) - chosen
over a cloud-based scheduler because it needs durable read/write access to
this school's ~/.school-calendar/<slug>/config.json to do the actual
compare-and-report work; a cloud sandbox that resets between runs can't do
that (confirmed against this project's own leftover scheduled-task files,
which had to hardcode everything as plain text for exactly this reason).

Each scheduled run simply invokes `claude -p ">refresh <slug>"` - the
`>refresh` chevron command already knows how to re-scrape, diff, and report;
this script's only job is registering that command to fire on a chosen
cadence, without disturbing any of the user's other crontab entries or
scheduled tasks.

Cadence options:
    termly    - beginning of each UK school term: 1 Sep, 1 Jan, 1 Apr (3x/year,
                aligned to when schools actually publish/revise term dates -
                deliberately NOT called "quarterly", since it's neither four
                times a year nor evenly spaced; the name should say what it does)
    monthly   - beginning of every month
    (cancel via --remove)

Usage:
    python3 schedule_refresh.py --school-slug <slug> --cadence termly|monthly
    python3 schedule_refresh.py --school-slug <slug> --remove
    python3 schedule_refresh.py --list [--school-slug <slug>]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

MARKER_PREFIX = "school-calendar-refresh"

MONTH_NAMES = {
    1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may", 6: "jun",
    7: "jul", 8: "aug", 9: "sep", 10: "oct", 11: "nov", 12: "dec",
}
WINDOWS_MONTHS = {v: v.upper() for v in MONTH_NAMES.values()}

CADENCES = {
    "termly": [9, 1, 4],
    "monthly": list(range(1, 13)),
}


def _claude_path() -> str:
    return shutil.which("claude") or "claude"


def _marker(school_slug: str, cadence: str, tag: str) -> str:
    return f"# {MARKER_PREFIX}:{school_slug}:{cadence}:{tag}"


def _school_marker_substring(school_slug: str) -> str:
    return f"{MARKER_PREFIX}:{school_slug}:"


def _config_home() -> str:
    return os.environ.get("SCHOOL_CALENDAR_HOME") or os.path.expanduser("~/.school-calendar")


def _cron_line(school_slug: str, cadence: str, month: int) -> str:
    claude = _claude_path()
    tag = MONTH_NAMES[month]
    log_path = os.path.join(_config_home(), school_slug, "refresh-log.txt")
    return (
        f'0 9 1 {month} * {claude} -p ">refresh {school_slug}" '
        f">> {log_path} 2>&1 {_marker(school_slug, cadence, tag)}"
    )


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return ""  # no crontab yet - not an error
    return result.stdout


def setup_cron(school_slug: str, cadence: str) -> dict:
    if cadence not in CADENCES:
        return {"success": False, "error": f"Unknown cadence '{cadence}', expected one of {list(CADENCES)}"}

    existing_lines = _current_crontab().splitlines()
    marker_substr = _school_marker_substring(school_slug)
    kept_lines = [line for line in existing_lines if marker_substr not in line]
    new_lines = [_cron_line(school_slug, cadence, month) for month in CADENCES[cadence]]
    updated = kept_lines + new_lines

    proc = subprocess.run(["crontab", "-"], input="\n".join(updated) + "\n", text=True, capture_output=True)
    return {
        "mechanism": "cron",
        "success": proc.returncode == 0,
        "cadence": cadence,
        "entries_added": new_lines,
        "stderr": proc.stderr if proc.returncode != 0 else "",
    }


def remove_cron(school_slug: str) -> dict:
    existing_lines = _current_crontab().splitlines()
    marker_substr = _school_marker_substring(school_slug)
    kept_lines = [line for line in existing_lines if marker_substr not in line]
    removed_count = len(existing_lines) - len(kept_lines)
    proc = subprocess.run(["crontab", "-"], input="\n".join(kept_lines) + ("\n" if kept_lines else ""), text=True, capture_output=True)
    return {
        "mechanism": "cron",
        "success": proc.returncode == 0,
        "entries_removed": removed_count,
        "stderr": proc.stderr if proc.returncode != 0 else "",
    }


def list_cron(school_slug: str | None) -> dict:
    existing_lines = _current_crontab().splitlines()
    pattern = re.compile(rf"# {re.escape(MARKER_PREFIX)}:([^:]+):([^:]+):([^\s]+)")
    schools: dict[str, dict] = {}
    for line in existing_lines:
        m = pattern.search(line)
        if not m:
            continue
        slug, cadence, tag = m.group(1), m.group(2), m.group(3)
        if school_slug and slug != school_slug:
            continue
        fields = line.split()
        cron_time = f"{fields[1]}:00 on day {fields[2]} of month {fields[3]}" if len(fields) >= 4 else line
        entry = schools.setdefault(slug, {"school_slug": slug, "cadence": cadence, "runs": []})
        entry["runs"].append({"tag": tag, "schedule": cron_time})
    return {"mechanism": "cron", "schools": list(schools.values())}


# --- launchd (macOS) ---------------------------------------------------
#
# Plain crontab has no wake-catchup: a job scheduled for a minute the Mac
# was asleep simply never fires, with no retry (confirmed against this
# project's own missed 1 Sep termly refresh). launchd's StartCalendarInterval
# fires a missed calendar-time job once, shortly after the machine next
# wakes/logs in - so this is the macOS-only replacement for cron below.
# Linux stays on cron (list_cron/setup_cron/remove_cron above), Windows
# stays on schtasks (below) - both untouched.

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def _uid() -> str:
    return str(os.getuid())


def _agent_label(school_slug: str) -> str:
    return f"com.school-calendar.refresh.{school_slug}"


def _plist_path(school_slug: str) -> Path:
    return LAUNCH_AGENTS_DIR / f"{_agent_label(school_slug)}.plist"


def _calendar_intervals(cadence: str) -> list[dict]:
    if cadence == "termly":
        return [{"Month": m, "Day": 1, "Hour": 9, "Minute": 0} for m in CADENCES["termly"]]
    return [{"Day": 1, "Hour": 9, "Minute": 0}]


def _cached_python_interpreter() -> str | None:
    env_file = Path(_config_home()) / "environment.json"
    if not env_file.exists():
        return None
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("python_interpreter")
    except (json.JSONDecodeError, OSError):
        return None


def _env_path_value(claude: str) -> str:
    """launchd agents get a much sparser PATH than a login shell - build one
    wide enough to cover the claude binary, the skill's resolved Python
    interpreter, and the usual Homebrew/system bin dirs.
    """
    dirs = []
    claude_dir = os.path.dirname(claude)
    if claude_dir:
        dirs.append(claude_dir)
    cached_python = _cached_python_interpreter()
    if cached_python:
        python_dir = os.path.dirname(cached_python)
        if python_dir:
            dirs.append(python_dir)
    dirs.extend([
        "/usr/local/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin",
        "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    ])
    seen: list[str] = []
    for d in dirs:
        if d and d not in seen:
            seen.append(d)
    return ":".join(seen)


def _build_plist(school_slug: str, cadence: str) -> dict:
    claude = _claude_path()
    log_path = os.path.join(_config_home(), school_slug, "refresh-log.txt")
    env = {"PATH": _env_path_value(claude)}
    home_override = os.environ.get("SCHOOL_CALENDAR_HOME")
    if home_override:
        env["SCHOOL_CALENDAR_HOME"] = home_override
    return {
        "Label": _agent_label(school_slug),
        "ProgramArguments": [claude, "-p", f">refresh {school_slug}"],
        "StartCalendarInterval": _calendar_intervals(cadence),
        "RunAtLoad": False,
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
        "EnvironmentVariables": env,
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _bootstrap(plist_path: Path) -> subprocess.CompletedProcess:
    proc = _launchctl("bootstrap", f"gui/{_uid()}", str(plist_path))
    if proc.returncode != 0:
        # Older macOS without the bootstrap subcommand, or agent already
        # loaded under a stale registration - load -w is the fallback either way.
        fallback = _launchctl("load", "-w", str(plist_path))
        if fallback.returncode == 0:
            return fallback
    return proc


def _bootout(school_slug: str, plist_path: Path) -> subprocess.CompletedProcess:
    proc = _launchctl("bootout", f"gui/{_uid()}/{_agent_label(school_slug)}")
    if proc.returncode != 0:
        proc = _launchctl("unload", "-w", str(plist_path))
    return proc


def _is_agent_loaded(school_slug: str) -> bool:
    proc = _launchctl("list")
    return proc.returncode == 0 and _agent_label(school_slug) in proc.stdout


def _remove_legacy_cron(school_slug: str) -> int:
    existing_lines = _current_crontab().splitlines()
    marker_substr = _school_marker_substring(school_slug)
    kept_lines = [line for line in existing_lines if marker_substr not in line]
    removed = len(existing_lines) - len(kept_lines)
    if removed:
        subprocess.run(["crontab", "-"], input="\n".join(kept_lines) + ("\n" if kept_lines else ""), text=True, capture_output=True)
    return removed


def _legacy_cron_schools() -> dict[str, str]:
    """slug -> cadence, read off whatever school-calendar cron lines remain."""
    pattern = re.compile(rf"# {re.escape(MARKER_PREFIX)}:([^:]+):([^:]+):")
    found: dict[str, str] = {}
    for line in _current_crontab().splitlines():
        m = pattern.search(line)
        if m:
            found[m.group(1)] = m.group(2)
    return found


def setup_launchd(school_slug: str, cadence: str) -> dict:
    if cadence not in CADENCES:
        return {"success": False, "error": f"Unknown cadence '{cadence}', expected one of {list(CADENCES)}"}

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    plist_path = _plist_path(school_slug)
    if _is_agent_loaded(school_slug):
        _bootout(school_slug, plist_path)

    with open(plist_path, "wb") as f:
        plistlib.dump(_build_plist(school_slug, cadence), f)

    proc = _bootstrap(plist_path)
    success = proc.returncode == 0
    result = {
        "mechanism": "launchd",
        "success": success,
        "cadence": cadence,
        "plist_path": str(plist_path),
        "label": _agent_label(school_slug),
        "stderr": proc.stderr if not success else "",
    }
    if success:
        # Only strip the old cron entries once the new agent is confirmed
        # loaded - never leave a school with neither mechanism registered.
        result["legacy_cron_lines_removed"] = _remove_legacy_cron(school_slug)
    else:
        result["note"] = (
            "launchd registration failed (this sandbox may block launchctl, the same "
            "restriction hit earlier with crontab). The plist was written correctly to "
            f"{plist_path} but not loaded, and any existing legacy crontab entries for "
            "this school were left untouched as a safety net. Run this in a real "
            f'terminal to finish: launchctl bootstrap gui/{_uid()} "{plist_path}"'
        )
    return result


def remove_launchd(school_slug: str) -> dict:
    plist_path = _plist_path(school_slug)
    bootout_proc = None
    if plist_path.exists() or _is_agent_loaded(school_slug):
        bootout_proc = _bootout(school_slug, plist_path)
    if plist_path.exists():
        plist_path.unlink()
    legacy_removed = _remove_legacy_cron(school_slug)
    still_loaded = _is_agent_loaded(school_slug)
    return {
        "mechanism": "launchd",
        "success": not still_loaded and not plist_path.exists(),
        "legacy_cron_lines_removed": legacy_removed,
        "stderr": bootout_proc.stderr if bootout_proc and bootout_proc.returncode != 0 else "",
    }


def _describe_calendar_intervals(intervals) -> list[dict]:
    if isinstance(intervals, dict):
        intervals = [intervals]
    runs = []
    for entry in intervals:
        hour, minute, day = entry.get("Hour", 0), entry.get("Minute", 0), entry.get("Day", 1)
        month = entry.get("Month")
        if month:
            runs.append({"tag": MONTH_NAMES.get(month, str(month)), "schedule": f"{hour}:{minute:02d} on day {day} of month {month}"})
        else:
            runs.append({"tag": "monthly", "schedule": f"{hour}:{minute:02d} on day {day} of every month"})
    return runs


def _registered_launchd_schools() -> dict[str, dict]:
    schools: dict[str, dict] = {}
    if not LAUNCH_AGENTS_DIR.exists():
        return schools
    for plist_path in LAUNCH_AGENTS_DIR.glob("com.school-calendar.refresh.*.plist"):
        slug = plist_path.stem[len("com.school-calendar.refresh."):]
        try:
            with open(plist_path, "rb") as f:
                data = plistlib.load(f)
        except Exception:
            continue
        runs = _describe_calendar_intervals(data.get("StartCalendarInterval", []))
        cadence = "termly" if any(r["tag"] != "monthly" for r in runs) else "monthly"
        schools[slug] = {"school_slug": slug, "cadence": cadence, "runs": runs}
    return schools


def list_launchd(school_slug: str | None) -> dict:
    # Self-healing migration: any school still only on legacy cron gets
    # promoted to launchd right here, so a plain --list call (as used by
    # >show-schedule) is what actually lands the one-time migration for
    # existing installs, without needing --cadence re-run per school.
    migration_warnings = []
    for slug, cadence in _legacy_cron_schools().items():
        if school_slug and slug != school_slug:
            continue
        if _plist_path(slug).exists():
            continue  # already migrated (or a prior migration attempt left the plist)
        result = setup_launchd(slug, cadence)
        if not result["success"]:
            migration_warnings.append({"school_slug": slug, "error": result.get("stderr") or result.get("note")})

    schools = _registered_launchd_schools()
    if school_slug:
        schools = {k: v for k, v in schools.items() if k == school_slug}

    # Anything migration couldn't move (sandbox-blocked launchctl) stays
    # visible via its still-live cron entries rather than disappearing.
    cron_view = list_cron(school_slug)
    for entry in cron_view["schools"]:
        schools.setdefault(entry["school_slug"], entry)

    output = {"mechanism": "launchd", "schools": list(schools.values())}
    if migration_warnings:
        output["migration_warnings"] = migration_warnings
    return output


def _task_name(school_slug: str, cadence: str, tag: str) -> str:
    return f"SchoolCalendarRefresh_{school_slug}_{cadence}_{tag}"


def setup_schtasks(school_slug: str, cadence: str) -> dict:
    if cadence not in CADENCES:
        return {"success": False, "error": f"Unknown cadence '{cadence}', expected one of {list(CADENCES)}"}
    _delete_all_schtasks(school_slug)
    claude = _claude_path()
    results = []
    for month in CADENCES[cadence]:
        tag = MONTH_NAMES[month]
        name = _task_name(school_slug, cadence, tag)
        proc = subprocess.run([
            "schtasks", "/create", "/tn", name,
            "/tr", f'{claude} -p ">refresh {school_slug}"',
            "/sc", "monthly", "/mo", "1", "/m", WINDOWS_MONTHS[tag], "/d", "1",
            "/st", "09:00", "/f",
        ], capture_output=True, text=True)
        results.append({"task_name": name, "success": proc.returncode == 0, "stderr": proc.stderr})
    return {"mechanism": "schtasks", "cadence": cadence, "results": results, "success": all(r["success"] for r in results)}


def _list_schtasks_names(school_slug: str | None) -> list[str]:
    proc = subprocess.run(["schtasks", "/query", "/fo", "csv"], capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    prefix = f"SchoolCalendarRefresh_{school_slug}_" if school_slug else "SchoolCalendarRefresh_"
    return [name for name in re.findall(r'"([^"]+)"', proc.stdout) if name.startswith(prefix)]


def _delete_all_schtasks(school_slug: str) -> None:
    for name in _list_schtasks_names(school_slug):
        subprocess.run(["schtasks", "/delete", "/tn", name, "/f"], capture_output=True, text=True)


def remove_schtasks(school_slug: str) -> dict:
    names = _list_schtasks_names(school_slug)
    results = [
        {"task_name": name, "success": subprocess.run(["schtasks", "/delete", "/tn", name, "/f"], capture_output=True, text=True).returncode == 0}
        for name in names
    ]
    return {"mechanism": "schtasks", "results": results, "success": all(r["success"] for r in results)}


def list_schtasks(school_slug: str | None) -> dict:
    names = _list_schtasks_names(school_slug)
    schools: dict[str, dict] = {}
    for name in names:
        m = re.match(r"SchoolCalendarRefresh_(.+)_(termly|monthly)_(\w+)$", name)
        if not m:
            continue
        slug, cadence, tag = m.groups()
        entry = schools.setdefault(slug, {"school_slug": slug, "cadence": cadence, "runs": []})
        entry["runs"].append({"tag": tag, "task_name": name})
    return {"mechanism": "schtasks", "schools": list(schools.values())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-slug")
    parser.add_argument("--cadence", choices=list(CADENCES))
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    system = platform.system()
    is_windows = system == "Windows"
    is_macos = system == "Darwin"

    if args.list:
        if is_windows:
            output = list_schtasks(args.school_slug)
        elif is_macos:
            output = list_launchd(args.school_slug)
        else:
            output = list_cron(args.school_slug)
    elif args.remove:
        if not args.school_slug:
            parser.error("--school-slug is required with --remove")
        if is_windows:
            output = remove_schtasks(args.school_slug)
        elif is_macos:
            output = remove_launchd(args.school_slug)
        else:
            output = remove_cron(args.school_slug)
    else:
        if not args.school_slug or not args.cadence:
            parser.error("--school-slug and --cadence are required to set up a schedule")
        if is_windows:
            output = setup_schtasks(args.school_slug, args.cadence)
        elif is_macos:
            output = setup_launchd(args.school_slug, args.cadence)
        else:
            output = setup_cron(args.school_slug, args.cadence)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
