# Publishing via self-hosting (school admin / head teacher option)

This is publish option **C**: for someone running this skill in an official
capacity for the whole school (a school administrator, office manager, or
head teacher), rather than a single parent sharing with their own contacts.
If the school already has a website, hosting the `.ics` file there directly
is often simpler than Google Drive and looks more official to parents.

## Steps

1. Hand over the generated `.ics` file (e.g. "Example Primary School
   - Calendar.ics").
2. Explain what they need to do on their end:
   - Upload the file to the school website (via whatever the school's CMS
     file manager / media library is - WordPress's Media Library, or
     equivalent).
   - Note the direct URL to the uploaded file (it should end in `.ics` and
     download/display the raw file content when visited directly - not a
     page that merely links to it).
3. **Emphasize the stability requirement** just as strongly as the Google
   Drive path: whatever URL the file ends up at must **never change**,
   even when term dates are updated later in the year. Parents' calendar
   apps will be polling that exact URL indefinitely. Concretely:
   - If the CMS allows "replace file" / "upload new version" while keeping
     the same URL, use that for every future update.
   - Avoid CMSs that append a new random filename/ID on every upload
     (common with some media libraries) - if that's unavoidable, the
     school needs a stable redirect or a fixed page that always points at
     the current file.
4. Once they paste back the live URL, that string becomes the
   `subscription_url` directly - no Google-Drive-style ID rewriting needed.
5. Run `verify_subscription_url.py --url <that URL>` before confirming
   success, exactly as with the Google Drive paths. Common failure modes
   here:
   - The CMS serves an HTML preview page instead of the raw file (check for
     a "download" or "raw" link variant).
   - The file was uploaded but isn't public yet (some school CMSs require a
     separate "publish" step, or restrict media library files to logged-in
     staff by default).

## Config fields set by this path

```json
"hosting_type": "self_hosted",
"published_by": "school_admin",
"google_drive_file_id": null,
"self_hosted_url": "https://www.exampleschool.org.uk/files/term-dates.ics",
"subscription_url": "https://www.exampleschool.org.uk/files/term-dates.ics"
```
