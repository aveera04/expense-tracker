import os
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for

from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

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

    # ---- Live DB queries ------------------------------------------------
    user_data   = get_user_by_id(db_user_id)
    stats       = get_summary_stats(db_user_id)
    raw_txs     = get_recent_transactions(db_user_id, limit=10)
    raw_cats    = get_category_breakdown(db_user_id)

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
