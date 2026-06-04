"""
tests/conftest.py — Shared pytest fixtures for the Spendly test suite.

Provides a reusable isolated SQLite DB factory, seed helpers, and
authenticated Flask test clients. Each test module that needs a DB
simply depends on ``test_db``; the factory creates a fresh file-backed
database per test so tests never share state.
"""

import sqlite3

import pytest
from werkzeug.security import generate_password_hash

import app as flask_app
import database.db as db_module


# ============================================================================ #
# Core DB factory fixture                                                       #
# ============================================================================ #

@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """
    Isolated SQLite DB backed by a temp file.

    * Creates the ``users`` and ``expenses`` tables matching the live schema.
    * Seeds one test user (test@spendly.com / testpass1).
    * Seeds ONE expense row owned by the test user; its id is returned as
      ``test_db["expense_id"]``.
    * Monkeypatches ``database.db.get_db`` AND ``flask_app.get_db`` so the app
      and all query helpers use this DB — the real spendly.db is never touched.

    Returns a dict:
      {
        "make_conn": callable,   # opens a new connection to the temp file
        "user_id":   int,        # primary key of the seeded test user
        "email":     str,        # test user email
        "password":  str,        # test user plaintext password
        "expense_id":int,        # primary key of the seeded expense row
      }
    """
    db_path = str(tmp_path / "test_spendly.db")

    def make_conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---- Schema ------------------------------------------------------------
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

    # ---- Seed test user ----------------------------------------------------
    plain_password = "testpass1"
    pw_hash = generate_password_hash(plain_password)
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@spendly.com", pw_hash),
    )
    user_id = cur.lastrowid

    # ---- Seed one expense owned by the test user ---------------------------
    cur = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, 250.0, "Food", "2026-05-20", "Lunch at cafe"),
    )
    expense_id = cur.lastrowid
    conn.commit()
    conn.close()

    # ---- Monkeypatch -------------------------------------------------------
    monkeypatch.setattr(db_module, "get_db", make_conn)
    monkeypatch.setattr(flask_app, "get_db", make_conn)

    return {
        "make_conn": make_conn,
        "user_id": user_id,
        "email": "test@spendly.com",
        "password": plain_password,
        "expense_id": expense_id,
    }


# ============================================================================ #
# Seed helper — second user                                                     #
# ============================================================================ #

def seed_other_user_with_expense(test_db):
    """
    Insert a second user with one expense into the test DB.
    Returns (other_user_id, other_expense_id).

    The first (test) user does NOT own this expense — use it to verify
    ownership enforcement (non-owner should get 404).
    """
    conn = test_db["make_conn"]()
    pw_hash = generate_password_hash("otherpass1")
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Other User", "other@spendly.com", pw_hash),
    )
    other_user_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (other_user_id, 999.0, "Other", "2026-05-21", "Other user expense"),
    )
    other_expense_id = cur.lastrowid
    conn.commit()
    conn.close()
    return other_user_id, other_expense_id


# ============================================================================ #
# Flask client fixtures                                                         #
# ============================================================================ #

@pytest.fixture
def client(test_db):
    """Flask test client wired to the isolated test database."""
    flask_app.app.config["TESTING"] = True
    flask_app.app.config["SECRET_KEY"] = "test-secret-key"
    flask_app.app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.app.test_client() as c:
        yield c


@pytest.fixture
def logged_in_client(test_db, client):
    """
    Flask test client with the test user already authenticated via /login.
    Returns (client, test_db) so tests can access the DB factory.
    """
    resp = client.post(
        "/login",
        data={"email": test_db["email"], "password": test_db["password"]},
        follow_redirects=False,
    )
    assert resp.status_code == 302, (
        f"Login should redirect (302) but got {resp.status_code}"
    )
    return client, test_db
