"""
JEVBP / JBESS Part Code Generator
=================================
Flask + SQLite. Session-based auth, role/module access control, an
Admin-only category builder (add new material types at runtime), and a
JSON API consumed by a single-page app shell (templates/app.html).

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000

First start on a fresh database: an Admin account "Master" is created with a
random temporary password. It is printed once in the console and saved to
initial_admin_password.txt until it is changed; you are made to choose your
own password at first sign-in. Settings (secret key, HTTPS cookies, proxy,
sign-in limits...) are environment variables - see README.md, "Security
configuration".
"""

import csv
import io
import json
import os
import re
import secrets
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

from rules import CATEGORIES as BUILTIN_CATEGORIES

# Absolute, so the database is always the one beside this file no matter which
# folder the app is started from (matters when it runs as a service).
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DB_PATH") or str(BASE_DIR / "partcodes.db")
# Modules an Admin can delegate to a "User" role account. "Manage Categories"
# is deliberately NOT in this list — creating new material types is kept
# Admin-only and isn't something Admins can hand off via access checkboxes.
ALL_MODULES = ["home", "history", "user_management"]

# Every generated code (hyphens included) must be this many characters long.
CODE_MIN_LEN = 10
CODE_MAX_LEN = 18

PLANT_INFO = {
    "name": "BESS Pune",
    "code": "4971",
    "address": "Kamshet, Pune, Maharashtra, India",
}
COMPANY_NAME = "JSW Energy"

def _env_flag(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def _load_secret_key():
    """Signs the session cookie. Taken from the SECRET_KEY environment variable
    if set; otherwise a random key is generated once and kept in .secret_key
    beside the app, so sessions survive restarts without any setup."""
    from_env = os.environ.get("SECRET_KEY")
    if from_env:
        return from_env
    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        stored = key_file.read_text().strip()
        if stored:
            return stored
    new_key = secrets.token_hex(32)
    key_file.write_text(new_key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass  # not supported on every filesystem (e.g. Windows)
    return new_key


app = Flask(__name__)
app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,      # page scripts can't read the cookie
    SESSION_COOKIE_SAMESITE="Lax",     # not sent on cross-site POSTs
    # Set SESSION_COOKIE_SECURE=1 once the app is served over HTTPS. Left off by
    # default because browsers refuse to send a Secure cookie over plain HTTP,
    # which would make sign-in impossible on an HTTP-only setup.
    SESSION_COOKIE_SECURE=_env_flag("SESSION_COOKIE_SECURE", False),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=float(os.environ.get("SESSION_HOURS", "8"))),
)
if _env_flag("TRUST_PROXY"):
    # Behind a reverse proxy (IIS / nginx): use the real client address and scheme
    # it forwards, so sign-in limits apply per person rather than per proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------
def get_db():
    # timeout: if another request is writing, wait up to 30 s for our turn
    # instead of failing straight away with "database is locked".
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def begin_write(conn):
    """Take the database's single write lock now, waiting our turn if someone
    else holds it. Use before any "look something up, then save" sequence
    (next sequence number, does this code already exist...) so it runs as one
    uninterrupted step. Without it, two people doing the same thing at once
    can both read the old state, and one of them is refused with an error.
    The lock is released by conn.commit(), or by closing the connection."""
    conn.execute("BEGIN IMMEDIATE")


def init_db():
    conn = get_db()
    # Write-ahead log: people reading (history, charts, page loads) no longer
    # block someone saving a code, and the reverse. Remembered by the database file.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'User',
            access TEXT NOT NULL DEFAULT '[]',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS part_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            attributes TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS custom_categories (
            key TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            code_format TEXT NOT NULL,
            fields TEXT NOT NULL,
            auto_width INTEGER NOT NULL DEFAULT 3,
            created_by TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    try:  # upgrading a database created before 'description' existed
        conn.execute("ALTER TABLE custom_categories ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        """CREATE TABLE IF NOT EXISTS category_field_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_key TEXT NOT NULL,
            field_key TEXT NOT NULL,
            code TEXT NOT NULL,
            label TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(category_key, field_key, code)
        )"""
    )
    users_upgraded = False
    try:  # upgrading a database created before forced password changes existed
        conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        users_upgraded = True
    except sqlite3.OperationalError:
        pass  # column already there: fresh database, or already upgraded
    conn.execute(
        """CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            username TEXT NOT NULL,
            attempted_at REAL NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts (ip, username, attempted_at)")

    announce = None
    existing = conn.execute("SELECT id FROM users WHERE username = ?", ("Master",)).fetchone()
    if not existing:
        supplied = os.environ.get("INITIAL_ADMIN_PASSWORD")
        initial_password = supplied or secrets.token_urlsafe(9)
        conn.execute(
            "INSERT INTO users (username, password_hash, role, access, must_change_password, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (
                "Master",
                generate_password_hash(initial_password),
                "Admin",
                json.dumps(ALL_MODULES),
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        if not supplied:
            announce = initial_password
    elif users_upgraded:
        # An older database: its Master account may still be on a shared or
        # well-known password, so make that account choose a new one.
        conn.execute("UPDATE users SET must_change_password = 1 WHERE username = ?", ("Master",))
    conn.commit()
    conn.close()
    if announce:
        _announce_initial_password(announce)


def load_custom_categories(conn):
    """Admin-added material categories, stored as data (not code)."""
    out = {}
    for r in conn.execute("SELECT * FROM custom_categories").fetchall():
        fields_raw = json.loads(r["fields"])
        tuple_fields = [(f["key"], f["label"], f["kind"], f.get("choices")) for f in fields_raw]
        template = r["code_format"]

        def build_code(values, _template=template):
            return _template.format(**values)

        out[r["key"]] = {
            "key": r["key"],
            "label": r["label"],
            "description": r["description"] or "",
            "code_format": template,
            "fields": tuple_fields,
            "scope_fields": None,  # sequence numbers run globally per category
            "auto_width": r["auto_width"],
            "build_code": build_code,
            "custom": True,
        }
    return out


def get_all_categories(conn):
    all_cats = dict(BUILTIN_CATEGORIES)
    all_cats.update(load_custom_categories(conn))
    return all_cats


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return row


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "not_authenticated"}), 401
            return redirect(url_for("login"))
        if current_user() is None:
            # Session points at a user id that no longer exists (DB was
            # reset, or the account was deleted while they were logged in).
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "not_authenticated"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


def admin_required(f):
    """Strictly Admin-role only — used for anything Admin status itself
    controls (creating material categories, granting Admin access)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "Admin":
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)

    return wrapper


def manage_users_required(f):
    """Admins always pass. A 'User' role account passes only if an Admin
    has explicitly granted them the 'user_management' module — but even
    then, granting Admin access itself stays gated by admin_required-style
    checks inside the route (see api_users / api_user_detail)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "forbidden"}), 403
        access = json.loads(user["access"])
        if user["role"] != "Admin" and "user_management" not in access:
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)

    return wrapper


def user_to_dict(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "access": json.loads(row["access"]),
        "created_at": row["created_at"],
    }


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "category"


# --------------------------------------------------------------------------
# Security helpers: password rules, sign-in throttling, request hooks
# --------------------------------------------------------------------------
MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 128
LOGIN_WINDOW_SECONDS = int(float(os.environ.get("LOGIN_WINDOW_MINUTES", "15")) * 60)
LOGIN_MAX_PER_USER = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))        # per address + username
LOGIN_MAX_PER_IP = int(os.environ.get("LOGIN_MAX_ATTEMPTS_PER_IP", "30"))  # per address, any username
INITIAL_PASSWORD_FILE = BASE_DIR / "initial_admin_password.txt"

# Checked when a username doesn't exist, so "wrong username" and "wrong password"
# take about the same time to answer.
_DUMMY_HASH = generate_password_hash("placeholder-for-timing")


def validate_password(password, username=""):
    """Returns a message describing the problem, or None if the password is fine."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len(password) > MAX_PASSWORD_LEN:
        return f"Password must be at most {MAX_PASSWORD_LEN} characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must include at least one letter and one number."
    if username and username.lower() in password.lower():
        return "Password can't contain the username."
    return None


def _announce_initial_password(password):
    INITIAL_PASSWORD_FILE.write_text(
        f"Temporary password for the 'Master' account: {password}\n"
        "You will be asked to choose your own at first sign-in.\n"
        "This file is deleted automatically once the password has been changed.\n"
    )
    try:
        os.chmod(INITIAL_PASSWORD_FILE, 0o600)
    except OSError:
        pass
    bar = "=" * 64
    print(f"\n{bar}\n  First start: admin account created.\n"
          f"  Username: Master\n  Temporary password: {password}\n"
          f"  (also saved in {INITIAL_PASSWORD_FILE.name} until you change it)\n{bar}\n", flush=True)


def client_ip():
    return request.remote_addr or "unknown"


def login_block_seconds(conn, ip, username):
    """0 if another attempt is allowed, otherwise the seconds to wait. Counts
    failed attempts only, inside a sliding window."""
    now = time.time()
    conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (now - LOGIN_WINDOW_SECONDS,))
    wait = 0.0
    checks = (
        ("SELECT attempted_at FROM login_attempts WHERE ip = ? AND username = ? ORDER BY attempted_at",
         (ip, username.lower()), LOGIN_MAX_PER_USER),
        ("SELECT attempted_at FROM login_attempts WHERE ip = ? ORDER BY attempted_at",
         (ip,), LOGIN_MAX_PER_IP),
    )
    for sql, params, limit in checks:
        times = [r[0] for r in conn.execute(sql, params)]
        if len(times) >= limit:
            # Unblocked once enough of the oldest failures have aged out of the window.
            wait = max(wait, times[len(times) - limit] + LOGIN_WINDOW_SECONDS - now)
    return int(wait) + 1 if wait > 0 else 0


def record_failed_login(conn, ip, username):
    conn.execute(
        "INSERT INTO login_attempts (ip, username, attempted_at) VALUES (?, ?, ?)",
        (ip, username.lower()[:100], time.time()),
    )


def _wait_message(seconds):
    minutes = max(1, (seconds + 59) // 60)
    return f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}."


@app.errorhandler(sqlite3.IntegrityError)
def handle_collision(error):
    """Two people saved the same thing at the same instant; the database
    kept only the first. Tell the second person plainly."""
    message = "Someone else just saved that at the same moment. Please refresh and check before trying again."
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), 409
    return message, 409


@app.errorhandler(sqlite3.OperationalError)
def handle_busy(error):
    if "locked" not in str(error).lower() and "busy" not in str(error).lower():
        raise error
    message = "The system is busy right now. Please try again in a moment."
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), 503
    return message, 503


@app.before_request
def enforce_password_change():
    """Someone on a temporary password can do nothing but change it."""
    if request.endpoint in (None, "static", "login", "logout", "change_password"):
        return None
    if not session.get("uid"):
        return None
    user = current_user()
    if user is not None and user["must_change_password"]:
        if request.path.startswith("/api/"):
            return jsonify({"error": "password_change_required"}), 403
        return redirect(url_for("change_password"))
    return None


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"  # keep pages and data out of browser caches
    return response


# --------------------------------------------------------------------------
# Page routes
# --------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("uid"):
            return redirect(url_for("index"))
        return render_template("login.html", company=COMPANY_NAME, error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    ip = client_ip()
    conn = get_db()

    wait = login_block_seconds(conn, ip, username)
    conn.commit()  # release the write lock before the slow password check
    if wait:
        conn.close()
        return render_template("login.html", company=COMPANY_NAME, error=_wait_message(wait)), 429

    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    password_ok = check_password_hash(row["password_hash"] if row else _DUMMY_HASH, password)
    if row is None or not password_ok:
        record_failed_login(conn, ip, username)
        conn.commit()
        conn.close()
        return render_template("login.html", company=COMPANY_NAME, error="Incorrect username or password.")

    conn.execute("DELETE FROM login_attempts WHERE ip = ? AND username = ?", (ip, username.lower()))
    conn.commit()
    conn.close()
    session.clear()  # fresh session on every sign-in
    session.permanent = True
    session["uid"] = row["id"]
    return redirect(url_for("index"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    user = current_user()
    forced = bool(user["must_change_password"])

    def page(error=None, status=200):
        return render_template(
            "change_password.html", company=COMPANY_NAME, forced=forced, error=error,
            username=user["username"], min_len=MIN_PASSWORD_LEN,
        ), status

    if request.method == "GET":
        return page()

    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    ip = client_ip()
    conn = get_db()

    wait = login_block_seconds(conn, ip, user["username"])
    conn.commit()  # release the write lock before the slow password check
    if wait:
        conn.close()
        return page(_wait_message(wait), 429)

    error = None
    if not check_password_hash(user["password_hash"], current):
        record_failed_login(conn, ip, user["username"])
        error = "Current password is incorrect."
    elif new != confirm:
        error = "The new passwords don't match."
    elif check_password_hash(user["password_hash"], new):
        error = "Choose a password different from your current one."
    else:
        error = validate_password(new, user["username"])
    if error:
        conn.commit()
        conn.close()
        return page(error)

    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
        (generate_password_hash(new), user["id"]),
    )
    conn.execute("DELETE FROM login_attempts WHERE ip = ? AND username = ?", (ip, user["username"].lower()))
    conn.commit()
    conn.close()
    if user["username"] == "Master" and INITIAL_PASSWORD_FILE.exists():
        INITIAL_PASSWORD_FILE.unlink()
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    user = current_user()
    return render_template(
        "app.html",
        company=COMPANY_NAME,
        plant=PLANT_INFO,
        user=user_to_dict(user),
        all_modules=ALL_MODULES,
        code_min=CODE_MIN_LEN,
        code_max=CODE_MAX_LEN,
    )


# --------------------------------------------------------------------------
# API: session / categories
# --------------------------------------------------------------------------
@app.route("/api/me")
@login_required
def api_me():
    return jsonify(user_to_dict(current_user()))


def _merged_choices(conn, category_key, field_key, base_choices):
    """Base (built-in or custom-category) choices, plus anything an Admin
    has added later via 'Manage options', flagged so the UI can tell which
    ones are removable."""
    result = [[c, l, False] for c, l in (base_choices or [])]
    existing = {c for c, l in (base_choices or [])}
    extra = conn.execute(
        "SELECT code, label FROM category_field_options WHERE category_key = ? AND field_key = ? ORDER BY id",
        (category_key, field_key),
    ).fetchall()
    for row in extra:
        if row["code"] in existing:
            continue
        result.append([row["code"], row["label"], True])
        existing.add(row["code"])
    return result


def category_length_range(cat, get_codes):
    """(shortest, longest) code length a category can ever produce, or None
    when a free-text field makes that unknowable. `get_codes(field_key,
    base_choices)` returns the list of option codes to consider for a
    dropdown field. Length is additive across segments, so the extremes
    come from picking the shortest / longest option in every field."""
    lo_vals, hi_vals = {}, {}
    for fkey, _flabel, fkind, fchoices in cat["fields"]:
        if fkind == "choice":
            codes = get_codes(fkey, fchoices)
            if not codes:
                return None
            lo_vals[fkey] = min(codes, key=len)
            hi_vals[fkey] = max(codes, key=len)
        elif fkind == "auto":
            lo_vals[fkey] = hi_vals[fkey] = "0" * cat.get("auto_width", 3)
        else:
            return None
    try:
        return len(cat["build_code"](lo_vals)), len(cat["build_code"](hi_vals))
    except KeyError:
        return None


def _length_rule_message(lo, hi):
    span = f"{lo}\u2013{hi} characters long" if lo != hi else f"{lo} characters long"
    return (f"Codes for this category would be {span} but every code must be "
            f"{CODE_MIN_LEN}\u2013{CODE_MAX_LEN} characters.")


def _categories_json(conn):
    out = {}
    for key, cat in get_all_categories(conn).items():
        fields_out = []
        for fkey, flabel, fkind, fchoices in cat["fields"]:
            if fkind == "choice":
                fchoices = _merged_choices(conn, key, fkey, fchoices)
            fields_out.append({"key": fkey, "label": flabel, "kind": fkind, "choices": fchoices})
        rng = category_length_range(
            cat, lambda fk, base, _k=key: [c[0] for c in _merged_choices(conn, _k, fk, base)]
        )
        out[key] = {
            "label": cat["label"],
            "description": cat.get("description") or "",
            "code_format": cat["code_format"],
            "custom": cat.get("custom", False),
            "fields": fields_out,
            "length_range": list(rng) if rng else None,
        }
    # Imported historical codes may carry a category string that was never
    # formally defined (e.g. from a legacy spreadsheet). Surface it as a
    # read-only pseudo-category so History filters and labels still work.
    used = conn.execute("SELECT DISTINCT category FROM part_codes").fetchall()
    for row in used:
        key = row["category"]
        if key and key not in out:
            out[key] = {
                "label": key.replace("_", " ").replace("-", " ").title(),
                "description": "Historical codes imported from outside this app.",
                "code_format": "(imported / legacy)",
                "custom": True,
                "fields": [],
                "length_range": None,
            }
    return out


def describe_code(conn, categories, cat_key, values):
    """Turn a code's raw attribute values into a plain-language breakdown,
    e.g. 'Supplier: EVE | Capacity (Ah): 105' instead of just 'EVE 105' —
    shown right after a code is created and in History."""
    cat = categories.get(cat_key)
    if not cat or not cat.get("fields"):
        if isinstance(values, dict) and values.get("imported"):
            return "Imported historical code \u2014 no structured breakdown available."
        return None
    parts = []
    for fkey, flabel, fkind, fchoices in cat["fields"]:
        val = values.get(fkey)
        if val is None:
            continue
        if fkind == "choice":
            label_map = {c[0]: c[1] for c in _merged_choices(conn, cat_key, fkey, fchoices)}
            parts.append(f"{flabel}: {label_map.get(val, val)}")
        elif fkind == "auto":
            parts.append(f"{flabel}: {val}")
        else:
            parts.append(f"{flabel}: {val}")
    return " | ".join(parts) if parts else None


@app.route("/api/categories", methods=["GET", "POST"])
@login_required
def api_categories():
    conn = get_db()
    if request.method == "GET":
        out = _categories_json(conn)
        conn.close()
        return jsonify(out)

    # POST — create a new material category. Admin only: this is the one
    # thing that stays out of the delegable module-access system entirely.
    user = current_user()
    if user["role"] != "Admin":
        conn.close()
        return jsonify({"error": "Only an Admin can add a new material category."}), 403

    data = request.get_json(force=True)
    label = (data.get("label") or "").strip()
    description = (data.get("description") or "").strip()
    prefix = re.sub(r"[^A-Za-z0-9-]", "", (data.get("prefix") or "").strip()) or "JEVBP"
    fields = data.get("fields") or []
    if not label:
        conn.close()
        return jsonify({"error": "Category name is required."}), 400
    if not fields:
        conn.close()
        return jsonify({"error": "Add at least one field."}), 400

    auto_fields = [f for f in fields if f.get("kind") == "auto"]
    if len(auto_fields) > 1:
        conn.close()
        return jsonify({"error": "Only one auto-sequence field is allowed per category."}), 400

    begin_write(conn)
    key = slugify(label)
    all_existing = get_all_categories(conn)
    suffix = 1
    base_key = key
    while key in all_existing:
        suffix += 1
        key = f"{base_key}_{suffix}"

    clean_fields = []
    template_parts = [prefix]
    for f in fields:
        fkey = slugify(f.get("key") or f.get("label") or "field")
        flabel = (f.get("label") or fkey).strip()
        fkind = f.get("kind") if f.get("kind") in ("choice", "text", "auto") else "text"
        choices = None
        if fkind == "choice":
            raw = f.get("choices_raw", "")
            choices = []
            for pair in raw.split(","):
                pair = pair.strip()
                if not pair:
                    continue
                if ":" in pair:
                    code, lbl = pair.split(":", 1)
                else:
                    code, lbl = pair, pair
                choices.append([code.strip(), lbl.strip()])
            if not choices:
                conn.close()
                return jsonify({"error": f"'{flabel}' needs at least one choice."}), 400
        clean_fields.append({"key": fkey, "label": flabel, "kind": fkind, "choices": choices})
        template_parts.append("{" + fkey + "}")

    code_format = "-".join(template_parts)
    auto_width = int(data.get("auto_width", 3))

    # Enforce the 10-18 character standard up front whenever it can be
    # worked out (i.e. no free-text field). Free-text categories are still
    # checked code-by-code at creation time.
    pseudo_cat = {
        "fields": [(f["key"], f["label"], f["kind"], f["choices"]) for f in clean_fields],
        "auto_width": auto_width,
        "build_code": lambda v, _t=code_format: _t.format(**v),
    }
    rng = category_length_range(pseudo_cat, lambda fk, base: [c[0] for c in (base or [])])
    if rng and (rng[0] < CODE_MIN_LEN or rng[1] > CODE_MAX_LEN):
        conn.close()
        return jsonify({"error": _length_rule_message(*rng) + " Shorten the prefix or option codes, or add more segments."}), 400

    conn.execute(
        "INSERT INTO custom_categories (key, label, description, code_format, fields, auto_width, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (key, label, description, code_format, json.dumps(clean_fields), auto_width,
         user["username"], datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "key": key, "code_format": code_format})


@app.route("/api/categories/<key>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_category(key):
    conn = get_db()
    begin_write(conn)
    row = conn.execute("SELECT key FROM custom_categories WHERE key = ?", (key,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Only Admin-added categories can be removed."}), 404
    in_use = conn.execute("SELECT id FROM part_codes WHERE category = ? LIMIT 1", (key,)).fetchone()
    if in_use:
        conn.close()
        return jsonify({"error": "This category already has codes issued against it and can't be removed."}), 400
    conn.execute("DELETE FROM custom_categories WHERE key = ?", (key,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/categories/<key>/fields/<field_key>/options", methods=["POST"])
@login_required
@admin_required
def api_add_field_option(key, field_key):
    data = request.get_json(force=True)
    code = str(data.get("code", "")).strip()
    label = str(data.get("label", "")).strip() or code
    if not code:
        return jsonify({"error": "Option code is required."}), 400

    conn = get_db()
    begin_write(conn)
    categories = get_all_categories(conn)
    if key not in categories:
        conn.close()
        return jsonify({"error": "Unknown category."}), 404
    field = next((f for f in categories[key]["fields"] if f[0] == field_key), None)
    if not field or field[2] != "choice":
        conn.close()
        return jsonify({"error": "That field doesn't accept dropdown options."}), 400

    existing_codes = {c for c, l in (field[3] or [])}
    extra_rows = conn.execute(
        "SELECT code FROM category_field_options WHERE category_key = ? AND field_key = ?", (key, field_key)
    ).fetchall()
    existing_codes.update(r["code"] for r in extra_rows)
    if code in existing_codes:
        conn.close()
        return jsonify({"error": f"Option '{code}' already exists for this field."}), 409

    def _codes_with_new(fk, base, _key=key):
        codes = [c[0] for c in _merged_choices(conn, _key, fk, base)]
        if fk == field_key:
            codes.append(code)
        return codes

    rng = category_length_range(categories[key], _codes_with_new)
    if rng and (rng[0] < CODE_MIN_LEN or rng[1] > CODE_MAX_LEN):
        conn.close()
        return jsonify({"error": f"Can't add '{code}': " + _length_rule_message(*rng)}), 400

    conn.execute(
        "INSERT INTO category_field_options (category_key, field_key, code, label, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (key, field_key, code, label, current_user()["username"], datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/categories/<key>/fields/<field_key>/options/<code>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_field_option(key, field_key, code):
    conn = get_db()
    begin_write(conn)
    row = conn.execute(
        "SELECT id FROM category_field_options WHERE category_key = ? AND field_key = ? AND code = ?",
        (key, field_key, code),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Only options added here can be removed — this one is part of the base category definition."}), 400
    conn.execute("DELETE FROM category_field_options WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# API: codes
# --------------------------------------------------------------------------
@app.route("/api/codes", methods=["GET", "POST"])
@login_required
def api_codes():
    conn = get_db()
    categories = get_all_categories(conn)

    if request.method == "POST":
        data = request.get_json(force=True)
        cat_key = data.get("category")
        if cat_key not in categories:
            conn.close()
            return jsonify({"error": "Unknown category."}), 400
        category = categories[cat_key]
        values = {}
        for fkey, flabel, fkind, _ in category["fields"]:
            if fkind == "auto":
                continue
            v = str(data.get("values", {}).get(fkey, "")).strip()
            if not v:
                conn.close()
                return jsonify({"error": f"'{flabel}' is required."}), 400
            values[fkey] = v

        # From here until the commit below, nobody else can save a code: the
        # "next number" we work out can't be taken by someone else before we
        # store it, and the duplicate check can't go stale.
        begin_write(conn)

        for fkey, flabel, fkind, _ in category["fields"]:
            if fkind == "auto":
                # Render the template with every other field filled in and a
                # sentinel standing in for this one, so we get the EXACT
                # literal text surrounding the auto segment for this
                # category+attribute combination — including any literal
                # text between fields (e.g. the "03" in
                # "{project}-03-{type}-{seq}"), which a naive "scope values
                # joined by '-'" prefix would miss.
                sentinel = "\x00AUTO\x00"
                probe_values = dict(values)
                probe_values[fkey] = sentinel
                try:
                    templated = category["build_code"](probe_values)
                except KeyError:
                    templated = None

                width = category.get("auto_width", 3)
                max_n = 0
                if templated and sentinel in templated:
                    prefix, _, suffix = templated.partition(sentinel)
                    rows = conn.execute(
                        "SELECT code FROM part_codes WHERE category = ? ORDER BY id DESC", (cat_key,)
                    ).fetchall()
                    for r in rows:
                        code = r["code"]
                        if not code.startswith(prefix):
                            continue
                        if suffix and not code.endswith(suffix):
                            continue
                        middle = code[len(prefix): len(code) - len(suffix) if suffix else None]
                        if middle.isdigit():
                            max_n = max(max_n, int(middle))
                values[fkey] = str(max_n + 1).zfill(width)

        try:
            code = category["build_code"](values)
        except KeyError as e:
            conn.close()
            return jsonify({"error": f"Category template is missing a value for {e}."}), 400

        if not (CODE_MIN_LEN <= len(code) <= CODE_MAX_LEN):
            conn.close()
            return jsonify({
                "error": f"'{code}' is {len(code)} characters long; every code must be "
                         f"{CODE_MIN_LEN}\u2013{CODE_MAX_LEN} characters. Use shorter values."
            }), 400

        dup = conn.execute("SELECT id FROM part_codes WHERE code = ?", (code,)).fetchone()
        if dup:
            conn.close()
            return jsonify({
                "error": f"Duplicate blocked: '{code}' already exists in the register."
            }), 409

        user = current_user()
        created_at = datetime.utcnow().isoformat(timespec="seconds")
        cur = conn.execute(
            "INSERT INTO part_codes (category, code, attributes, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (cat_key, code, json.dumps(values), user["username"], created_at),
        )
        conn.commit()
        new_id = cur.lastrowid
        description = describe_code(conn, categories, cat_key, values)
        conn.close()
        return jsonify({
            "id": new_id, "code": code, "category": cat_key, "attributes": values,
            "created_by": user["username"], "created_at": created_at,
            "description": description,
        })

    category_filter = request.args.get("category")
    q = "SELECT * FROM part_codes"
    params = []
    if category_filter and category_filter != "all":
        q += " WHERE category = ?"
        params.append(category_filter)
    q += " ORDER BY id DESC"
    rows = conn.execute(q, params).fetchall()
    result = []
    for r in rows:
        attrs = json.loads(r["attributes"])
        result.append({
            "id": r["id"], "category": r["category"], "code": r["code"],
            "attributes": attrs, "created_by": r["created_by"],
            "created_at": r["created_at"],
            "description": describe_code(conn, categories, r["category"], attrs),
        })
    conn.close()
    return jsonify(result)


@app.route("/api/stats")
@login_required
def api_stats():
    granularity = request.args.get("granularity", "day")
    fmt = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}.get(granularity, "%Y-%m-%d")
    conn = get_db()
    rows = conn.execute("SELECT created_at FROM part_codes").fetchall()
    conn.close()
    buckets = {}
    for r in rows:
        try:
            dt = datetime.fromisoformat(r["created_at"])
        except ValueError:
            continue
        key = dt.strftime(fmt)
        buckets[key] = buckets.get(key, 0) + 1
    ordered = sorted(buckets.items())
    return jsonify({"labels": [k for k, _ in ordered], "values": [v for _, v in ordered]})


# --------------------------------------------------------------------------
# API: export (txt / xlsx)
# --------------------------------------------------------------------------
def _xlsx_col(idx):
    """0-based column index -> spreadsheet letters (0 -> A, 26 -> AA)."""
    idx += 1
    letters = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def build_xlsx(headers, rows, sheet_name="Part Codes"):
    """Return the bytes of a real .xlsx workbook using only the standard
    library, so Excel export works with nothing but Flask installed."""
    def cell(ref, value, style=0):
        text = "" if value is None else str(value)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        s = f' s="{style}"' if style else ""
        if isinstance(value, int) and not isinstance(value, bool):
            return f'<c r="{ref}"{s}><v>{value}</v></c>'
        return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{xml_escape(text)}</t></is></c>'

    everything = [headers] + rows
    widths = [
        max(len(str(r[i])) if i < len(r) and r[i] is not None else 0 for r in everything)
        for i in range(len(headers))
    ]
    cols = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{min(max(w + 2, 10), 50)}" customWidth="1"/>'
        for i, w in enumerate(widths)
    )
    sheet_rows = []
    for r_idx, row in enumerate(everything, start=1):
        style = 1 if r_idx == 1 else 0
        cells = "".join(cell(f"{_xlsx_col(c)}{r_idx}", v, style) for c, v in enumerate(row))
        sheet_rows.append(f'<row r="{r_idx}">{cells}</row>')

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

    sheet_xml = (
        f'{head}<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        f'</sheetView></sheetViews><cols>{cols}</cols><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    styles_xml = (
        f'{head}<styleSheet xmlns="{ns}">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF034078"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    )
    workbook_xml = (
        f'{head}<workbook xmlns="{ns}" xmlns:r="{rel_ns}"><sheets>'
        f'<sheet name="{xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        f'{head}<Relationships xmlns="{pkg_rel}">'
        f'<Relationship Id="rId1" Type="{rel_ns}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{rel_ns}/styles" Target="styles.xml"/></Relationships>'
    )
    root_rels = (
        f'{head}<Relationships xmlns="{pkg_rel}">'
        f'<Relationship Id="rId1" Type="{rel_ns}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        f'{head}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/styles.xml", styles_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


@app.route("/api/export", methods=["POST"])
@login_required
def api_export():
    data = request.get_json(force=True)
    ids = data.get("ids") or []
    fmt = data.get("format", "txt")
    if not ids:
        return jsonify({"error": "No codes selected."}), 400

    conn = get_db()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM part_codes WHERE id IN ({placeholders}) ORDER BY id DESC", ids
    ).fetchall()
    categories = get_all_categories(conn)
    conn.close()

    if fmt == "xlsx":
        table = []
        for r in rows:
            cat_label = categories.get(r["category"], {}).get("label", r["category"])
            attrs = json.loads(r["attributes"])
            attrs_str = "; ".join(f"{k}={v}" for k, v in attrs.items())
            table.append([r["code"], len(r["code"]), cat_label, r["created_by"], r["created_at"], attrs_str])
        buf = io.BytesIO(build_xlsx(
            ["Code", "Length", "Category", "Created By", "Created At (UTC)", "Attributes"], table
        ))
        return send_file(
            buf, as_attachment=True, download_name="part_codes_export.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # default: txt
    content = "\n".join(r["code"] for r in rows)
    buf = io.BytesIO(content.encode("utf-8"))
    return send_file(buf, as_attachment=True, download_name="part_codes_export.txt", mimetype="text/plain")


@app.route("/api/import", methods=["POST"])
@login_required
@admin_required
def api_import():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "Choose a .csv or .xlsx file first."}), 400

    filename = file.filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    raw_rows = []

    if ext == "csv":
        content = file.stream.read().decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            raw_rows.append(row)
    elif ext in ("xlsx", "xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            return jsonify({
                "error": "Reading .xlsx files needs the 'openpyxl' package (pip install openpyxl). "
                         "Or save the sheet as .csv and import that instead."
            }), 500
        wb = load_workbook(file, read_only=True, data_only=True)
        ws = wb.active
        headers = None
        for row in ws.iter_rows(values_only=True):
            if headers is None:
                headers = [str(h).strip() if h is not None else "" for h in row]
                continue
            raw_rows.append({headers[i]: row[i] for i in range(len(headers)) if i < len(row)})
    else:
        return jsonify({"error": "Unsupported file type — upload a .csv or .xlsx file."}), 400

    # Normalize header keys (case/whitespace-insensitive lookup)
    norm_rows = []
    for r in raw_rows:
        norm_rows.append({(k.strip().lower() if k else k): v for k, v in r.items()})

    conn = get_db()
    begin_write(conn)  # the whole import is one step; other saves wait until it is done
    inserted = skipped_dup = skipped_invalid = off_standard = 0

    for r in norm_rows:
        code = str(r.get("code") or "").strip()
        if not code:
            skipped_invalid += 1
            continue
        category = str(r.get("category") or "legacy").strip() or "legacy"
        created_by = str(r.get("created_by") or "import").strip() or "import"
        created_at_raw = str(r.get("created_at") or "").strip()
        try:
            created_at = (
                datetime.fromisoformat(created_at_raw).isoformat(timespec="seconds")
                if created_at_raw else datetime.utcnow().isoformat(timespec="seconds")
            )
        except ValueError:
            created_at = datetime.utcnow().isoformat(timespec="seconds")

        dup = conn.execute("SELECT id FROM part_codes WHERE code = ?", (code,)).fetchone()
        if dup:
            skipped_dup += 1
            continue

        conn.execute(
            "INSERT INTO part_codes (category, code, attributes, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (category, code, json.dumps({"imported": True}), created_by, created_at),
        )
        inserted += 1
        if not (CODE_MIN_LEN <= len(code) <= CODE_MAX_LEN):
            off_standard += 1

    conn.commit()
    conn.close()
    return jsonify({
        "ok": True, "inserted": inserted, "skipped_duplicate": skipped_dup,
        "skipped_invalid": skipped_invalid, "total_rows": len(norm_rows),
        "off_standard": off_standard,
    })


# --------------------------------------------------------------------------
# API: user management
# --------------------------------------------------------------------------
@app.route("/api/users", methods=["GET", "POST"])
@login_required
@manage_users_required
def api_users():
    conn = get_db()
    acting_user = current_user()

    if request.method == "POST":
        data = request.get_json(force=True)
        username = data.get("username", "").strip()
        password = data.get("password", "")
        requested_role = data.get("role", "User")
        access = data.get("access", [])

        if not username or not password:
            conn.close()
            return jsonify({"error": "Username and password are required."}), 400
        password_problem = validate_password(password, username)
        if password_problem:
            conn.close()
            return jsonify({"error": password_problem}), 400

        # Only a real Admin can create another Admin — non-admin managers
        # (delegated user_management access) are forced to "User".
        if requested_role == "Admin" and acting_user["role"] != "Admin":
            conn.close()
            return jsonify({"error": "Only an Admin can grant Admin access."}), 403
        role = "Admin" if requested_role == "Admin" else "User"

        access = [a for a in access if a in ALL_MODULES]
        if role == "Admin":
            access = ALL_MODULES[:]
        elif acting_user["role"] != "Admin":
            access = [a for a in access if a != "user_management"]

        begin_write(conn)
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            conn.close()
            return jsonify({"error": "Username already exists."}), 409

        # The Admin chose this password, so it is temporary: the person must pick their own.
        conn.execute(
            "INSERT INTO users (username, password_hash, role, access, must_change_password, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (username, generate_password_hash(password), role, json.dumps(access),
             datetime.utcnow().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
    conn.close()
    return jsonify([user_to_dict(r) for r in rows])


@app.route("/api/users/<int:uid>", methods=["PUT", "DELETE"])
@login_required
@manage_users_required
def api_user_detail(uid):
    conn = get_db()
    begin_write(conn)
    acting_user = current_user()
    target = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "User not found."}), 404
    if target["role"] == "Admin" and acting_user["role"] != "Admin":
        conn.close()
        return jsonify({"error": "Only an Admin can manage Admin accounts."}), 403

    if request.method == "DELETE":
        if target["username"] == "Master":
            conn.close()
            return jsonify({"error": "The Master admin account can't be deleted."}), 400
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    data = request.get_json(force=True)
    requested_role = data.get("role", target["role"])
    if requested_role == "Admin" and acting_user["role"] != "Admin":
        conn.close()
        return jsonify({"error": "Only an Admin can grant Admin access."}), 403
    role = "Admin" if requested_role == "Admin" else "User"

    access = data.get("access", json.loads(target["access"]))
    access = [a for a in access if a in ALL_MODULES]
    if role == "Admin":
        access = ALL_MODULES[:]
    elif acting_user["role"] != "Admin":
        access = [a for a in access if a != "user_management"]

    conn.execute("UPDATE users SET role = ?, access = ? WHERE id = ?", (role, json.dumps(access), uid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/users/<int:uid>/reset_password", methods=["POST"])
@login_required
@manage_users_required
def api_reset_password(uid):
    data = request.get_json(force=True)
    new_password = data.get("password", "")
    acting_user = current_user()
    conn = get_db()
    begin_write(conn)
    target = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not target:
        conn.close()
        return jsonify({"error": "User not found."}), 404
    if target["role"] == "Admin" and acting_user["role"] != "Admin":
        conn.close()
        return jsonify({"error": "Only an Admin can manage Admin accounts."}), 403
    problem = validate_password(new_password, target["username"])
    if problem:
        conn.close()
        return jsonify({"error": problem}), 400
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
        (generate_password_hash(new_password), uid),
    )
    # A reset also lifts any sign-in lockout on that account.
    conn.execute("DELETE FROM login_attempts WHERE username = ?", (target["username"].lower(),))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# Create or upgrade the database whenever the app is loaded, however it is
# started (python app.py, waitress, flask run). Safe to run repeatedly.
init_db()

if __name__ == "__main__":
    # Debug mode serves an interactive debugger that can run code on the server,
    # so it is off unless explicitly requested (FLASK_DEBUG=1) for local work.
    app.run(
        debug=_env_flag("FLASK_DEBUG", False),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
    )
