"""Shared helpers used by the other school-calendar scripts.

Not a CLI itself — import from the other scripts in this folder.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path

CONFIG_ROOT = Path(os.environ.get("SCHOOL_CALENDAR_HOME") or os.path.expanduser("~/.school-calendar"))
SCHEMA_VERSION = 2

# Strict 24h HH:MM only - deliberately does not accept "6:00-8:00pm" or
# "TBC" style values seen in real parent-supplied sheets. Ignoring anything
# ambiguous is safer than guessing at am/pm.
_SINGLE_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_TIME_RANGE_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)\s*-\s*([01]?\d|2[0-3]):([0-5]\d)$")


def format_time_suffix(raw_time: str | None) -> str | None:
    """Validate a raw TIME-column value and turn it into the " (HH:MM)" or
    " (HH:MM-HH:MM)" suffix to append to an event title - or None if it's
    blank or isn't strictly 24h format (never guessed at). Events stay
    all-day either way; this only ever affects the title text, on purpose -
    a specific meeting time as a real ICS time field would be more
    disruptive to a parent's calendar than useful.
    """
    if not raw_time:
        return None
    raw_time = raw_time.strip()
    if not raw_time:
        return None

    m = _TIME_RANGE_RE.match(raw_time)
    if m:
        h1, m1, h2, m2 = m.groups()
        return f" ({int(h1):02d}:{m1}-{int(h2):02d}:{m2})"

    m = _SINGLE_TIME_RE.match(raw_time)
    if m:
        h, mi = m.groups()
        return f" ({int(h):02d}:{mi})"

    return None


def slugify(name: str) -> str:
    """Turn a school name into a filesystem/UID-safe slug."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def normalize_summary(text: str) -> str:
    """Normalize an event label so the same event matches across re-scrapes
    even if wording/punctuation shifts slightly (e.g. "Half Term" vs "Half-Term").
    """
    text = text.lower()
    text = text.replace("–", "-").replace("—", "-")  # en/em dash -> hyphen
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    filler = {"the", "school", "for", "of", "a", "an"}
    words = [w for w in re.split(r"[\s-]+", text) if w and w not in filler]
    return "-".join(words)


def event_id(category: str, term_name: str | None, summary: str, start_date: str) -> str:
    """Stable semantic key for matching the same event across refreshes.

    Deliberately NOT based on the full date or array position — the exact
    day is precisely what's expected to change, and array position shifts
    when the school adds/removes an event earlier in the list. The academic
    YEAR (derived from start_date) is included, though: a single config can
    hold more than one academic year's events at once (this is exactly what
    real production data looks like - schools publish a year or two ahead,
    and it's natural to keep them all in one calendar/config rather than
    starting a new file every September). Without the year, "Michaelmas
    Term begins" in 2025 and the identical label in 2026 would compute to
    the same id, and refresh-matching could silently update the wrong
    year's event.
    """
    year_label = academic_year_for_date(date.fromisoformat(start_date))
    parts = [category]
    if term_name:
        parts.append(term_name.lower())
    parts.append(normalize_summary(summary))
    parts.append(year_label)
    return slugify("-".join(parts))


def academic_year_bounds(year_str: str) -> tuple[date, date]:
    """'2025-26' -> (2025-09-01, 2026-08-31). UK academic year runs Sep-Aug."""
    start_year = int(year_str.split("-")[0])
    return date(start_year, 9, 1), date(start_year + 1, 8, 31)


def academic_year_for_date(d: date) -> str:
    """Which academic year label a given date falls into."""
    if d.month >= 9:
        return f"{d.year}-{str(d.year + 1)[-2:]}"
    return f"{d.year - 1}-{str(d.year)[-2:]}"


def config_path(school_slug: str) -> Path:
    return CONFIG_ROOT / school_slug / "config.json"


def load_config(school_slug: str) -> dict | None:
    path = config_path(school_slug)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config_atomic(school_slug: str, data: dict) -> Path:
    """Write config via a temp file + os.replace so a crash mid-write never
    corrupts the existing config (which is the only durable record of a
    school's manual events and last-scraped baselines).
    """
    path = config_path(school_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["schema_version"] = SCHEMA_VERSION
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return path


def list_schools() -> list[str]:
    if not CONFIG_ROOT.exists():
        return []
    return sorted(
        p.name for p in CONFIG_ROOT.iterdir()
        if p.is_dir() and (p / "config.json").exists()
    )


def default_output_dir(school_name: str) -> Path:
    return Path(os.path.expanduser(f"~/Documents/School Calendars/{school_name}"))
