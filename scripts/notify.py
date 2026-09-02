#!/usr/bin/env python3
"""Best-effort notification when a scheduled `>refresh` completes and finds
a change. macOS only - matches this skill's scheduling scope (Fix 1 is
launchd/macOS-only too), so no platform branching is needed here.

Fallback chain (tried in order, first success wins):
    1. A connected email/Gmail MCP tool - NOT handled here. That can only be
       attempted from inside a live Claude session, before falling back to
       this script. See SKILL.md's `>refresh` step for how the two fit
       together: Claude tries the MCP tool first, and only shells out to
       this script if no such tool is connected, or the attempt failed.
    2. Mail.app automation via `osascript` - sends a real email, through
       whatever account(s) are already configured in Mail.app, to the
       user's own address (`user_contact` from config). Provider-agnostic
       in practice, but only helps if the user actually uses Apple Mail.
    3. A local macOS notification (`display notification`) - no external
       account needed, fires reliably as a plain shell command, but only
       reaches whoever's near the Mac and carries no email content.
    4. log-only - the baseline outcome if nothing above is available,
       enabled, or successful. This script never treats "nothing got
       through" as an error; a failed notification must never fail the
       refresh itself.

`--preference` controls how far down the chain this script is allowed to
go: "email" tries Mail.app then local notification; "local_only" skips
Mail.app and tries only the local notification; "none" does nothing at all
(the caller already logs the refresh result to refresh-log.txt regardless).

Usage:
    python3 notify.py --school-slug <slug> --school-name <name> \\
        --to <user_contact_email> --summary "<short summary of what changed>" \\
        --preference email|local_only|none

Always exits 0. Prints JSON: {"method": "email"|"local_notification"|"none",
"attempted": [...], "success": bool}.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess


def _osascript_available() -> bool:
    return shutil.which("osascript") is not None


def _applescript_string(text: str) -> str:
    """Escape a Python string for safe embedding in an AppleScript string
    literal (backslash and double-quote are the only characters AppleScript
    string literals treat specially)."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _run_osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)


def try_mail_app(school_name: str, to_address: str, summary: str) -> dict:
    if not _osascript_available():
        return {"method": "email", "success": False, "detail": "osascript not available"}
    if not to_address:
        return {"method": "email", "success": False, "detail": "no recipient address configured"}

    subject = _applescript_string(f"School Calendar update: {school_name}")
    body = _applescript_string(summary)
    to = _applescript_string(to_address)
    script = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{subject:"{subject}", content:"{body}", visible:false}}
        tell newMessage
            make new to recipient at end of to recipients with properties {{address:"{to}"}}
        end tell
        send newMessage
    end tell
    '''
    proc = _run_osascript(script)
    return {"method": "email", "success": proc.returncode == 0, "detail": proc.stderr.strip() if proc.returncode != 0 else "sent via Mail.app"}


def try_local_notification(school_name: str, summary: str) -> dict:
    if not _osascript_available():
        return {"method": "local_notification", "success": False, "detail": "osascript not available"}

    title = _applescript_string(f"School Calendar: {school_name}")
    message = _applescript_string(summary)
    script = f'display notification "{message}" with title "{title}"'
    proc = _run_osascript(script)
    return {"method": "local_notification", "success": proc.returncode == 0, "detail": proc.stderr.strip() if proc.returncode != 0 else "shown"}


def notify(school_slug: str, school_name: str, to_address: str, summary: str, preference: str) -> dict:
    attempted = []

    if preference == "none":
        return {"method": "none", "attempted": attempted, "success": False}

    if preference == "email":
        result = try_mail_app(school_name, to_address, summary)
        attempted.append(result)
        if result["success"]:
            return {"method": "email", "attempted": attempted, "success": True}

    result = try_local_notification(school_name, summary)
    attempted.append(result)
    if result["success"]:
        return {"method": "local_notification", "attempted": attempted, "success": True}

    return {"method": "none", "attempted": attempted, "success": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-slug", required=True)
    parser.add_argument("--school-name", required=True)
    parser.add_argument("--to", default="", help="Recipient address for the Mail.app path (user_contact from config)")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--preference", choices=["email", "local_only", "none"], default="local_only")
    args = parser.parse_args()

    result = notify(args.school_slug, args.school_name, args.to, args.summary, args.preference)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
