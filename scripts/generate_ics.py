#!/usr/bin/env python3
"""Turn a canonical event list into a strict RFC5545 .ics calendar file.

This is the one place format-correctness really matters, so it's plain
deterministic code, not something left to Claude to write freehand each
time. Rules enforced here:

  - exact header block (VERSION, PRODID, X-WR-CALNAME, X-WR-CALDESC,
    CALSCALE, METHOD, REFRESH-INTERVAL, X-PUBLISHED-TTL) - X-WR-CALNAME is
    what makes the calendar show up under the school's own name as a
    separate, togglable calendar in Apple/Google Calendar
  - all-day events via DTSTART/DTEND;VALUE=DATE. Every event's stored
    start_date/end_date is the natural INCLUSIVE calendar range (e.g. "half
    term is Mon 27 - Fri 31 October" is stored as start=27th, end=31st,
    exactly as a person would say it and exactly as Claude will naturally
    extract it from a school's page). RFC5545 requires DTEND to be
    EXCLUSIVE (the day *after* the last day), so that conversion - and only
    that conversion - happens here, in code, once, rather than trusting
    every event to have been hand-adjusted by whoever/whatever produced it.
  - UID stays exactly what's stored per event (stability across re-runs is
    handled upstream, by compare_dates.py's matching logic - this script
    just renders whatever UID it's given)
  - CRLF line endings throughout, written explicitly rather than relying on
    the OS's text-mode newline translation (this file may well be generated
    on a Mac and later regenerated on a school office's Windows PC)
  - RFC5545 75-octet line folding, mainly relevant for longer DESCRIPTION
    text

Usage:
    python3 generate_ics.py --config config.json --out "School - Calendar.ics" [--events events.json]

If --events is omitted, events are read from config["events"]. --events is
for the pre-save "does this look right?" preview step, before the event
list has been written into config.json yet.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone


def exclusive_dtend(inclusive_end_date: str) -> str:
    """RFC5545 DTEND is exclusive; our stored end_date is the natural
    inclusive last day. Convert once, here, in code."""
    d = datetime.strptime(inclusive_end_date, "%Y-%m-%d").date()
    return (d + timedelta(days=1)).strftime("%Y%m%d")


def ics_escape(text: str) -> str:
    """Escape TEXT-type values per RFC5545 (backslash, semicolon, comma, newline)."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    """RFC5545 75-octet line folding. Continuation lines are prefixed with a
    single space; splits are made on UTF-8 byte boundaries so multi-byte
    characters (emoji in SUMMARY) never get corrupted mid-character.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts = []
    remaining = encoded
    limit = 75
    while len(remaining) > limit:
        chunk = remaining[:limit]
        while chunk and (chunk[-1] & 0xC0) == 0x80:  # mid-UTF8-sequence, back off
            chunk = chunk[:-1]
        parts.append(chunk.decode("utf-8"))
        remaining = remaining[len(chunk):]
        limit = 74  # continuation lines lose 1 octet to the leading space
    parts.append(remaining.decode("utf-8"))
    return "\r\n ".join(parts)


def build_vevent(event: dict, dtstamp: str) -> list[str]:
    current = event["current"]
    start = current["start_date"].replace("-", "")
    end = exclusive_dtend(current["end_date"])
    lines = [
        "BEGIN:VEVENT",
        f"DTSTART;VALUE=DATE:{start}",
        f"DTEND;VALUE=DATE:{end}",
        f"SUMMARY:{ics_escape(current['summary'])}",
    ]
    if current.get("description"):
        lines.append(f"DESCRIPTION:{ics_escape(current['description'])}")
    lines.extend([
        f"UID:{event['uid']}",
        f"DTSTAMP:{dtstamp}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
    ])
    return lines


def build_ics(school_name: str, academic_year: str, dates_url: str, events: list[dict]) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{school_name}//Term Dates {academic_year}//EN",
        f"X-WR-CALNAME:{school_name}",
        f"X-WR-CALDESC:Term dates, holidays and half terms {academic_year}. Source: {dates_url}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]
    for event in sorted(events, key=lambda e: e["current"]["start_date"]):
        if event.get("suppressed"):
            continue
        lines.extend(build_vevent(event, dtstamp))
    lines.append("END:VCALENDAR")

    folded = [fold_line(line) for line in lines]
    return "\r\n".join(folded) + "\r\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--events", help="Optional event-list JSON; defaults to config['events']")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    if args.events:
        with open(args.events, "r", encoding="utf-8") as f:
            events = json.load(f)
    else:
        events = config.get("events", [])

    ics_text = build_ics(
        school_name=config["school_name"],
        academic_year=config.get("academic_year", ""),
        dates_url=config.get("dates_url", ""),
        events=events,
    )

    # newline="" is required here: without it, Python's text-mode I/O would
    # translate our explicit \r\n into \r\r\n on write (or back to \n on
    # read) depending on platform - this must stay byte-for-byte CRLF.
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(ics_text)

    event_count = sum(1 for e in events if not e.get("suppressed"))
    print(json.dumps({"written_to": args.out, "event_count": event_count}, indent=2))


if __name__ == "__main__":
    main()
