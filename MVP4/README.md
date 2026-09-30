# JEVBP / JBESS Part Code Generator — v5

Flask + SQLite single-page app: auth, role-based module access, an
Admin-only material-category builder (now with per-field option
management), historical-data import, unified code creation, history with
bulk export (txt + Excel), and a live activity chart.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

**Default login:** `Master` / `Master@123` (Admin — change before real use).

## What's new in this version (v5)

- **Drawing / 3D Model category.** One category covers both 2D drawings and
  3D renderings; a *Document Type* dropdown picks which. Codes look like
  `JEVBP-DRW-00001` (2D drawing) and `JEVBP-3DM-00001` (3D model), 15
  characters. Numbering restarts per project and document type. More
  document types can be added later from Manage Categories -> Manage options.
- **Every code must be 10-18 characters (hyphens counted).** Enforced in
  three places: at code creation (over/under-length codes are refused with the
  reason), when an Admin adds a dropdown option (refused if it would let any
  code exceed the range), and when an Admin defines a new category (refused if
  its codes can't fit). Manage Categories now shows each category's length
  range, and the limits live in `CODE_MIN_LEN` / `CODE_MAX_LEN` at the top of
  `app.py` if the standard changes again.
- **Excel export no longer needs any extra package.** It is now built with
  the Python standard library, so it works with only Flask installed. The
  exported sheet has a frozen header, auto-sized columns and a Length column.
  `openpyxl` is now only needed to *import* `.xlsx` files (CSV import needs
  nothing extra).
- **Fastener data fix.** `BOLT` was a group heading in the source nomenclature
  sheet, not a head-style code; it had wrongly been in the Head Style dropdown
  and could push fastener codes to 19 characters. Removed. Codes already issued
  are unaffected.
- **Import now reports off-standard legacy codes** (outside 10-18 characters).
  They are still kept for duplicate checking.

## Earlier changes

- **`requirements.txt` added** (`Flask`, `openpyxl`, `Werkzeug`) — earlier
  versions only documented `pip install flask`, which is exactly why
  Excel export could fail silently if `openpyxl` was never installed.
  Excel export now also surfaces a clear in-app error telling you to
  install it, instead of failing with no explanation.
- **Manage Categories → "Manage options" (Admin-only).** This is the fix
  for "the system runs out once we've used all the codes": you don't need
  to create a whole new category when, say, a new cell supplier gets
  qualified — expand the category, add the new option to the relevant
  dropdown (code + label), and it's immediately available on the Home
  form for everyone. Built-in options (the ones from `rules.py`) are
  shown but can't be removed from here; anything added through this
  panel can be removed again just as easily.
- **Stale-session crash fixed.** If the database gets reset/recreated
  while a browser still has an old session cookie, the app now redirects
  to `/login` (or returns a clean 401 for API calls) instead of crashing
  with a 500.

## On "same material, different project" (still an open decision)

Cell / BMS / Fastener codes are built purely from physical attributes —
no Project field — so the same physical part gets **one shared code**
reused across every project that needs it, by design (that's what
duplicate-checking is protecting). If JEVBP/BESS actually wants separate
codes per project even for an identical part (e.g. for cost-center
tracking), that needs a Project field added into those categories'
formats — flag it and I'll wire it in specifically, since it changes how
duplicate-checking behaves for those categories.

## Historical import (unchanged, still here)

Admin-only, same tab as Manage Categories: upload a `.csv`/`.xlsx` of
your existing part-code list (`code` column required) to seed the
register, so new-code duplicate checks catch collisions with real legacy
data, not just codes created inside this app. Safe to re-run — already-
known codes are skipped, not duplicated.

## Still worth deciding

1. Password reset stays admin-manual (no email server in this
   prototype).
2. "Edit access" / role changes still use browser `prompt()` dialogs;
   swap for a real modal past MVP.
3. Custom-category auto-sequence numbers run globally per category, not
   scoped to a combination of other field values.
4. `app.secret_key` and the default Master password must be changed
   before this touches a real network.
