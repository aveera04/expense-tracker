import os
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for

from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db

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


@app.route("/profile")
@login_required
def profile():
    # Hardcoded data for Step 4
    user = {
        "name": "Arjun Mehta",
        "email": "arjun.mehta@example.com",
        "initials": "AM",
        "member_since": "January 2024"
    }
    
    stats = {
        "total_spent": 24850.00,
        "transaction_count": 18,
        "top_category": "Food & Dining"
    }
    
    transactions = [
        {"date": "2026-05-25", "description": "Swiggy Order", "category": "food", "category_label": "Food & Dining", "amount": 340.00},
        {"date": "2026-05-24", "description": "Uber Ride", "category": "travel", "category_label": "Travel", "amount": 210.00},
        {"date": "2026-05-23", "description": "Netflix Subscription", "category": "entertainment", "category_label": "Entertainment", "amount": 649.00},
        {"date": "2026-05-22", "description": "Big Bazaar Grocery", "category": "grocery", "category_label": "Groceries", "amount": 1820.00},
        {"date": "2026-05-20", "description": "Amazon Purchase", "category": "shopping", "category_label": "Shopping", "amount": 2199.00}
    ]
    
    categories = [
        {"name": "Food & Dining", "slug": "food", "amount": 8420.00, "percent": 34, "icon": "utensils"},
        {"name": "Shopping", "slug": "shopping", "amount": 6199.00, "percent": 25, "icon": "shopping-bag"},
        {"name": "Travel", "slug": "travel", "amount": 4350.00, "percent": 18, "icon": "car"},
        {"name": "Groceries", "slug": "grocery", "amount": 3680.00, "percent": 15, "icon": "shopping-cart"},
        {"name": "Entertainment", "slug": "entertainment", "amount": 2201.00, "percent": 9, "icon": "film"}
    ]
    
    return render_template(
        "profile.html", 
        user=user, 
        stats=stats, 
        transactions=transactions, 
        categories=categories
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
