---
name: school-calendar
description: Build and maintain a subscribable school-calendar (.ics file) for a UK school - scrapes term dates, half-terms, holidays, INSET days and UK bank holidays from the school's website (HTML, PDF, Word doc, or an already-published .ics feed), publishes it via Google Drive or a self-hosted URL so other parents can subscribe and get automatic updates, and checks termly/monthly for date changes. Use this whenever the user wants to create, share, or publish a school term-dates calendar, mentions "/school-calendar", asks to turn a school's term-dates page into an ICS/calendar file other parents can subscribe to, wants a WhatsApp-shareable school calendar link, or issues one of this skill's own chevron commands (setup, refresh, add, status, verify, instructions, refresh-schedule, show-schedule) - even if they don't use the word "skill" or name this skill directly.
---

# School Calendar Publisher

Turns a school's term-dates webpage into a subscribable `.ics` calendar that
parents can add once and never think about again - it auto-updates because
it's a genuine calendar *subscription*, not a one-off file they re-download.

**Audience is parents, not developers.** Plain English throughout, minimal
jargon, confirm each major step before moving to the next. If scraping
fails or dates look wrong, always offer a clear way forward (different URL,
manual entry) rather than a dead end.

**Hard constraint, never break this**: this skill never modifies anything
on Google Drive automatically. The user always uploads/re-uploads
themselves. Once a subscription URL has been shared with parents, its
underlying file ID/URL must never change - updates overwrite the same file,
never delete-and-recreate.

Detailed references (read these when the relevant step comes up, not all
upfront):
- `references/scraping_playbook.md` - the extraction fallback chain, why
  there's no per-CMS parser, category vocabulary, UID-matching algorithm.
- `references/ics_format.md` - exact RFC5545 rules `generate_ics.py` enforces.
- `references/google_drive_setup.md` - Option A/B publish steps in detail.
- `references/self_hosted_setup.md` - Option C (school admin) publish steps.

Config for each school lives at `~/.school-calendar/[school-slug]/config.json`
by default - except for an **EASY-mode** install (see `>setup` below), where
it instead lives at `<project-folder>/.school-calendar/[school-slug]/config.json`,
so it stays with the Cowork project itself rather than depending on the
sandbox's own home directory. Generated files go to
`~/Documents/School Calendars/[school name]/` by default (ask if the user
wants somewhere else).

---

## First run / `>setup`

**0. First-run gate - always check this before anything else below**

This determines whether to show the EASY/ADVANCED menu at all. **The menu
must never appear for an install that already has configured schools** -
that's a hard requirement, not a nice-to-have; getting this wrong means
re-onboarding someone who's already set up and running.

Check, in order:
1. Does `./.school-calendar/` (relative to the current working directory)
   contain any `<slug>/config.json`? If so, this is an **existing
   EASY-mode install** - use `SCHOOL_CALENDAR_HOME=$(pwd)/.school-calendar`
   as an env var prefix on every `scripts/*.py` call for the rest of this
   session, skip the menu entirely, and go straight to the normal flow
   below (treat it exactly like any other existing install from here on).
2. Else, does `~/.school-calendar/` contain any `<slug>/config.json`? If
   so, this is an **existing ADVANCED-mode (or pre-Fix-4) install** - no
   env var override needed, skip the menu, go straight to the normal flow.
3. Else - truly nothing configured anywhere - this is a genuine first run.
   If the user typed `>setup` explicitly, or this is the very first
   `/school-calendar` invocation with nothing found above, show the menu:

```
📅 Welcome to School Calendar Publisher - first-time setup

  1) EASY Setup (recommended if you're not technical)
     Best inside a Cowork project. Manual refresh only - you run
     >refresh yourself whenever you want to check for date changes
     (e.g. start of each term). No automatic scheduling.

  2) ADVANCED Setup
     Best in Claude Code. Fully automated: sets up a scheduled check
     (termly or monthly) that runs unattended in the background and
     only asks you to step in when something actually needs a human
     (reviewing a change, re-uploading the file).
```

Also run `python3 scripts/check_dependencies.py` proactively at this point
(don't wait on it before showing the menu) and mention plainly whether a
Google Drive or email connector is available this session - since a skill
can't connect a new one on the user's behalf (that's an account-level
setting in Claude Code's/Cowork's own UI), explain the manual-publish
alternative (Option B in `references/google_drive_setup.md`) and
self-hosting (`references/self_hosted_setup.md`, Option C) clearly rather
than implying a connector is required either way.

If **1) EASY** is chosen: set `SCHOOL_CALENDAR_HOME=$(pwd)/.school-calendar`
for every script call from here on (this session and, per the gate check
above, automatically detected again in any future session run from the
same project folder). Continue to step 1 below, but skip the automatic
refresh-cadence offer in step 9 entirely - manual `>refresh` only, per the
EASY-mode design.

If **2) ADVANCED** is chosen: no env var override - continue to step 1
below exactly as today, including the step 9 scheduling offer.

**1. Welcome**

```
📅 Welcome to School Calendar Publisher
──────────────────────────────────────────
I'll help you create a shareable school calendar that other
parents can subscribe to. It takes about 2 minutes.
```

**2. Dependency check**

Run `python3 scripts/check_dependencies.py`. Its output includes
`python_interpreter` - **use that exact interpreter path for every other
script call in this session** (it may point at a private venv rather than
the system Python, e.g. when the system Python is externally-managed and
refused a direct install - the script handles that fallback itself). If
anything's missing, explain in one plain sentence ("I need a couple of
small, standard helper libraries - one-time setup") and run with
`--install`.

**3. School info**

Ask:
- "What's the name of your school?"
- "Paste the URL of the school's website OR the specific term-dates page:"

**4. Fetch and extract**

Run `scripts/fetch_page.py --url <url>` (add `--mode crawl` if a homepage
was given). Follow the fallback chain in `references/scraping_playbook.md`:
check for an `.ics`/PDF/Word-doc special case first, then read
`cleaned_text` directly, then PDF/docx extraction, then the JS-render
fallback (try WebFetch on the same URL before assuming it's a dead end),
then manual entry. If homepage crawl mode returns multiple plausible
`keyword_links`, show them and ask which one.

Extract, using the category vocabulary from `scraping_playbook.md`:
- Term start/end dates, labelled by term name where the school uses one
  (Autumn/Spring/Summer, or Michaelmas/Lent/Trinity).
- Half-terms (date ranges).
- Christmas/Easter/Summer holiday periods (date ranges).
- INSET/staff days (single dates, labelled "Staff Day - no pupils").
- UK bank holidays falling in the school year: run
  `scripts/uk_bank_holidays.py --from <academic-year-start> --to <academic-year-end>`
  and merge the results in - don't try to spot these on the page yourself,
  they're computed deterministically.

Store dates as natural **inclusive** ranges (start=first day, end=last
day) - do not pre-compute the RFC5545 exclusive DTEND yourself,
`generate_ics.py` does that conversion.

Run `scripts/validate_events.py --events <list> --academic-year <year>` on
the raw list before showing it to the user. Fix anything flagged as an
`error` (these are mechanically wrong - a start after its end, etc.);
mention any `warnings` if they seem worth double-checking against the page.

**5. Confirm with the user**

```
I found XX events for [school name]:

AUTUMN TERM 2025/26
  🏫 Term begins:        Thu 4 Sep 2025
  📋 INSET Day:          Fri 5 Sep 2025  (no pupils)
  🌸 Half Term:          Mon 27 Oct – Fri 31 Oct 2025
  🏫 Term ends:          Fri 19 Dec 2025
  🎄 Christmas Holiday:  Mon 22 Dec 2025 – Fri 2 Jan 2026
[... etc ...]

Does this look right? (yes / edit / retry with different URL)
```

- **edit**: covers correcting a date/label, removing an item that doesn't
  apply, *or* adding something the school's page doesn't list at all (a
  bake sale, PTA meeting, non-uniform day - see "Manual events" below).
  This is the natural place for ad-hoc additions, not a separate flow.
- **retry**: ask for a different URL, go back to step 4.
- **yes**: continue.

**6. Generate the config and the ICS file**

Build the canonical event list (see "Config schema" below - each event
gets `source: "scraped"` with `current` and `last_scraped` set identically,
except manually-added events which get `source: "manual"` and
`last_scraped: null`). Allocate a UID per event: `[school-slug]-NNNN@school-calendar`,
sequential from `uid_counter`, starting at 1.

Run `scripts/generate_ics.py --config <config> --out "<output_dir>/[School Name] - Calendar.ics"`.

**7. Publish**

```
To share this calendar so other parents can subscribe and get
automatic updates, I need to save it somewhere with a public link.

  A) Use the Google Drive connector (if connected)
  B) I'll upload it manually to Google Drive myself
  C) I'm the school (admin / head teacher / office) - I'll host this
     on our own website
```

Follow `references/google_drive_setup.md` for A/B, `references/self_hosted_setup.md`
for C. Whichever path, once a `subscription_url` exists:

```
python3 scripts/verify_subscription_url.py --url <subscription_url>
```

If it fails, explain the specific classified reason in plain English and
let them retry after fixing it (don't just say "verification failed").

**8. Sharing files**

Ask for the user's name and (optionally) a contact method for the sign-off.
Generate, into `output_dir`:

1. `[School Name] - WhatsApp Message.txt`:

```
📅 *[School Name] — Term Dates [YEAR]–[YEAR]*

I've put together a calendar with all the school dates (term
start/end, half terms, holidays and INSET days). Add it once
and it updates automatically if any dates change.

---
*Step 1 — COPY this link:*
[subscription_url]

---
*Step 2 — Follow the instructions for your device:*

*📱 iPhone / iPad*
1. Open the *Calendar* app
2. Tap *Calendars* at the bottom
3. Tap *Add Calendar → Add Subscription Calendar*
4. Paste the link → tap *Subscribe*

*💻 Mac*
1. Open *Calendar* app
2. Menu bar: *File → New Calendar Subscription*
3. Paste the link → click *Subscribe*

*🤖 Android / Google Calendar*
1. Go to *calendar.google.com*
2. Tap *Other calendars → From URL*
3. Paste the link → tap *Add calendar*

---
A new *"[School Name]"* calendar will appear in your list —
you can turn it on/off anytime.

Got stuck? Message me 😊
[User's name]
```

2. `[School Name] - Import Instructions.md` - the same device steps, more
   verbose, for less tech-savvy parents (spell out every tap, add a
   troubleshooting section: "nothing showed up" → check they subscribed
   rather than downloaded a one-off copy; "dates look wrong" → tell them to
   ping the person who shared it, since updates go out automatically).

**9. Automatic refresh checks**

**Skip this step entirely for an EASY-mode setup** (see `>setup` above) -
manual `>refresh` only is the whole point of that path; don't promise a
cadence a Cowork sandbox can't reliably back. Go straight to step 10.

For an ADVANCED-mode (or pre-Fix-4 default) setup, ask:
```
I can set up an automatic check that re-scrapes the school website and
tells you if any dates have changed, so you can update the calendar and
re-share.

  A) Yes - termly (beginning of Sep/Jan/Apr - matches when schools publish/revise dates)
  B) Yes - monthly (beginning of every month)
  C) No thanks - I'll run >refresh manually when needed
```

For A/B, run:
```
python3 scripts/schedule_refresh.py --school-slug <slug> --cadence termly|monthly
```
Explain plainly: this runs `claude -p ">refresh <slug>"` locally on their
machine at 09:00 on the scheduled dates. On macOS this is a launchd
LaunchAgent: if the machine is asleep at the scheduled time, it fires once
shortly after the machine next wakes/logs in - it still won't run while
the machine is fully powered off, only catching up at next wake. (On
Linux this still runs via cron, which has no catch-up at all - a missed
run there is simply skipped.) It **only checks and reports** - it
never touches Google Drive or the self-hosted file automatically; the user
always re-uploads by hand after reviewing what changed. Mention `>refresh-schedule`
and `>show-schedule` for changing/checking this later. Since these runs are
unattended and un-reviewed, Opus at high reasoning is worth considering here
specifically - a recommendation, not a requirement.

If A/B was chosen (macOS only - this whole notification step is a no-op on
other platforms), also ask how they'd like to hear about it when a
scheduled run finds a change:
```
  A) Email me (uses a connected email tool if this session has one, else
     sends via Mail.app if you use it)
  B) Just a local notification on this Mac when a run finds something
  C) No notification - I'll check >status myself
```
Save the choice as `notification_preference` in config: `"email"` /
`"local_only"` / `"none"`. This only affects *unattended scheduled* runs -
an interactively-run `>refresh` already shows its result directly in the
conversation, no separate notification needed.

**10. Save config, confirm**

Save via the config schema below (atomic write - see `_common.save_config_atomic`
if writing this by hand instead of through a script).

```
✅ Done! Here's what was created:
  📄 [School Name] - Calendar.ics
  📄 [School Name] - WhatsApp Message.txt
  📄 [School Name] - Import Instructions.md

Subscription URL (share this with parents):
  [subscription_url]

Run >refresh any time to check for date changes.
Run >status to see all configured schools.
Run >help to see every command.
```

---

## Subsequent runs (config already exists)

List existing school(s) with `last_updated`, offer: check for changes
(`>refresh`) / add another school (`>add`) / regenerate sharing
instructions (`>instructions`) / add a manual event (`>add-event`).

---

## Manual events - the precedence rule

A parent might want events on this calendar that the school's page never
mentions (a bake sale, a PTA meeting) - or might need to correct a date the
school's page had wrong. Both go through the same mechanism: adding/editing
an event with `source: "manual"` (for a brand new one) or setting
`manually_edited: true` (for a correction to a scraped one).

The rule, in priority order, for what wins on a later `>refresh`:

1. **The school's own page shows a genuinely new/different value** for
   that same event → this wins, surfaced as a normal diff for the user to
   confirm ("school now shows X, you'd corrected this to Y - apply the
   school's update?").
2. **The user edits it again themselves** → this obviously wins, it's the
   most recent instruction.
3. **Anything else** (a refresh that just re-confirms the same old value
   the school already had) → the manual value is left completely alone.

This works because `compare_dates.py` diffs a fresh scrape against each
event's stored `last_scraped` baseline, never against `current` (the
possibly-manually-overridden value actually rendered into the ICS). A
purely manual event (no school-page counterpart at all, like a bake sale)
has no `last_scraped` to compare against, so it simply persists forever
until the user changes it. Full mechanics in `references/scraping_playbook.md`.

### Adding events: accepts a list, checks for duplicates first

**Always confirm which school before doing anything else, unless it's
completely unambiguous.** `>add-event [school]` takes a school argument for
exactly this reason - don't guess from a vague reference ("the primary
school", "St Mary's") when more than one configured school could match.
This is a real, not hypothetical, risk once several schools are configured
- imagine a project with both `st-marys-primary` and `st-marys-secondary`
configured, two different schools with near-identical names. Ask, using a
distinguishing detail (address/postcode, full official name) if the user's
reference doesn't already disambiguate on its own.

`>add-event` (and the "edit" path during initial setup) takes events in
either of two forms:

**Form 1 - pasted text, one or many events in a single message**, date
first, then the event name:

```
>add-event <school>
13-07-2026 Summer Fair
30-10-2026 Harvest Festival
11-04-2026 Parents Drinks
```

Parse each line yourself (day-first date, e.g. `DD-MM-YYYY`; the rest of
the line is the summary) into a candidate event - no dedicated parsing
script needed, this is plain text.

**Form 2 - a URL to a list**, e.g. a PTA fundraising spreadsheet:

```
>add-event <school> <url>
```

Run `scripts/fetch_event_list.py --url <url>` to turn it into structured
rows - it handles a Google Sheets link (tries the public CSV export first;
if the sheet isn't shared "Anyone with the link" it reports
`requires_drive_tool: true` instead of silently failing - fall back to a
connected Google Drive tool in the current session if one's available,
e.g. `download_file_content` with the given `sheet_id` and
`exportMimeType: text/csv`), a direct `.xlsx` link, or a direct `.csv`
link. The script only fetches and structures the rows (using the sheet's
own column headers) - it does not decide which columns matter or what
counts as a valid date. That interpretation is yours, the same judgment
you'd apply reading any other messy real-world source in this skill:

- **Only look at columns that actually mean date/event/time** - a
  real-world sheet's headers won't always be named exactly that (confirmed
  directly: one real sheet used `DATE, EVENT, VOLUNTEERS, TIME, LOCATION`
  - `VOLUNTEERS` and `LOCATION` are irrelevant here). Match by meaning, not
  by exact header text.
- **Ignore rows without a specific, parseable date.** Section-header rows
  (a bare month name like "SEPTEMBER"), blank rows, and rows with a vague
  date ("Fri", "Sat", or no date at all) are skipped, not guessed at.
- **A "date to date" row is a multi-day event** - e.g. "02-Nov-2026 to Fri
  06-Nov-2026" becomes one event spanning that range, not two events.
- **Events stay all-day, but a valid time gets folded into the title.**
  Look at the TIME column (or whatever column means that, by meaning not
  exact header text). Run it through `_common.format_time_suffix()`, which
  only accepts strict 24h format - a single time (`8:00`, `17:45`) or a
  window (`18:00-20:00`) - and returns `None` for anything else (blank, a
  vague note like "TBC" or "at drop off", or a non-24h value like
  "6:00-8:00pm" - confirmed directly against a real sheet that had exactly
  that value; it's correctly rejected rather than guessed at as either
  6am or 6pm). When it returns a suffix, append it to the event summary:
  `[Event Title] (18:00)` for a single time, `[Event Title] (18:00-20:00)`
  for a window. Never turn this into a real ICS time-of-day field - the
  event itself stays all-day either way; only the title text changes.

**Classify each candidate's category the same way you would when
scraping, and hard-exclude anything official-shaped before it ever reaches
the duplicate check.** Lists like a PTA fundraising spreadsheet mix two
fundamentally different kinds of content: genuine parent-organised events
(bake sale, coffee morning, auction, prayer group, AGM, class trip - these
are always fine as manual additions), and restatements of official school
milestones (term begins/ends, half-term, holidays, INSET days - these must
ALWAYS come from the official scraped calendar, never from a parent list,
even when the list's own date differs from what's officially scraped). Use
the category vocabulary from `scraping_playbook.md`: if a candidate's
content genuinely describes a `term`, `half_term`, `holiday`, `inset`, or
`bank_holiday`-type milestone, exclude it outright - don't add it, and
don't run it through the duplicate check at all, regardless of whether its
date happens to collide with anything already on the calendar. This is a
category judgment, not a date-matching one: a parent list's "Half Term:
23 Oct" naming a different date than the real official half-term (26-30
Oct) is not license to add a second, conflicting "Half Term" entry - it's
still official-shaped content, so it's excluded either way. If a listed
date genuinely conflicts with what's officially scraped, that's a signal
to run `>refresh` and check the real source, not to trust the parent list.
Only candidates that describe something the school's own term-dates page
would never mention proceed past this filter.

**Then, before adding anything, check for duplicates** among what's left -
re-running `>add-event`
with the same list, or pasting it twice by mistake, should never silently
create two copies of the same event. Run:

```
python3 scripts/check_duplicates.py --config config.json --new-events <candidates>
```

This reports, per candidate, any existing (non-suppressed) event sharing
the exact same date, with a text-similarity score against its summary, and
a `recommended_action`:

- **`skip_official_duplicate`** - collides with an official (`source:
  "scraped"`) event at high similarity. **Hard rule: never add this, and
  never adjust the official event's date to match the new source.** Lists
  a parent hands you (a fundraising spreadsheet, a WhatsApp thread) often
  restate official dates for reference - "04 Sep - Start of Term" sitting
  alongside genuine fundraising events - and if that restated date is
  stale or was copy-pasted from a different year, it must never be allowed
  to shadow or override the real scraped date. Silently skip these; a
  one-line summary at the end ("skipped N dates that duplicate the
  official calendar") is enough, no need to ask per-item.
  **The similarity score under-catches paraphrased restatements** -
  confirmed directly: "Start of the Term" scored only 0.44 against the
  real scraped "Autumn Term begins" on the exact same date, well below the
  0.6 cutoff, despite obviously being the same milestone. So: whenever a
  candidate's date exactly matches a `source: "scraped"` event's date at
  all, read both summaries yourself regardless of what `recommended_action`
  says - if they clearly describe the same real-world moment (term
  start/end, half-term, INSET), treat it as a duplicate and skip it, same
  as if the script had caught it. Only trust `add` at face value when
  there's no same-date scraped event to compare against in the first
  place.
- **`review`** - collides with an existing MANUAL event at high similarity
  (e.g. re-running `>add-event` with the same list twice). Ask the user:
  skip it, add anyway (genuine second entry), or did they mean to correct
  the existing one.
- **`add`** - no high-similarity collision. A same-day collision may still
  be listed for context (e.g. a bake sale falling inside an existing
  half-term) but that's completely normal, not blocking - add it straight
  away.

Every accepted event gets `source: "manual"`, `last_scraped: null`, a fresh
UID from `uid_counter`, then `generate_ics.py` regenerates the file.
`>add-event` never modifies an existing scraped event's `current` fields -
that's `>refresh`'s job, via the precedence rule above, and only ever after
the user confirms.

---

## Chevron commands

| Command | Behavior |
|---|---|
| `>refresh [school]` | Re-run the fetch/extract fallback chain, **and** re-run `scripts/uk_bank_holidays.py` for the same academic year, merging its output into the freshly-scraped event list exactly as in initial setup - bank holidays are recomputed, not scraped, but `compare_dates.py` has no way to know that unless they're included every time. Forgetting this step makes every bank holiday falsely show up as "removed" on every single refresh, since they'd be absent from `--new-events` entirely. Run `compare_dates.py` against the school's config with that merged list. Show what changed (school-side changes only - manual-only divergence is never shown, per the precedence rule). Ask to apply. Regenerate the ICS, **overwriting the same local file**. Remind the user to re-upload/overwrite the same Drive file or self-hosted URL - never delete+recreate. Offer to re-run `verify_subscription_url.py --compare-to <local ics>` once they confirm the re-upload finished. **If this is an unattended scheduled run** (invoked non-interactively, e.g. by launchd) **and a change was found and `notification_preference` isn't `"none"`**: attempt the fallback chain from Fix 2 - try a connected email/Gmail MCP tool first if `notification_preference` is `"email"` and one is available this session (catch and ignore any error from it, e.g. missing permissions, rather than letting it fail the refresh); otherwise shell out to `python3 scripts/notify.py --school-slug <slug> --school-name "<name>" --to <user_contact> --summary "<short summary of what changed>" --preference <notification_preference>`. Record in `refresh-log.txt` which method actually got through (`notified via: email` / `notified via: local notification` / `no notification available`), so `>status` can report it honestly instead of assuming success. |
| `>setup` | Explicit first-run entry point (EASY vs ADVANCED) - see "First-run gate" above. **Never shows the menu if any school is already configured** (locally or at `~/.school-calendar/`); falls through to the normal existing-schools flow instead. |
| `>add` | Add a new school - repeats the first-run flow under a new slug. |
| `>add-event [school] <url>` | Add one or more events for your school: (e.g. manually "13-07-2026 Summer Fair" or provide a `<url>` to an xls file with a list of events) |
| `>remove-event [school]` | Remove a manual event, or suppress a scraped one that doesn't apply (marked `suppressed`, not deleted, so it can't spuriously reappear as "new" on the next refresh - same precedence rule applies to it too). |
| `>remove [school]` | Delete a school from config entirely. |
| `>verify [school]` | Re-check the live subscription URL without re-scraping - fast diagnostic when a parent reports the calendar isn't showing up. |
| `>refresh-schedule [termly\|monthly\|cancel] [school]` | Set, change, or cancel the automatic refresh cadence for a school. Calls `schedule_refresh.py --cadence <x>` or `--remove`. If the school isn't specified and there's more than one configured, ask which. |
| `>show-schedule` | Show what's currently scheduled, for which school(s), via `schedule_refresh.py --list`. |
| `>status` | List all configured schools, last refresh check, last URL verification, scheduling cadence, and (if a scheduled run has fired) last notification outcome - read from `refresh-log.txt`, e.g. "last notified via: email" / "local only" / "no notification available". Never assume a notification succeeded just because scheduling is set up. |
| `>instructions [school]` | Regenerate the WhatsApp message + Import Instructions from current config, no re-scrape. |
| `>unschedule [school]` | Alias for `>refresh-schedule cancel` - kept for discoverability. |
| `>help` | Show this table. |

---

## Config schema

```jsonc
{
  "schema_version": 2,
  "school_name": "Example Primary School",
  "school_slug": "example-primary-school",
  "academic_year": "2025-26",
  "dates_url": "https://www.exampleschool.org.uk/term-dates",
  "dates_source_detail": {
    "method": "html" | "pdf" | "docx" | "ics_feed" | "browser_fallback" | "manual_paste" | "manual_entry",
    "document_urls": []
  },
  "user_name": "Jane Smith",
  "user_contact": "jane@example.com",
  "output_dir": "/Users/you/Documents/School Calendars/Example Primary",

  "hosting_type": "google_drive" | "self_hosted",
  "published_by": "parent" | "school_admin",
  "google_drive_file_id": "FILE_ID_EXAMPLE",
  "self_hosted_url": null,
  "subscription_url": "https://drive.google.com/uc?export=download&id=...",
  "subscription_url_last_verification": {"ok": true, "http_status": 200, "reason": null},

  "last_updated": "2026-07-04T12:00:00Z",
  "last_refresh_checked": "2026-07-04T12:00:00Z",
  "uid_counter": 27,

  "scheduling": {"mechanism": "launchd" | "cron" | "schtasks" | "none", "cadence": "termly" | "monthly" | null},
  "notification_preference": "email" | "local_only" | "none",

  "events": [
    {
      "event_id": "half_term-autumn",
      "uid": "example-primary-school-0007@school-calendar",
      "category": "term" | "half_term" | "holiday" | "inset" | "bank_holiday" | "manual",
      "term_name": "Autumn",
      "source": "scraped" | "manual",
      "current": {"summary": "Half Term", "start_date": "2025-10-27", "end_date": "2025-10-31"},
      "last_scraped": {"summary": "Half Term", "start_date": "2025-10-27", "end_date": "2025-10-31"},
      "manually_edited": false,
      "suppressed": false
    }
  ]
}
```

Use `scripts/_common.py`'s `load_config` / `save_config_atomic` (atomic
write - temp file + rename, so a crash mid-write can never corrupt an
existing config) rather than reading/writing the JSON file directly.
