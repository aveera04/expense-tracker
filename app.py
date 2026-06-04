import hmac
import os
import calendar
from datetime import date, datetime
from functools import wraps
import math
import secrets

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
    get_expense_by_id,
    update_expense,
    delete_expense_row,
)

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# Secure secret key loading with fallback only for testing/dev
import sys
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("FLASK_DEBUG") == "1":
        secret_key = "dev-secret-key"
    else:
        raise RuntimeError("SECRET_KEY environment variable must be set")
app.secret_key = secret_key

with app.app_context():
    init_db()
    seed_db()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def requires_db_user(f):
    """
    Decorator that resolves the integer DB user-id from the session email and
    injects it as the first positional argument (``db_user_id``) of the wrapped
    view.  If the session email does not map to a real user (ghost session),
    the session is cleared and the request is redirected to login.

    Must be applied *after* @login_required so the session is guaranteed to
    contain ``user_id`` before this decorator runs.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        email = session["user_id"]
        db_user_id = resolve_db_user_id(email)
        if db_user_id is None:
            session.clear()
            return redirect(url_for("login"))
        return f(*args, db_user_id=db_user_id, **kwargs)
    return decorated


def resolve_db_user_id(email):
    """Return the integer DB user id for the given email, or None."""
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row["id"] if row else None


def _validate_csrf():
    """
    Abort 400 if the CSRF token in the submitted form does not match the one
    stored in the session.  Uses a constant-time comparison to prevent
    timing-based token oracle attacks.

    No-op when ``app.config['TESTING']`` is True so tests can submit forms
    without synthesising valid tokens.
    """
    if app.config.get("TESTING"):
        return
    session_token = session.get("_csrf_token") or ""
    form_token = request.form.get("_csrf_token") or ""
    if not session_token or not hmac.compare_digest(session_token, form_token):
        abort(400)


def generate_csrf_token():
    """Generates a CSRF token for the current session."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]

app.jinja_env.globals["csrf_token"] = generate_csrf_token


def _parse_date(value):
    """Return a date object or None if absent/malformed."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _months_ago(n, ref_date=None):
    """Return a date approximately n calendar months before ref_date."""
    if ref_date is None:
        ref_date = date.today()
    month = ref_date.month - n
    year = ref_date.year
    while month <= 0:
        month += 12
        year -= 1
    # Clamp day to last valid day of that month
    last_day = calendar.monthrange(year, month)[1]
    day = min(ref_date.day, last_day)
    return date(year, month, day)



# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        error = None

        if len(name) < 2:
            error = "Name must be at least 2 characters."
        elif not email or "@" not in email:
            error = "Please enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."

        if error:
            return render_template("register.html", error=error), 400

        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        if existing:
            conn.close()
            return render_template("register.html", error="Email already registered."), 400

        password_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        conn.commit()
        conn.close()

        session["user_id"] = email
        return redirect(url_for("profile"))

    if "user_id" in session:
        return redirect(url_for("profile"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        error = None

        if not email or "@" not in email:
            error = "Please enter a valid email address."
        elif not password:
            error = "Password is required."

        if error:
            return render_template("login.html", error=error), 400

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid email or password."), 400

        session["user_id"] = email
        return redirect(url_for("profile"))

    if "user_id" in session:
        return redirect(url_for("profile"))

    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/analytics")
@login_required
def analytics():
    return render_template("analytics.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# Maps database category names → CSS slug, human label, and Lucide icon
CATEGORY_META = {
    "Food":          {"slug": "food",          "label": "Food & Dining",  "icon": "utensils"},
    "Transport":     {"slug": "travel",         "label": "Transport",       "icon": "car"},
    "Bills":         {"slug": "bills",          "label": "Bills",           "icon": "file-text"},
    "Health":        {"slug": "health",         "label": "Health",          "icon": "heart-pulse"},
    "Entertainment": {"slug": "entertainment",  "label": "Entertainment",   "icon": "film"},
    "Shopping":      {"slug": "shopping",       "label": "Shopping",        "icon": "shopping-bag"},
    "Other":         {"slug": "other",          "label": "Other",           "icon": "circle-ellipsis"},
}

DEFAULT_META = {"slug": "other", "label": "Other", "icon": "circle-ellipsis"}


@app.route("/profile")
@login_required
def profile():
    email = session["user_id"]

    db_user_id = resolve_db_user_id(email)
    if db_user_id is None:
        session.clear()
        return redirect(url_for("login"))

    # ---- Parse & validate date-range query params -----------------------
    raw_from = request.args.get("date_from", "").strip()
    raw_to   = request.args.get("date_to",   "").strip()

    date_from = _parse_date(raw_from)
    date_to   = _parse_date(raw_to)

    # Spec: If either parameter is absent or malformed, the route falls back to unfiltered
    if not date_from or not date_to:
        date_from = None
        date_to   = None

    # If both are present but in the wrong order, flash and clear
    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = None
        date_to   = None

    # Avoid redundant date string-to-object-to-string round-tripping
    str_from = raw_from if date_from else None
    str_to   = raw_to if date_to else None

    # ---- Compute preset date windows (in Python, not in the template) ---
    today = date.today()
    first_of_month = today.replace(day=1)

    preset_dates = {
        "this_month":   {"date_from": first_of_month.isoformat(),   "date_to": today.isoformat()},
        "last_3_months":{"date_from": _months_ago(3, today).isoformat(),   "date_to": today.isoformat()},
        "last_6_months":{"date_from": _months_ago(6, today).isoformat(),   "date_to": today.isoformat()},
    }

    # Detect which preset is active (if any)
    active_preset = "all_time"
    if str_from and str_to:
        active_preset = "custom"
        for name, pd in preset_dates.items():
            if str_from == pd["date_from"] and str_to == pd["date_to"]:
                active_preset = name
                break


    # ---- Live DB queries ------------------------------------------------
    user_data   = get_user_by_id(db_user_id)
    stats       = get_summary_stats(db_user_id, date_from=str_from, date_to=str_to)
    raw_txs     = get_recent_transactions(db_user_id, limit=10, date_from=str_from, date_to=str_to)
    raw_cats    = get_category_breakdown(db_user_id, date_from=str_from, date_to=str_to)

    # ---- Build user dict for template -----------------------------------
    name = user_data["name"] if user_data else email
    initials = "".join(part[0].upper() for part in name.split() if part)[:2]
    user = {
        "name": name,
        "email": user_data["email"] if user_data else email,
        "initials": initials,
        "member_since": user_data["member_since"] if user_data else "",
    }

    # ---- Enrich transactions with slug and label -------------------------
    transactions = []
    for tx in raw_txs:
        meta = CATEGORY_META.get(tx["category"], DEFAULT_META)
        transactions.append({
            "id":             tx["id"],
            "date":           tx["date"],
            "description":    tx["description"],
            "category":       meta["slug"],
            "category_label": meta["label"],
            "amount":         tx["amount"],
        })

    # ---- Enrich category breakdown with slug, label, icon ---------------
    categories = []
    for cat in raw_cats:
        meta = CATEGORY_META.get(cat["name"], DEFAULT_META)
        categories.append({
            "name":    meta["label"],
            "slug":    meta["slug"],
            "amount":  cat["amount"],
            "percent": cat["pct"],
            "icon":    meta["icon"],
        })

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        # Filter state
        date_from=str_from,
        date_to=str_to,
        active_preset=active_preset,
        preset_dates=preset_dates,
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
@requires_db_user
def add_expense(db_user_id):
    if request.method == "POST":
        raw_amount   = request.form.get("amount", "").strip()
        category     = request.form.get("category", "").strip()
        raw_date     = request.form.get("date", "").strip()
        description  = request.form.get("description", "").strip()

        error = None

        # Validate CSRF — constant-time comparison, no-op in TESTING mode
        try:
            _validate_csrf()
        except Exception:
            error = "Invalid or missing CSRF token. Please try again."

        # Validate amount — must be a positive number and not NaN/Infinity
        if not error:
            try:
                amount = float(raw_amount)
                if math.isnan(amount) or math.isinf(amount) or amount <= 0:
                    raise ValueError
            except ValueError:
                error = "Amount must be a positive number."

        # Validate category — must exist in CATEGORY_META
        if not error and category not in CATEGORY_META:
            error = "Please select a valid category."

        # Validate date — must be a valid ISO date
        if not error:
            parsed_date = _parse_date(raw_date)
            if parsed_date is None:
                error = "Please enter a valid date."

        # Optional: cap description length
        if not error and len(description) > 200:
            error = "Description must be 200 characters or fewer."

        if error:
            return render_template(
                "add_expense.html",
                error=error,
                categories=CATEGORY_META,
                form={"amount": raw_amount, "category": category,
                      "date": raw_date, "description": description},
            ), 400

        # All valid — insert into expenses
        conn = get_db()
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            (db_user_id, amount, category, parsed_date.isoformat(), description or None),
        )
        conn.commit()
        conn.close()

        flash("Expense added successfully!", "success")
        return redirect(url_for("profile"))

    # GET — render the blank form
    today = date.today().isoformat()
    return render_template(
        "add_expense.html",
        categories=CATEGORY_META,
        form={"amount": "", "category": "", "date": today, "description": ""},
    )


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
@login_required
@requires_db_user
def edit_expense(id, db_user_id):
    expense = get_expense_by_id(id, db_user_id)
    if expense is None:
        abort(404)

    if request.method == "POST":
        raw_amount   = request.form.get("amount", "").strip()
        category     = request.form.get("category", "").strip()
        raw_date     = request.form.get("date", "").strip()
        description  = request.form.get("description", "").strip()

        error = None

        # Validate CSRF — constant-time comparison, no-op in TESTING mode
        try:
            _validate_csrf()
        except Exception:
            error = "Invalid or missing CSRF token. Please try again."

        # Validate amount — must be a positive number and not NaN/Infinity
        if not error:
            try:
                amount = float(raw_amount)
                if math.isnan(amount) or math.isinf(amount) or amount <= 0:
                    raise ValueError
            except ValueError:
                error = "Amount must be a positive number."

        # Validate category — must exist in CATEGORY_META
        if not error and category not in CATEGORY_META:
            error = "Please select a valid category."

        # Validate date — must be a valid ISO date
        if not error:
            parsed_date = _parse_date(raw_date)
            if parsed_date is None:
                error = "Please enter a valid date."

        # Optional: cap description length
        if not error and len(description) > 200:
            error = "Description must be 200 characters or fewer."

        if error:
            return render_template(
                "edit_expense.html",
                error=error,
                categories=CATEGORY_META,
                expense=expense,
                form={"amount": raw_amount, "category": category,
                      "date": raw_date, "description": description},
            ), 400

        # All valid — update the row
        rowcount = update_expense(
            id, db_user_id, amount, category, parsed_date.isoformat(), description or None,
        )
        if rowcount == 0:
            # Defensive: row was deleted between load and update
            abort(404)

        flash("Expense updated successfully!", "success")
        return redirect(url_for("profile"))

    # GET — render the pre-filled form
    return render_template(
        "edit_expense.html",
        categories=CATEGORY_META,
        expense=expense,
        form={
            "amount": expense["amount"],
            "category": expense["category"],
            "date": expense["date"],
            "description": expense["description"],
        },
    )


@app.route("/expenses/<int:id>/delete", methods=["POST"])
@login_required
@requires_db_user
def delete_expense(id, db_user_id):
    # Validate CSRF — constant-time comparison, abort 400 on mismatch
    _validate_csrf()

    # Delete with atomic ownership guard: WHERE id = ? AND user_id = ?
    # rowcount == 0 covers both "not found" and "wrong owner" without leaking which.
    rowcount = delete_expense_row(id, db_user_id)
    if rowcount == 0:
        abort(404)

    flash("Expense deleted successfully!", "success")
    return redirect(url_for("profile"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
