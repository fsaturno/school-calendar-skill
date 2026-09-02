# Publishing via Google Drive

Two ways to get the `.ics` file onto Google Drive, depending on what's
available in the current session.

## Option A - Google Drive connector is available

If a Google Drive tool/connector is connected in this session:

1. Create a folder called "[School Name] Calendar" in the user's Drive.
2. Upload the generated `.ics` file into it, named "[School Name] -
   Calendar.ics".
3. Set sharing to **"Anyone with the link" - Viewer**. (Never "Editor" -
   subscribers only ever need to read it.)
4. Get the file's Drive ID from the upload result or the file's URL.
5. Construct the subscription URL: `https://drive.google.com/uc?export=download&id=FILE_ID`
6. Run `verify_subscription_url.py --url <that URL>` to confirm it's
   actually publicly reachable before telling the user it's done.

## Option B - manual upload

If no Drive connector is available, or the user prefers to do it themselves:

1. Hand the user the local `.ics` file path.
2. Ask them to:
   - Upload it to their own Google Drive (drag and drop into
     [drive.google.com](https://drive.google.com), or use the Drive app).
   - Right-click the file → **Share** → change to **"Anyone with the
     link"** → make sure the role is **Viewer** → **Copy link**.
   - Paste that link back into the conversation.
3. Extract the file ID from whatever link format they paste - the ID is
   the long alphanumeric string, found in either of these patterns:
   - `https://drive.google.com/file/d/FILE_ID/view?usp=sharing`
   - `https://drive.google.com/open?id=FILE_ID`
4. Construct the subscription URL the same way as Option A:
   `https://drive.google.com/uc?export=download&id=FILE_ID`
5. Verify it with `verify_subscription_url.py` before telling the user
   it's done.

## The one rule that matters more than any other

**Once a subscription URL has been shared with parents, the Drive file ID
must never change.** Parents' calendar apps are polling that exact URL
forever. When dates change later (via `>refresh`):

- Regenerate the `.ics` file locally (`generate_ics.py` overwrites the same
  local file).
- Re-upload it to Drive by **replacing the existing file's content** (in
  Drive's web UI: right-click the file → "Manage versions" → upload a new
  version; or simply drag the new file onto the existing one and choose
  "Replace"), which keeps the same file ID and therefore the same
  subscription URL.
- **Never** delete the old file and upload a fresh one - that gets a new
  file ID, silently breaking the link for every parent who already
  subscribed, with no way to notify them.

If the user isn't sure how to replace-in-place, tell them explicitly to
search Drive's help for "upload a new version of a file", not "delete and
re-upload".
