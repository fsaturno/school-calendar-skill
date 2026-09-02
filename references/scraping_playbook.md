# Scraping playbook

## Why there's no per-CMS parser library

UK school websites run on a long tail of platforms - Juniper, Schudio,
Greenhouse, School Jotter, Weduc, WordPress, Wix, Squarespace, Google Sites,
and fully bespoke builds - and even schools on the *same* CMS platform
publish term dates completely differently from each other. This was tested
directly against 8 real, unrelated school sites while building this skill,
and no two used quite the same approach. Maintaining a parser per CMS
vendor would be a losing battle against a long tail that never stops
growing, and estimates of "X% of schools use PDF vs HTML vs images" are
guesses without real measurement - the only way to know what a given
school does is to look.

So the design is deliberately split:

- **Scripts do mechanical, deterministic work only**: fetch a page, clean
  out navigation/script/style noise, flatten tables into readable text,
  enumerate every PDF/Word-doc/ICS-feed link and every "this might be the
  term-dates page" link (regardless of whether CSS would hide it from a
  human), download and extract text from documents, and calculate/verify/
  generate things that have one objectively correct answer (bank holidays,
  ICS formatting, URL reachability).
- **Claude does the judgment call**: reading whatever text ends up in
  front of it - a prose paragraph, a flattened table, extracted PDF text,
  an extracted Word document - and identifying which parts are term dates,
  in whatever phrasing the school actually used. This is what generalizes
  to schools nobody has tested against, where a fixed set of regexes or
  CSS selectors would simply fail silently.

## The fallback chain, in the order to try them

1. **Is the given URL itself a document?** `fetch_page.py` checks the
   response's content-type/extension first. If it's already a PDF or an
   `.ics` feed, it says so immediately rather than trying to HTML-parse it.
   An `.ics` feed is the best possible case - the school already publishes
   structured data; sanity-check it's actually the term-dates calendar
   (not some unrelated events feed) and use it close to as-is.
2. **Was a homepage given, not a term-dates page?** Use `--mode crawl` and
   read `links.keyword_links`, ranked by how specific the matched phrase
   was ("term dates" ranks far above a bare "calendar" link). If there's
   one clear winner, that's usually right; if several plausible candidates
   exist, ask the user which one.
3. **Read `cleaned_text` directly.** This is where Claude's own language
   understanding does the real work - no CMS-specific regex. This is the
   right first read whenever the page has real visible content, whether
   it's a table, a bulleted list, or plain prose with inline dates.
4. **No usable text, but `links.pdf_links` or `links.docx_links` exist?**
   Run `extract_pdf_text.py` / `extract_docx_text.py` on the most relevant
   document(s) (matched by filename/link text against the target academic
   year - schools sometimes list several years' documents side by side) and
   read the extracted text the same way as step 3. If a document looks
   scanned/empty (`looks_scanned_or_empty`), say so honestly rather than
   guessing - OCR is intentionally out of scope.
5. **`looks_js_rendered` is true and nothing above applied?** A plain HTTP
   fetch cannot execute JavaScript. Try the **WebFetch tool** on the same
   URL first - it renders some JS-heavy pages where a raw fetch sees
   nothing (confirmed directly: a Juniper-CMS page that returned an empty
   shell via `requests` was fully readable through WebFetch). If that also
   comes back empty, check whether a browser-automation tool is already
   connected in this session (e.g. a Chrome extension) and use it to read
   the rendered page. If none of that is available, say plainly that the
   page needs JavaScript to render and offer: paste the visible text,
   provide a different URL (often a direct PDF link exists even when the
   main page doesn't render), or enter dates manually.
6. **Manual entry.** Always available as a last resort - never fabricate
   or guess a date.

After extraction, run `validate_events.py` on the raw event list before
showing it to the user - it catches mechanical mistakes (a start date after
its end date, overlapping ranges in the same category, a date nowhere near
the target academic year) that extraction errors tend to produce. It's a
safety net alongside the "does this look right?" human review, not a
replacement for it.

## Category vocabulary

Schools use inconsistent language for the same thing. Normalize to these
categories so matching/diffing (see below) and the config schema stay
consistent regardless of a school's own wording:

| Category | School's wording might be |
|---|---|
| `term` | "Autumn Term begins/ends", "Term starts", "First day of term" |
| `half_term` | "Half Term", "Half-term", "October break", "Mid-term break" |
| `holiday` | "Christmas Holiday", "Easter Holidays", "Summer Holidays" |
| `inset` | "INSET Day", "Training Day", "Staff Development Day", "Professional Development Day", "PD Day" - all mean "no pupils" |
| `bank_holiday` | (computed by `uk_bank_holidays.py`, not scraped) |
| `manual` | anything the user added themselves that isn't on the school's page at all |

## How UID stability actually works across `>refresh`

Format is `[school-slug]-NNNN@school-calendar`, but stability comes from
matching, not from the number itself. Each event has a semantic `event_id`
(category + term name + normalized summary + the event's academic year, via
`_common.event_id()`) - stable across refreshes even though the exact day
moves. The academic year is part of the key deliberately: a school
publishes dates a year or two ahead, so it's normal for one config to hold
several academic years of events at once (this is exactly what the
project's own real production calendars look like), and without a year
component, "Michaelmas Term begins" in 2025 and the identical label in 2026
would collide onto the same id - refresh-matching could then silently
update the wrong year's event. `>refresh` matches a freshly re-scraped
event back to its existing config entry in two passes (`compare_dates.py`):

1. Exact `event_id` match.
2. Fallback: within the same category, nearest `start_date` (within 14
   days) plus a summary-similarity check - needed for generically-labelled
   repeats like several undifferentiated "INSET Day" entries, where
   `event_id` alone can't tell them apart.

A matched event keeps its existing UID; only a genuinely new event gets a
freshly allocated one. This is what stops subscribers from seeing duplicate
events every time the calendar is regenerated.

## Deliberately out of scope

- **OCR for scanned/image-only PDFs or images.** Real dependency weight
  (a system Tesseract install, not just a pip package) for something that
  didn't come up once across 8 real schools tested. If a PDF turns out to
  be a scan, `extract_pdf_text.py` flags it and the skill asks the user to
  paste the text or enter dates manually instead.
- **Cross-referencing multiple sources for one school** (e.g. comparing a
  PDF against a news post against a newsletter). Interesting idea, real
  added complexity for a personal/parent tool - a human already reviews the
  final list before anything is generated, which catches the same class of
  discrepancy more simply.
- **A formal numeric "confidence score".** The "does this look right?"
  human confirmation step already serves as the real confidence gate, and
  is more honest than an opaque number would be.
