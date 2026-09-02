# ICS format notes

`generate_ics.py` handles all of this in code - this file is for understanding
*why*, and for reference if you're debugging a calendar app that isn't
showing events correctly.

## Header block

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//[School Name]//Term Dates [YEARS]//EN
X-WR-CALNAME:[School Name]
X-WR-CALDESC:Term dates, holidays and half terms [YEARS]. Source: [URL]
CALSCALE:GREGORIAN
METHOD:PUBLISH
REFRESH-INTERVAL;VALUE=DURATION:P1D
X-PUBLISHED-TTL:P1D
```

- `X-WR-CALNAME` is the single most important line for the end-user
  experience: it's what makes Apple Calendar and Google Calendar show this
  as its own named, togglable calendar when someone subscribes, rather than
  dumping events into their main calendar.
- `REFRESH-INTERVAL` / `X-PUBLISHED-TTL` are both set to one day (`P1D`) -
  this is a hint to calendar apps about how often to re-poll the URL for
  changes. Not all apps honor it exactly (Google Calendar in particular
  polls on its own schedule, often less often than requested), but it's the
  correct signal to send.

## Events are all-day, using DATE not DATE-TIME

```
BEGIN:VEVENT
DTSTART;VALUE=DATE:20250904
DTEND;VALUE=DATE:20250905
SUMMARY:Term begins
UID:school-slug-0001@school-calendar
DTSTAMP:20260704T090000Z
STATUS:CONFIRMED
END:VEVENT
```

`DTSTAMP` (the moment this specific version of the event was generated) is
required by RFC5545 for every VEVENT, even though it's easy to miss when
looking at simplified examples - `generate_ics.py` always includes it.

## DTEND is exclusive - and that conversion happens in code, once

Throughout this skill, every event's `start_date`/`end_date` (as stored in
config.json and as Claude extracts them) is the natural, human-meaningful
**inclusive** range - "half term is Monday 27th to Friday 31st" is stored
as start=27th, end=31st, exactly as a person would say it.

RFC5545 requires `DTEND` to be **exclusive** (the first date *not* included
in the event). `generate_ics.py` converts inclusive end_date -> exclusive
DTEND by adding exactly one calendar day - nothing fancier than that:

| Human description | Stored `start_date` / `end_date` | Rendered `DTSTART` / `DTEND` |
|---|---|---|
| Single day, 4 Sep | 2025-09-04 / 2025-09-04 | 20250904 / 20250905 |
| Mon 27 - Fri 31 Oct | 2025-10-27 / 2025-10-31 | 20251027 / 20251101 |

Note the second example: DTEND is Saturday 1 Nov (the very next calendar
day after Friday), **not** "the following Monday" - it's easy to assume the
exclusive end should skip forward to the next school day, but that's wrong
and would make the event visually bleed into the following week in
calendar apps. This was verified against the project owner's real,
already-working ICS file before implementing `generate_ics.py`, rather than
assumed.

## UIDs must be stable across re-generation

Format: `[school-slug]-NNNN@school-calendar`, e.g.
`example-primary-school-0007@school-calendar`.

Calendar apps use UID to recognize "this is an update to an event I already
have" vs "this is a new event". If the same real-world event gets a
different UID on every `>refresh`, subscribers end up with duplicates
instead of updates. `compare_dates.py` matches re-scraped events back to
their existing config entry (by a semantic key, not by array position or
raw date) specifically so the same UID gets reused - see
`scraping_playbook.md` for how that matching works.

## Line folding and encoding

- Lines are wrapped at 75 octets per RFC5545 (`generate_ics.py`'s
  `fold_line`), splitting on UTF-8 byte boundaries so an emoji in a
  `SUMMARY` (e.g. "🌸 Half Term") never gets corrupted mid-character.
- The file is written with CRLF (`\r\n`) line endings throughout, including
  on macOS/Linux where the OS default is bare `\n` - RFC5545 requires CRLF,
  and some calendar clients reject or mis-parse files that don't have it.
  `generate_ics.py` opens the output file with `newline=""` specifically to
  stop Python's own text-mode line-ending translation from interfering.
