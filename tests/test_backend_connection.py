"""
tests/test_backend_connection.py — Unit and route tests for Step 5.

The test_db fixture monkeypatches get_db() to use an isolated
in-memory-style temporary database so production data is never touched.
"""

import os
import sqlite3
import tempfile

import pytest
from werkzeug.security import generate_password_hash

import app as flask_app
from database import queries as q


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """
    Create a temporary SQLite database with the correct schema, seed
    it with one demo user and 8 expenses, and monkeypatch get_db() so
    that all query helpers use this DB instead of spendly.db.
    """
    db_path = str(tmp_path / "test_spendly.db")

    def make_conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # Bootstrap schema
    conn = make_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()

    # Insert demo user with a fixed created_at so member_since is predictable
    pw = generate_password_hash("demo123")
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Demo User", "demo@spendly.com", pw, "2026-01-15 10:00:00"),
    )
    user_id = cur.lastrowid

    # 8 seed expenses matching the spec (total = 6490.00, top = Bills at 2500)
    seed_expenses = [
        (user_id, 450.0,  "Food",          "2026-05-05", "Lunch at restaurant"),
        (user_id, 120.0,  "Transport",     "2026-05-08", "Uber to office"),
        (user_id, 2500.0, "Bills",         "2026-05-10", "Electricity bill"),
        (user_id, 800.0,  "Health",        "2026-05-12", "Pharmacy"),
        (user_id, 600.0,  "Entertainment", "2026-05-15", "Movie tickets"),
        (user_id, 1500.0, "Shopping",      "2026-05-18", "New headphones"),
        (user_id, 320.0,  "Food",          "2026-05-20", "Grocery shopping"),
        (user_id, 200.0,  "Other",         "2026-05-22", "Miscellaneous expense"),
    ]
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        seed_expenses,
    )
    conn.commit()
    conn.close()

    # Monkeypatch database.db.get_db — query helpers use _db_module.get_db()
    import database.db as db_module
    monkeypatch.setattr(db_module, "get_db", make_conn)
    # Also patch the reference bound directly into app.py
    monkeypatch.setattr(flask_app, "get_db", make_conn)

    return {"user_id": user_id, "email": "demo@spendly.com", "make_conn": make_conn}


@pytest.fixture
def client(test_db, monkeypatch):
    """
    Flask test client wired to the isolated test database.
    """
    flask_app.app.config["TESTING"] = True
    flask_app.app.config["SECRET_KEY"] = "test-secret"
    with flask_app.app.test_client() as c:
        yield c


# ------------------------------------------------------------------ #
# Helper                                                              #
# ------------------------------------------------------------------ #

def login(client, email="demo@spendly.com", password="demo123"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


# ------------------------------------------------------------------ #
# Unit tests — get_user_by_id                                         #
# ------------------------------------------------------------------ #

def test_get_user_by_id_valid(test_db):
    uid = test_db["user_id"]
    result = q.get_user_by_id(uid)
    assert result is not None
    assert result["name"] == "Demo User"
    assert result["email"] == "demo@spendly.com"
    assert result["member_since"] == "January 2026"


def test_get_user_by_id_invalid(test_db):
    result = q.get_user_by_id(99999)
    assert result is None


# ------------------------------------------------------------------ #
# Unit tests — get_summary_stats                                       #
# ------------------------------------------------------------------ #

def test_get_summary_stats_with_expenses(test_db):
    uid = test_db["user_id"]
    result = q.get_summary_stats(uid)
    assert result["transaction_count"] == 8
    assert abs(result["total_spent"] - 6490.0) < 0.01  # 450+120+2500+800+600+1500+320+200
    assert result["top_category"] == "Bills"  # highest single total: 2500


def test_get_summary_stats_no_expenses(test_db):
    # Insert a fresh user with no expenses
    conn = test_db["make_conn"]()
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Empty User", "empty@spendly.com", generate_password_hash("pass1234")),
    )
    empty_uid = cur.lastrowid
    conn.commit()
    conn.close()

    result = q.get_summary_stats(empty_uid)
    assert result == {"total_spent": 0, "transaction_count": 0, "top_category": "—"}


# ------------------------------------------------------------------ #
# Unit tests — get_recent_transactions                                 #
# ------------------------------------------------------------------ #

def test_get_recent_transactions_with_expenses(test_db):
    uid = test_db["user_id"]
    txs = q.get_recent_transactions(uid)
    assert len(txs) == 8
    # Newest first — last seeded date is 2026-05-22
    assert txs[0]["date"] == "2026-05-22"
    # Check required keys
    for tx in txs:
        for key in ("date", "description", "category", "amount"):
            assert key in tx


def test_get_recent_transactions_no_expenses(test_db):
    conn = test_db["make_conn"]()
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("NoTx User", "notx@spendly.com", generate_password_hash("pass1234")),
    )
    empty_uid = cur.lastrowid
    conn.commit()
    conn.close()

    result = q.get_recent_transactions(empty_uid)
    assert result == []


# ------------------------------------------------------------------ #
# Unit tests — get_category_breakdown                                  #
# ------------------------------------------------------------------ #

def test_get_category_breakdown_with_expenses(test_db):
    uid = test_db["user_id"]
    cats = q.get_category_breakdown(uid)

    # 7 unique categories
    assert len(cats) == 7

    # Ordered by amount descending
    amounts = [c["amount"] for c in cats]
    assert amounts == sorted(amounts, reverse=True)

    # pct values are integers summing to 100
    pcts = [c["pct"] for c in cats]
    assert all(isinstance(p, int) for p in pcts)
    assert sum(pcts) == 100

    # Each item has required keys
    for cat in cats:
        for key in ("name", "amount", "pct"):
            assert key in cat


def test_get_category_breakdown_no_expenses(test_db):
    conn = test_db["make_conn"]()
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("NoCat User", "nocat@spendly.com", generate_password_hash("pass1234")),
    )
    empty_uid = cur.lastrowid
    conn.commit()
    conn.close()

    result = q.get_category_breakdown(empty_uid)
    assert result == []


# ------------------------------------------------------------------ #
# Route tests                                                          #
# ------------------------------------------------------------------ #

def test_profile_unauthenticated(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_profile_authenticated(client):
    # Log in as the seed user
    login(client)

    response = client.get("/profile", follow_redirects=True)
    assert response.status_code == 200

    html = response.data.decode()

    # User info
    assert "Demo User" in html
    assert "demo@spendly.com" in html

    # Currency symbol
    assert "\u20b9" in html

    # Total spent: 450+120+2500+800+600+1500+320+200 = 6490.00
    assert "6,490.00" in html

    # Transaction count (appears in stat card)
    assert "8" in html

    # Top category
    assert "Bills" in html

    # Category breakdown — all 7 DB categories should appear via label mapping
    for label in ["Food &amp; Dining", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]:
        assert label in html


def test_profile_new_user_shows_zeros(client):
    # Register a fresh user
    client.post(
        "/register",
        data={"name": "Fresh User", "email": "fresh@spendly.com", "password": "password123"},
        follow_redirects=True,
    )

    response = client.get("/profile", follow_redirects=True)
    assert response.status_code == 200
    html = response.data.decode()

    # Zero stats — total_spent formatted
    assert "0.00" in html
    # Top category dash
    assert "—" in html
