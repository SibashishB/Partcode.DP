# JEVBP / JBESS Part Code Generator — v8 (MVP7)

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

**First start:** there is no default password. On a fresh database the app
creates an Admin account `Master` with a **random temporary password**, prints
it once in the console and saves it to `initial_admin_password.txt`. Sign in
with it, you are made to choose your own password straight away, and the file
is deleted automatically. (To set the first password yourself instead, start
with the `INITIAL_ADMIN_PASSWORD` environment variable - you are still made to
change it.)

**Upgrading from an earlier version:** copy your existing `partcodes.db` into
this folder before starting. It is upgraded in place, nothing is lost, and
`Master` is asked to choose a new password once at next sign-in.

## What's new in this version (v5, still applies)

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

## What's new in this version (v7)

- **Clear description after a code is created.** Every code now comes with
  a plain-language breakdown of what it means — e.g.
  `Material: AL - Aluminium | Sub-Type: SO - Solid | Sequence (auto): 001`
  — shown right under the code on Home, and as its own column in History.
- **BMS now has a Series field.** Codes look like `JEVBP-SBMS-RX-S2`. The
  actual series list wasn't specified, so it ships with placeholders
  (Series 1/2/3) — extend via Manage Categories -> Manage options once the
  real series names are known.
- **Busbar is now its own category**, segregated by Material
  (Aluminium/Copper, more addable later) then Sub-Type (Solid/Flexible):
  `JEVBP-04-AL-SO-001`. Removed from the General category's dropdown so
  there's no ambiguous path left that bundles them back together. Note:
  this one sits right at the 18-character ceiling, so Material/Sub-Type
  codes added later need to stay 2 characters to fit.
- **Every category now has a description**, shown under its name in
  Manage Categories. Built-in ones ship with one; Admins can write one for
  custom categories when creating them.
- **Live code preview while building a custom category.** As you add
  fields and fill in options, an example code (using the first option of
  each dropdown) updates live, with a running character count that turns
  red the moment it falls outside 10–18 — so a category that won't work
  is obvious before you save it, not after.

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

## Segregating bundled categories (Insulation, Electrical & Electronic)

Two categories in the source nomenclature sheet bundled several distinct
material types under one flat code with no way to tell them apart once
issued:

- **"03 - Insulation, Plastic, Foam, Gaskets, Epoxy, PC, TIM"** — 7 types
  in one line
- **"06 - Electrical & Electronic parts"** — open-ended, no breakdown given

Both are now their own categories (same treatment `DRAWING` got vs. GA
Drawing) with a **Type** field baked into the code, so e.g. a Gasket and a
Foam part are `JEVBP-03-GKT-00001` and `JEVBP-03-FOA-00001` — distinguishable
at a glance, with independent sequences per type. They're removed from the
General Part Number category's dropdown so there's no ambiguous path left
that bypasses this.

`ELECTRICAL`'s type list (Connector/Switch/Relay/Sensor/Other) is a
starting guess — the real breakdown should come out of the R&D process
study. Extend it anytime via Manage Categories -> Manage options once
the actual sub-types are known; no code change needed for that part.

If other categories (Fabrication, Busbars, Harness) turn out to bundle
multiple types too once the process study is done, the same pattern
applies — say the word and I'll split them out the same way.

## Bug fixed in this pass: auto-sequence numbering for categories with a literal segment

Categories whose code format has fixed text between fields (e.g. the "03"
in `<Project>-03-<Type>-<Sequence>`) were getting duplicate-blocked instead
of incrementing, because the old sequence logic assumed the code started
with the scope values glued directly together. Fixed by deriving the exact
literal prefix/suffix from the actual template instead of guessing it from
scope values — verified each Insulation/Electrical type now gets its own
independent, correctly incrementing sequence.

## Backing up the database

`partcodes.db` is the entire register and user list in one file — back it
up regularly. `backup_db.py` is included for this: it uses SQLite's
built-in online-backup API (safe to run even while the app is live and
someone's mid-creating a code), keeps 30 days of dated copies in
`backups/`, and prunes older ones automatically.

Run by hand:
    python backup_db.py

Or schedule it (recommended so it's not something to remember):
    Windows -> Task Scheduler -> daily -> `python C:\path\to\backup_db.py`
    Linux   -> crontab -e -> `0 2 * * * cd /path/to/app && python3 backup_db.py`

Point `BACKUP_DIR` in the script at a synced/network folder if possible —
a backup sitting on the same disk as the original doesn't help if that
disk fails.

## Security configuration

Everything is optional; the defaults are safe for an internal network.

| Environment variable | What it does | Default |
|---|---|---|
| `SECRET_KEY` | Signs session cookies. If unset, a random key is generated once and kept in `.secret_key` beside the app. | auto |
| `SESSION_COOKIE_SECURE` | Set to `1` **once the app is served over HTTPS** so the cookie is never sent over plain HTTP. Leave off on an HTTP-only setup or sign-in will stop working. | off |
| `TRUST_PROXY` | Set to `1` when behind a reverse proxy (IIS / nginx) so the real client address is used. Without it, every user looks like the proxy and the sign-in limits below would apply to everyone together. | off |
| `SESSION_HOURS` | Signed-in session length (renewed while in use). | 8 |
| `LOGIN_MAX_ATTEMPTS` | Failed sign-ins allowed per address + username within the window. | 5 |
| `LOGIN_MAX_ATTEMPTS_PER_IP` | Failed sign-ins allowed per address across all usernames. | 30 |
| `LOGIN_WINDOW_MINUTES` | Window for the two limits above, and the lockout length. | 15 |
| `INITIAL_ADMIN_PASSWORD` | Temporary first password for `Master` on a fresh database. | random |
| `FLASK_DEBUG` | `1` turns on Flask's debugger. **Local development only**: it can run code on the server. | off |
| `HOST` / `PORT` | Address and port to listen on. | `0.0.0.0` / `5000` |
| `DB_PATH` | Location of the database file. | `partcodes.db` beside `app.py` |

What is enforced:
- Passwords: 10-128 characters, at least one letter and one number, and not
  containing the username. Stored hashed, never in plain text.
- A password an Admin sets for someone (new user or reset) is temporary: that
  person must choose their own at next sign-in. Anyone can change theirs from
  the account menu.
- Repeated wrong passwords lock the sign-in (and the change-password form) for
  a while; an Admin resetting a password lifts the lockout.
- Only an Admin can reset, edit or delete an Admin account. A user who has
  been delegated User Management can manage ordinary users only.
- Session cookie is `HttpOnly` and `SameSite=Lax`; pages and data are not
  cached by the browser; basic anti-clickjacking headers are sent.
- The app creates/upgrades its database on startup however it is launched
  (`python app.py`, waitress, a service).

Not covered yet (see the rollout plan): HTTPS itself (needs a certificate and
a reverse proxy in front), an audit log of who changed which account, and
SSO / email-based onboarding.

## Several people at once

Saving a code is a "look up the next number, then store it" step, and two
people doing that at the same instant used to collide: in a stress test of the
earlier build, only 3 of 40 simultaneous saves succeeded and the rest got an
error page. Now:

- Saving takes the database's write lock first, so people queue (milliseconds)
  instead of colliding. 40 simultaneous busbar codes came out as exactly
  001-040 with no gaps; 25 people requesting the identical code got one code
  and 24 clean "already exists" messages.
- The database runs in WAL mode, so people viewing History / charts never
  block someone saving, and the reverse.
- If two people still save the same thing at the same instant, the second sees
  a plain message (HTTP 409), and if the system is genuinely overloaded they
  see "busy, try again" (HTTP 503) - never a crash page.
- A button disables itself while its request is running, so a double-click
  can't create two codes.
- If the server is killed abruptly mid-save (power cut, `kill -9`) the
  database stays intact: tested with 150 saves in flight, nothing half-written
  or duplicated, numbering resumed correctly after restart.

Practical notes:
- SQLite handles writes one at a time, which is far more than this app needs
  (a save takes milliseconds). It comfortably suits a plant team; if it ever
  needs hundreds of people saving continuously, that is the moment to move to
  a server database.
- Keep `partcodes.db` on the computer's **local disk**. WAL mode does not work
  reliably on a network share / mapped drive.
- WAL mode adds `partcodes.db-wal` and `partcodes.db-shm` beside the database
  while the app runs; that is normal. Do not copy just `partcodes.db` from a
  running app: use `python backup_db.py` (safe while live), or stop the app
  first.
- Run waitress with several threads, e.g. `serve(app, host="0.0.0.0", port=5000, threads=8)`.
- `tools/stress_test.py` repeats the stress test. Run it only against a
  throwaway copy on a fresh database (see the instructions inside the file).

## Still worth deciding

1. Password reset stays admin-manual (no email server in this
   prototype); SSO / email onboarding is the planned replacement.
2. "Edit access" / role changes still use browser `prompt()` dialogs;
   swap for a real modal past MVP.
3. Custom-category auto-sequence numbers run globally per category, not
   scoped to a combination of other field values.
4. Serve it over HTTPS before it is reachable beyond a trusted network,
   then set `SESSION_COOKIE_SECURE=1` (and `TRUST_PROXY=1` if behind a proxy).
