#!/usr/bin/env python3
"""Confirm a subscription URL (Google Drive or self-hosted) actually serves
a live, valid .ics file - used at the publish step (both Drive and
self-hosted paths get verified, per this skill's design) and by the
`>verify` command for a quick standalone check.

Failure reasons are classified into plain, non-technical messages rather
than surfacing raw HTTP/parsing errors, since the audience is parents, not
developers.

Usage:
    python3 verify_subscription_url.py --url <candidate_url> [--compare-to local.ics]
"""
from __future__ import annotations

import argparse
import json
import re

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20

# A handful of phrases Google Drive shows instead of file content when a
# file isn't shared publicly (virus-scan interstitial, sign-in wall, etc).
_DRIVE_BLOCKED_MARKERS = [
    "can't scan this file for viruses",
    "sign in - google accounts",
    "google drive - access denied",
    "you need permission",
    "request access",
]


def _extract_event_keys(ics_text: str) -> set[tuple]:
    """Pull (UID, DTSTART, DTEND, SUMMARY) tuples out of raw ICS text for a
    lightweight structural comparison - not a full RFC5545 parse, just
    enough to tell "same content" from "different content".
    """
    keys = set()
    events = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics_text, re.DOTALL)
    for block in events:
        def field(name):
            m = re.search(rf"^{name}[^:]*:(.*)$", block, re.MULTILINE)
            return m.group(1).strip() if m else ""
        keys.add((field("UID"), field("DTSTART"), field("DTEND"), field("SUMMARY")))
    return keys


def verify(url: str, compare_to: str | None = None) -> dict:
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, allow_redirects=True
        )
    except requests.RequestException as exc:
        return {"ok": False, "reason": f"Couldn't reach that link at all ({exc}). Double check it was copied correctly."}

    result = {
        "ok": False,
        "http_status": response.status_code,
        "final_url": response.url,
        "reason": None,
        "content_preview": response.text[:120],
    }

    if response.status_code < 200 or response.status_code >= 300:
        result["reason"] = f"We got an HTTP {response.status_code} back from that link - double check the URL is correct."
        return result

    body = response.text
    body_lower = body.lower()

    if body.lstrip().startswith("BEGIN:VCALENDAR"):
        result["ok"] = True
        result["reason"] = None
    elif any(marker in body_lower for marker in _DRIVE_BLOCKED_MARKERS):
        result["reason"] = (
            "That link isn't publicly viewable yet - in Google Drive, right-click the file, "
            "choose Share, and make sure it's set to 'Anyone with the link' (Viewer)."
        )
    elif "<html" in body_lower or "<!doctype" in body_lower:
        result["reason"] = (
            "That looks like a webpage, not a calendar file - check you're pasting the direct "
            "file URL (the one that starts the download), not a page that just links to it."
        )
    elif not body.strip():
        result["reason"] = "That link returned an empty response - double check the URL."
    else:
        result["reason"] = "That doesn't look like a calendar file (it doesn't start with BEGIN:VCALENDAR)."

    if result["ok"] and compare_to:
        try:
            with open(compare_to, "r", encoding="utf-8") as f:
                local_text = f.read()
            live_keys = _extract_event_keys(body)
            local_keys = _extract_event_keys(local_text)
            result["content_matches_local"] = live_keys == local_keys
            if live_keys != local_keys:
                result["compare_note"] = (
                    "The live file doesn't match your local copy yet - did the re-upload finish? "
                    "It can also take a minute for some hosts to serve the new version."
                )
        except OSError as exc:
            result["compare_error"] = str(exc)

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--compare-to", help="Local .ics file to compare live content against")
    args = parser.parse_args()

    result = verify(args.url, args.compare_to)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
