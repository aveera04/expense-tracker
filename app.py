import os
import calendar
from datetime import date, datetime
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for

from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
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

    # Resolve the integer user id from the email stored in session
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if row is None:
        session.clear()
        return redirect(url_for("login"))

    db_user_id = row["id"]

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


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
