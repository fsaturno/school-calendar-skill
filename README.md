# School Calendar Publisher

A Claude Code / Cowork skill that turns a UK school's term-dates webpage
into a shareable `.ics` calendar - the kind other parents subscribe to
*once* and it just keeps itself up to date, instead of a file they have to
re-download every time the school changes something.

It handles school websites that publish dates as plain HTML tables, prose
paragraphs, PDF attachments, Word documents, or an already-published `.ics`
feed - and it's built so that Claude reads the messy real-world page itself
rather than relying on a rigid parser tuned to one school's website, which
is what lets it work on a school nobody's tested it against.

> This skill makes a good-faith effort to keep calendars accurate, based on
> the dates published on each school's official website - but it's
> provided as a convenience, not a guarantee. Always verify important
> dates independently with the school directly.

## Installing

Download `school-calendar.skill` from the
[latest release](https://github.com/fsaturno/school-calendar-skill/releases/latest),
then open it in Claude Code or Cowork and use the "Save skill" option to
install it into your profile.

(If someone sent you the `.skill` file directly instead, e.g. over
WhatsApp, do the same thing - open it and "Save skill".)

Once installed, just run:

```
/school-calendar
```

and follow the prompts - it takes about 2 minutes for a first calendar.

## Choose how you'll run it: EASY or ADVANCED

Before anything else, decide how automated you want date-checking to be -
the skill asks you this same question the first time you run it, but it's
worth knowing up front:

**🟢 EASY - recommended for most people, especially in Cowork.**
No coding background needed. You check for date changes yourself, whenever
you want (e.g. once a term), just by asking - the skill walks you through
everything else, including publishing/sharing the calendar. There's no
automatic background checking on this path, so nothing runs unless you ask
it to.

To set this up:
1. In Cowork, create a new project - call it something like "School
   Calendars".
2. Link that project to a folder on your computer where you'd like the
   generated calendar files saved. (The skill can't create this project or
   link for you - that's a Cowork step you do once, yourself.)
3. Open a new chat inside that project and type `>setup`.

Everything the skill creates (your school configs, the `.ics` files, the
WhatsApp messages) will then live inside that linked folder, so it stays
with the project across sessions instead of depending on Cowork's own
temporary storage.

**🔵 ADVANCED - for Claude Code, if you want it fully hands-off.**
Runs on your own computer via Claude Code (not Cowork) and sets up a real
scheduled check - termly or monthly - that runs automatically in the
background, even when you're not using Claude, so you never have to
remember to check yourself. This needs Claude Code installed locally
rather than Cowork, and a bit more comfort with your computer generally
(the skill still walks you through the setup itself).

Not sure which? Start with EASY. You can always move to ADVANCED later by
running the skill from Claude Code instead of Cowork.

## What you'll need

- **Claude Code or Cowork**, with this skill installed (see "Installing"
  above) - whichever matches the EASY/ADVANCED choice above.
- **A URL**: either the school's specific term-dates page, or just the
  homepage (the skill will look for the right link itself).
- **Python 3.** The skill checks for a few small helper libraries on first
  run and offers to install anything missing automatically - including
  falling back to a private virtual environment if your system Python
  refuses direct installs (common on modern macOS/Linux, sometimes called
  "externally managed"). You don't need to do anything about this yourself;
  the skill handles it and tells you what it did.
- **A way to publish the file** - pick whichever fits you:
  - **Google Drive (most parents).** Works with your own Google account.
    If Claude has a Google Drive connector available, the skill can use it
    directly; otherwise it walks you through uploading the file manually -
    no connector required either way.
  - **Self-hosting (school admins/head teachers).** If you're publishing on
    behalf of the whole school and the school already has a website,
    hosting the `.ics` file there directly is often simpler than Google
    Drive and looks more official to parents. Once installed, the skill
    walks you through this itself (`references/self_hosted_setup.md`
    ships inside the `.skill` file).

Note that a skill can't connect a new Google Drive/email account to Claude
on its own - that's an account-level setting you turn on in Claude Code's
or Cowork's own UI beforehand, if you want to use a connector. Without one,
everything above still works manually.

**Model recommendation:** Sonnet at high/extra reasoning is sufficient for
normal use, and is what this skill was built and validated against
end-to-end. On the ADVANCED path, consider Opus at high reasoning
specifically for the scheduled runs - they run unattended and un-reviewed,
so the extra reasoning budget is worth it there even though it's not
needed for everyday use. This is a recommendation, not a requirement.

## Commands

Type `>help` any time to see this list again. Most take a `[school]` name
if you have more than one configured - the skill will ask if it's not
clear which one you mean.

| Command | What it does |
|---|---|
| `>help` | Show this list of commands. |
| `>setup` | First-run setup (EASY vs ADVANCED) - only appears if nothing's configured yet. |
| `>add` | Add another school. |
| `>refresh [school]` | Check the school's website again for date changes, and offer to update the calendar. |
| `>add-event [school]` | Add your own events (bake sales, PTA meetings, etc.) - see below. |
| `>remove-event [school]` | Remove or hide an event. |
| `>remove [school]` | Delete a school and its calendar from this skill entirely. |
| `>verify [school]` | Quick check that the shared calendar link still works, without re-checking the school's website. |
| `>refresh-schedule [termly\|monthly\|cancel] [school]` | Turn automatic checking on, change it, or turn it off (ADVANCED/Claude Code only). |
| `>show-schedule` | See what's currently set to check automatically. |
| `>status` | See all your schools, when each was last checked, and whether the last automatic check notified you. |
| `>instructions [school]` | Regenerate the WhatsApp message and import instructions to share with parents. |
| `>unschedule [school]` | Same as `>refresh-schedule cancel`. |

## Adding your own events (bake sales, PTA meetings, etc.)

You're not limited to whatever the school's website publishes. During
setup (or any time after, with `>add-event`), you can add events that
aren't on the school's page at all - paste as many as you like in one go:

```
13-07-2026 Summer Fair
30-10-2026 Harvest Festival
11-04-2026 Parents Drinks
```

The skill checks each one against what's already on the calendar first, so
running this twice by mistake won't create duplicate entries.

**Your own additions never get removed by the automatic refresh check** -
they're not on the school's page, so there's nothing to compare them
against; they just stay on the calendar until you change or delete them
yourself.

**If you correct a date because the school's website had it wrong, that
correction sticks.** It will only ever be replaced if the school's own page
later shows a genuinely *different* date - and even then, you'll be shown
the change and asked before anything is applied. A refresh that just
re-confirms the same old (still wrong) value from the school's page will
never silently overwrite your correction.

## Sharing this skill with other parents

If another parent wants to run this for their own school (rather than just
subscribing to a calendar you've already made - see the WhatsApp message
the skill generates for that), just send them the link to this repo, or
the `.skill` file directly over WhatsApp/email if that's easier - no
Google Drive sharing permissions to sort out, the file is tiny. They'll
still need Claude Code or Cowork installed first; getting the file to them
is the easy part.

## License

Creative Commons Attribution-NonCommercial 4.0 (CC BY-NC 4.0) - see
[LICENSE](LICENSE). Free to use and adapt for personal/non-commercial
purposes; please keep credit to Fernando Saturno.

## Support

If for any reason this doesn't work for your school, contact
**hello@fernandosaturno.com**.
