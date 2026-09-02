#!/usr/bin/env python3
"""Check whether new manual event(s) collide with something already on a
school's calendar - used by the add-event command so re-running it (or
pasting the same list twice by mistake) doesn't quietly pile up duplicate
entries.

A "collision" is any existing, non-suppressed event sharing the exact same
start_date, reported together with a text-similarity score against that
event's summary (same normalize_summary + difflib approach compare_dates.py
uses for its own matching). A high similarity score on the same date is
almost certainly the same event being re-added; a low one is just two
different, legitimate things happening to fall on the same day (a bake sale
during half-term is not a duplicate of "Half Term").

Hard rule, enforced here rather than left to prose instructions: a
manually-added event must NEVER replace or shadow an official (source:
"scraped") date. Parent-supplied lists (e.g. a PTA fundraising spreadsheet)
often restate official dates for reference ("04-09-2026 Start of Term") -
when that restated date collides with the real scraped one, the official
entry stays authoritative no matter what the spreadsheet says, and the
duplicate is never added. This is a policy with one correct answer, so it's
computed here as `recommended_action` rather than re-derived from prose
each time:

  - "skip_official_duplicate" - collides with a scraped/official event at
    high similarity. Never add this - the official date already covers it.
  - "review" - collides with an existing MANUAL event at high similarity
    (e.g. re-running add-event with the same list twice). Worth asking the
    user rather than auto-deciding, since re-adding on purpose is valid.
  - "add" - no high-similarity collision. Low-similarity same-day
    collisions (if any) are included for context only, never blocking.

Usage:
    python3 check_duplicates.py --config config.json --new-events new_events.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import normalize_summary  # noqa: E402

LIKELY_DUPLICATE_THRESHOLD = 0.6


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_summary(a), normalize_summary(b)).ratio()


def check(existing_events: list[dict], new_events: list[dict]) -> dict:
    active_existing = [e for e in existing_events if not e.get("suppressed")]
    results = []

    for cand in new_events:
        try:
            cand_start = cand["start_date"]
            date.fromisoformat(cand_start)  # validate parseable
        except (KeyError, ValueError):
            results.append({"new_event": cand, "collisions": [], "error": "unparseable start_date"})
            continue

        collisions = []
        for ev in active_existing:
            current = ev.get("current", {})
            if current.get("start_date") != cand_start:
                continue
            sim = _similarity(cand.get("summary", ""), current.get("summary", ""))
            collisions.append({
                "uid": ev.get("uid"),
                "event_id": ev.get("event_id"),
                "summary": current.get("summary"),
                "start_date": current.get("start_date"),
                "end_date": current.get("end_date"),
                "category": ev.get("category"),
                "source": ev.get("source"),
                "similarity": round(sim, 2),
                "likely_duplicate": sim >= LIKELY_DUPLICATE_THRESHOLD,
            })

        collisions.sort(key=lambda c: -c["similarity"])

        official_duplicate = any(c["source"] == "scraped" and c["likely_duplicate"] for c in collisions)
        manual_duplicate = any(c["source"] == "manual" and c["likely_duplicate"] for c in collisions)
        if official_duplicate:
            action = "skip_official_duplicate"
        elif manual_duplicate:
            action = "review"
        else:
            action = "add"

        results.append({"new_event": cand, "collisions": collisions, "recommended_action": action})

    return {"results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--new-events", required=True)
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)
    with open(args.new_events, "r", encoding="utf-8") as f:
        new_events = json.load(f)

    print(json.dumps(check(config.get("events", []), new_events), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
