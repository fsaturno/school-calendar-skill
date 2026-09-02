#!/usr/bin/env python3
"""Diff a freshly re-scraped event list against a school's saved config.

This is the script that makes the manual-events precedence rule actually
work: a parent's manual correction to a wrong date must survive repeated
`>refresh` runs that keep re-scraping the same (still-wrong) value, but must
still yield to the school's own page once THAT genuinely changes.

The key idea: compare the new scrape against each event's `last_scraped`
snapshot (what the school's page showed last time), never against `current`
(which may be a manual override). If the new scrape matches last_scraped,
nothing happened on the school's side - no diff, current is left alone even
though it may differ from the fresh scrape. If the new scrape differs from
last_scraped, the school genuinely changed something, and that's surfaced
for the user to confirm.

This script is read-only / report-only - it does not mutate config.json.
Applying accepted changes (updating current/last_scraped, allocating UIDs
for new events, suppressing removed ones) is done by whoever's driving the
`>refresh` conversation (Claude, per SKILL.md), using this report to know
what to ask the user about.

Matching a freshly-scraped raw event to an existing config event uses two
passes:
  1. exact match on the semantic event_id (category + term name + normalized
     summary) - stable across refreshes even though dates move
  2. fallback: nearest start_date (within 14 days) + summary similarity,
     for generically-labelled repeats like multiple undifferentiated
     "INSET Day" entries where event_id alone can't disambiguate

Usage:
    python3 compare_dates.py --config config.json --new-events new_scraped_events.json --out diff_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import event_id, normalize_summary  # noqa: E402

DATE_WINDOW_DAYS = 14
SIMILARITY_THRESHOLD = 0.6


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_summary(a), normalize_summary(b)).ratio()


def _values_equal(a: dict, b: dict) -> bool:
    # Summary is compared normalized, not verbatim: extraction is done fresh
    # by an LLM on every refresh, not a deterministic parser, so wording or
    # emoji can vary slightly between runs even when the school's page
    # said exactly the same thing (confirmed directly: re-scraping the same
    # page produced "SJS - Last day of Summer Term" one run and "🏫 SJS -
    # Last day of Summer Term" the previous run - same event, same date).
    # An exact-string comparison would flag that as "changed" on every
    # single refresh, which is noise, not signal. Dates are still compared
    # exactly, since that precision is the entire point of this check.
    return (
        normalize_summary(a.get("summary", "")) == normalize_summary(b.get("summary", ""))
        and a.get("start_date") == b.get("start_date")
        and a.get("end_date") == b.get("end_date")
    )


def compare(config_events: list[dict], new_events: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    # Schools routinely trim past terms off their own term-dates page once
    # they're over (confirmed directly against a real school's live page no
    # longer listing a term once it had already finished) - that's
    # normal housekeeping, not the school "removing" anything meaningful,
    # so an event that's already fully in the past is never eligible to be
    # reported as "removed" just because a fresh scrape no longer mentions
    # it. It's still matched normally if the scrape happens to include it
    # (harmless), just never flagged as missing when it doesn't.
    scraped_config_events = [
        e for e in config_events
        if e.get("source") == "scraped" and e["current"]["end_date"] >= today.isoformat()
    ]
    manual_count = sum(1 for e in config_events if e.get("source") == "manual")

    for ev in new_events:
        ev["_event_id"] = event_id(ev["category"], ev.get("term_name"), ev["summary"], ev["start_date"])

    matched_new_ids = set()
    matches: list[tuple[dict, dict]] = []
    unmatched_config: list[dict] = []

    # Pass 1: exact event_id match.
    new_by_event_id: dict[str, list[dict]] = {}
    for ev in new_events:
        new_by_event_id.setdefault(ev["_event_id"], []).append(ev)

    for cev in scraped_config_events:
        candidates = [c for c in new_by_event_id.get(cev["event_id"], []) if id(c) not in matched_new_ids]
        if candidates:
            chosen = candidates[0]
            matches.append((cev, chosen))
            matched_new_ids.add(id(chosen))
        else:
            unmatched_config.append(cev)

    # Pass 2: nearest-date + summary-similarity fallback, same category only.
    still_unmatched_config = []
    for cev in unmatched_config:
        baseline = cev.get("last_scraped") or cev["current"]
        try:
            base_date = date.fromisoformat(baseline["start_date"])
        except (KeyError, ValueError):
            still_unmatched_config.append(cev)
            continue

        best_candidate = None
        best_score = 0.0
        for cand in new_events:
            if id(cand) in matched_new_ids or cand["category"] != cev["category"]:
                continue
            try:
                cand_date = date.fromisoformat(cand["start_date"])
            except ValueError:
                continue
            if abs((cand_date - base_date).days) > DATE_WINDOW_DAYS:
                continue
            score = _similarity(cand["summary"], baseline["summary"])
            if score > SIMILARITY_THRESHOLD and score > best_score:
                best_score = score
                best_candidate = cand

        if best_candidate:
            matches.append((cev, best_candidate))
            matched_new_ids.add(id(best_candidate))
        else:
            still_unmatched_config.append(cev)

    removed = still_unmatched_config
    new_only = [ev for ev in new_events if id(ev) not in matched_new_ids]

    changed = []
    unchanged_count = 0
    for cev, nev in matches:
        baseline = cev.get("last_scraped")
        new_vals = {"summary": nev["summary"], "start_date": nev["start_date"], "end_date": nev["end_date"]}
        if baseline is not None and _values_equal(baseline, new_vals):
            unchanged_count += 1
            continue
        changed.append({
            "event_id": cev["event_id"],
            "uid": cev["uid"],
            "category": cev["category"],
            "current": cev["current"],
            "last_scraped": baseline,
            "new_scraped": new_vals,
            "had_manual_override": bool(cev.get("manually_edited")),
        })

    return {
        "changed": changed,
        "new": [
            {
                "category": e["category"],
                "term_name": e.get("term_name"),
                "summary": e["summary"],
                "start_date": e["start_date"],
                "end_date": e["end_date"],
            }
            for e in new_only
        ],
        "removed": [
            {
                "event_id": e["event_id"],
                "uid": e["uid"],
                "category": e["category"],
                "current": e["current"],
                "last_scraped": e.get("last_scraped"),
            }
            for e in removed
        ],
        "unchanged_count": unchanged_count,
        "manual_only_count": manual_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--new-events", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)
    with open(args.new_events, "r", encoding="utf-8") as f:
        new_events = json.load(f)

    report = compare(config.get("events", []), new_events)

    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
    print(output)


if __name__ == "__main__":
    main()
