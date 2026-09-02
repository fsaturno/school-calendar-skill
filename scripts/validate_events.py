#!/usr/bin/env python3
"""Cheap deterministic sanity checks on a freshly-extracted event list.

This is a safety net alongside the "does this look right?" human review
step, not a replacement for it - some mistakes (a genuinely wrong date that
still looks plausible) can only be caught by a person who knows their own
school. But some mistakes ARE mechanically detectable and worth catching
automatically: a start date after its end date, an obvious duplicate, a
date that's nowhere near the academic year being processed. These are also
exactly the kind of error a scraping/OCR/PDF-extraction mistake tends to
produce, so catching them here means the user sees fewer visibly-broken
entries before they even get to review the list.

Errors are things that are definitely wrong (bad enough to require fixing
before generating the ICS). Warnings are things worth a second look but not
necessarily wrong (e.g. only two half-terms found - some schools genuinely
only publish two, but it's worth Claude double-checking against the page).

Usage:
    python3 validate_events.py --events events.json --academic-year 2025-26
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import academic_year_bounds, event_id  # noqa: E402

# Some slack either side of Sep 1 - Aug 31: INSET days are sometimes the
# last days of August, and a "summer holiday ends" entry can spill into
# early September of the following academic year.
BOUNDS_SLACK_DAYS = 21

EXPECTED_MIN_HALF_TERMS = 2  # most UK schools have 3; some genuinely have 2


def validate(events: list[dict], academic_year: str | None) -> dict:
    errors = []
    warnings = []

    bounds = None
    if academic_year:
        try:
            start, end = academic_year_bounds(academic_year)
            bounds = (start - timedelta(days=BOUNDS_SLACK_DAYS), end + timedelta(days=BOUNDS_SLACK_DAYS))
        except (ValueError, IndexError):
            warnings.append(f"Couldn't parse academic year '{academic_year}' - skipping date-range checks.")

    seen_event_ids: dict[str, int] = {}
    parsed = []
    category_counts: dict[str, int] = {}

    for i, ev in enumerate(events):
        label = ev.get("summary", f"event #{i}")
        try:
            start = date.fromisoformat(ev["start_date"])
            end = date.fromisoformat(ev["end_date"])
        except (KeyError, ValueError) as exc:
            errors.append(f"'{label}': unparseable date ({exc})")
            continue

        if start > end:
            errors.append(f"'{label}': start date ({start}) is after end date ({end})")
            continue

        if bounds and not (bounds[0] <= start <= bounds[1]):
            warnings.append(
                f"'{label}' starts {start}, which is well outside the {academic_year} academic "
                f"year - double check this wasn't misread from a different year on the page."
            )

        eid = event_id(ev.get("category", ""), ev.get("term_name"), ev.get("summary", ""), ev["start_date"])
        seen_event_ids[eid] = seen_event_ids.get(eid, 0) + 1

        category = ev.get("category", "uncategorized")
        category_counts[category] = category_counts.get(category, 0) + 1
        parsed.append({"label": label, "category": category, "start": start, "end": end})

    for eid, count in seen_event_ids.items():
        if count > 1:
            warnings.append(f"Event id '{eid}' appears {count} times - check these aren't accidental duplicates.")

    # Overlap check within the same category (e.g. two "half_term" ranges
    # that overlap almost always means one was misread).
    by_category: dict[str, list] = {}
    for p in parsed:
        by_category.setdefault(p["category"], []).append(p)
    for category, items in by_category.items():
        items.sort(key=lambda p: p["start"])
        for a, b in zip(items, items[1:]):
            if a["end"] >= b["start"]:
                warnings.append(
                    f"'{a['label']}' ({a['start']}-{a['end']}) overlaps '{b['label']}' "
                    f"({b['start']}-{b['end']}) - both are category '{category}'."
                )

    if category_counts.get("half_term", 0) < EXPECTED_MIN_HALF_TERMS:
        warnings.append(
            f"Only {category_counts.get('half_term', 0)} half-term event(s) found - most UK "
            f"schools have 3 (autumn/spring/summer). Double-check the page for a missing one."
        )
    if category_counts.get("term", 0) == 0:
        warnings.append("No 'term' category events found at all - check term start/end dates were extracted.")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "category_counts": category_counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--academic-year")
    args = parser.parse_args()

    with open(args.events, "r", encoding="utf-8") as f:
        events = json.load(f)

    print(json.dumps(validate(events, args.academic_year), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
