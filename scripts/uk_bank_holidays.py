#!/usr/bin/env python3
"""Compute England & Wales bank holidays for a date range.

Deterministic, not scraped - Easter-based holidays use dateutil's Easter
algorithm, fixed-date holidays (New Year's Day, Christmas Day, Boxing Day)
apply the standard "moved to the next weekday if it falls on a weekend"
substitution rule used by gov.uk.

Known limitation, intentionally out of scope: one-off historical exceptions
(e.g. the Early May bank holiday was moved to Friday 8 May 2020 for VE Day's
75th anniversary; extra bank holidays were added for the 2022 Platinum
Jubilee and 2023 Coronation) are NOT modelled - those were one-off past
events, not a repeating rule, and this skill targets current/future academic
years. If a school year requires one, it can be added as a manual event.

Usage:
    python3 uk_bank_holidays.py --from 2025-09-01 --to 2026-08-31
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from dateutil.easter import easter


def _new_years_day(year: int) -> date:
    nyd = date(year, 1, 1)
    if nyd.weekday() == 5:  # Saturday -> Monday
        return nyd + timedelta(days=2)
    if nyd.weekday() == 6:  # Sunday -> Monday
        return nyd + timedelta(days=1)
    return nyd


def _christmas_and_boxing_day(year: int) -> tuple[date, date]:
    christmas = date(year, 12, 25)
    weekday = christmas.weekday()  # Mon=0 ... Sun=6
    if weekday == 4:  # Fri: Christmas fine, Boxing Day (Sat) -> Monday
        return christmas, date(year, 12, 28)
    if weekday == 5:  # Sat: Christmas -> Monday, Boxing Day (Sun) -> Tuesday
        return date(year, 12, 27), date(year, 12, 28)
    if weekday == 6:  # Sun: Christmas -> Tuesday, Boxing Day (Mon) fine
        return date(year, 12, 27), date(year, 12, 26)
    return christmas, date(year, 12, 26)


def _first_monday_of(year: int, month: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


def _last_monday_of(year: int, month: int) -> date:
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != 0:
        d -= timedelta(days=1)
    return d


def bank_holidays_for_year(year: int) -> list[dict]:
    """All England & Wales bank holidays whose fixed calendar date is in
    the given calendar year (not academic year) - caller filters by range.
    """
    easter_sunday = easter(year)
    good_friday = easter_sunday - timedelta(days=2)
    easter_monday = easter_sunday + timedelta(days=1)
    christmas_obs, boxing_obs = _christmas_and_boxing_day(year)
    christmas_moved = christmas_obs != date(year, 12, 25)
    boxing_moved = boxing_obs != date(year, 12, 26)

    holidays = [
        ("🏦 New Year's Day", _new_years_day(year)),
        ("🏦 Good Friday", good_friday),
        ("🏦 Easter Monday", easter_monday),
        ("🏦 Early May Bank Holiday", _first_monday_of(year, 5)),
        ("🏦 Spring Bank Holiday", _last_monday_of(year, 5)),
        ("🏦 Summer Bank Holiday", _last_monday_of(year, 8)),
        ("🏦 Christmas Day" + (" (substitute)" if christmas_moved else ""), christmas_obs),
        ("🏦 Boxing Day" + (" (substitute)" if boxing_moved else ""), boxing_obs),
    ]
    return [
        {
            "category": "bank_holiday",
            "term_name": None,
            "summary": name,
            "start_date": d.isoformat(),
            "end_date": d.isoformat(),  # single-day event: inclusive end == start
        }
        for name, d in holidays
    ]


def bank_holidays_in_range(from_date: date, to_date: date) -> list[dict]:
    events = []
    for year in range(from_date.year, to_date.year + 1):
        for event in bank_holidays_for_year(year):
            start = date.fromisoformat(event["start_date"])
            if from_date <= start <= to_date:
                events.append(event)
    events.sort(key=lambda e: e["start_date"])
    return events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date)
    events = bank_holidays_in_range(from_date, to_date)
    print(json.dumps(events, indent=2))


if __name__ == "__main__":
    main()
