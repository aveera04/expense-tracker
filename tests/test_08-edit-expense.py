"""
tests/test_08-edit-expense.py — Tests for Spec 08: Edit Expense

Strategy
--------
* A ``test_db`` fixture creates an isolated temporary SQLite database that
  mirrors the schema in database/db.py and monkeypatches ``get_db`` so that
  both app.py and database.queries use the test DB — the real spendly.db is
  never touched.
* A seed user is inserted with a known plain-text password so the
  ``logged_in_client`` fixture can authenticate via the real /login route,
  establishing a proper session cookie.
* The seed user owns ONE expense row whose id is exposed as
  ``test_db["expense_id"]`` so GET/POST tests have a stable target.
* A ``_seed_other_user_with_expense`` helper inserts a second user with
  one expense — used to verify that a non-owner gets a 404 (DoD 8).
* All tests are fully independent; no test relies on execution order.
* Every test maps to at least one Definition-of-Done item from the spec.

DoD coverage
------------
DoD 1  — GET /expenses/<id>/edit pre-fills the form for the owner.
DoD 2  — POST with valid data updates the matching row in expenses.
DoD 3  — After a successful POST, redirect to /profile; new values appear.
DoD 4  — POST with invalid data re-renders the form with an inline error.
DoD 5  — Category dropdown is populated from CATEGORY_META.
DoD 6  — CSRF token is rendered and validated.
DoD 7  — Unauthenticated users are redirected to the login page.
DoD 8  — Non-existent id and other-user id both return 404.
DoD 9  — Profile template has an Edit control per row.
DoD 10 — get_recent_transactions surfaces 'id' so the link can be built.
"""

import sqlite3

import pytest
from werkzeug.security import generate_password_hash

import app as flask_app
import database.queries as queries_module


# ============================================================================ #
# Constants                                                                   #
# ============================================================================ #

VALID_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]


# ============================================================================ #
# Fixtures                                                                    #
# ============================================================================ #

@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """
    Isolated in-memory-style SQLite DB backed by a temp file.

    * Creates the users and expenses tables.
    * Seeds one test user (test@spendly.com / testpass1).
    * Seeds ONE expense row owned by the test user, captured as expense_id.
    * Monkeypatches database.db.get_db AND flask_app.get_db so the app never
      touches the real spendly.db.
    """
    db_path = str(tmp_path / "test_edit_expense.db")

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
        (user_id, 150.0, "Food", "2026-05-15", "Original lunch"),
    )
    expense_id = cur.lastrowid
    conn.commit()
    conn.close()

    # ---- Monkeypatch -------------------------------------------------------
    import database.db as db_module
    monkeypatch.setattr(db_module, "get_db", make_conn)
    monkeypatch.setattr(flask_app, "get_db", make_conn)

    return {
        "make_conn": make_conn,
        "user_id": user_id,
        "email": "test@spendly.com",
        "password": plain_password,
        "expense_id": expense_id,
    }


def _seed_other_user_with_expense(test_db):
    """
    Insert a second user with one expense. Returns (other_user_id, other_expense_id).
    The first user is NOT the owner of the second user's expense.
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
        (other_user_id, 999.0, "Other", "2026-05-20", "Other user expense"),
    )
    other_expense_id = cur.lastrowid
    conn.commit()
    conn.close()
    return other_user_id, other_expense_id


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
    Returns (client, test_db) tuple so tests can access DB helpers.
    """
    resp = client.post(
        "/login",
        data={"email": test_db["email"], "password": test_db["password"]},
        follow_redirects=False,
    )
    assert resp.status_code == 302, (
        f"Login fixture failed — expected 302, got {resp.status_code}"
    )
    return client, test_db


# ============================================================================ #
# DoD 7 — Auth guard: unauthenticated users are redirected to /login          #
# ============================================================================ #

class TestAuthGuard:
    """Unauthenticated access to /expenses/<id>/edit must redirect to /login."""

    def test_get_unauthenticated_redirects(self, client, test_db):
        """DoD 7: GET /expenses/<id>/edit without a session → 302 to /login."""
        resp = client.get(f"/expenses/{test_db['expense_id']}/edit")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_post_unauthenticated_redirects(self, client, test_db):
        """DoD 7: POST /expenses/<id>/edit without a session → 302 to /login."""
        resp = client.post(
            f"/expenses/{test_db['expense_id']}/edit",
            data={
                "amount": "200",
                "category": "Food",
                "date": "2026-06-01",
                "description": "Hijack",
            },
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_unauthenticated_does_not_change_row(self, client, test_db):
        """DoD 7: an unauthenticated POST must NOT mutate the seeded row."""
        client.post(
            f"/expenses/{test_db['expense_id']}/edit",
            data={
                "amount": "99999",
                "category": "Other",
                "date": "2099-12-31",
                "description": "Hijack",
            },
        )
        conn = test_db["make_conn"]()
        row = conn.execute(
            "SELECT amount, category, date, description FROM expenses "
            "WHERE id = ?",
            (test_db["expense_id"],),
        ).fetchone()
        conn.close()
        assert row["amount"] == 150.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-05-15"
        assert row["description"] == "Original lunch"


# ============================================================================ #
# DoD 1, 5, 6 — GET /expenses/<id>/edit pre-fills the form for the owner     #
# ============================================================================ #

class TestGetEditForm:
    """GET /expenses/<id>/edit for the owner returns a pre-filled form."""

    def test_get_returns_200(self, logged_in_client):
        """DoD 1: GET /expenses/<id>/edit returns HTTP 200 for the owner."""
        client, td = logged_in_client
        resp = client.get(f"/expenses/{td['expense_id']}/edit")
        assert resp.status_code == 200

    def test_get_contains_form_element(self, logged_in_client):
        """DoD 1: The response body contains an HTML <form> element."""
        client, td = logged_in_client
        resp = client.get(f"/expenses/{td['expense_id']}/edit")
        assert "<form" in resp.data.decode()

    def test_get_form_action_targets_edit_url(self, logged_in_client):
        """DoD 1: The form action points to /expenses/<id>/edit."""
        client, td = logged_in_client
        resp = client.get(f"/expenses/{td['expense_id']}/edit")
        html = resp.data.decode()
        assert f'action="/expenses/{td["expense_id"]}/edit"' in html

    def test_get_amount_prefilled(self, logged_in_client):
        """DoD 1: The amount input is pre-filled with the seeded value."""
        client, td = logged_in_client
        resp = client.get(f"/expenses/{td['expense_id']}/edit")
        html = resp.data.decode()
        assert 'value="150.0"' in html

    def test_get_category_prefilled_selected(self, logged_in_client):
        """DoD 1: The seeded category has the 'selected' attribute."""
        client, td = logged_in_client
        resp = client.get(f"/expenses/{td['expense_id']}/edit")
        html = resp.data.decode()
        assert 'value="Food" selected' in html

    def test_get_date_prefilled(self, logged_in_client):
        """DoD 1: The date input is pre-filled with the seeded ISO date."""
        client, td = logged_in_client
        resp = client.get(f"/expenses/{td['expense_id']}/edit")
        html = resp.data.decode()
        assert 'value="2026-05-15"' in html

    def test_get_description_prefilled(self, logged_in_client):
        """DoD 1: The description input is pre-filled with the seeded text."""
        client, td = logged_in_client
        resp = client.get(f"/expenses/{td['expense_id']}/edit")
        html = resp.data.decode()
        assert 'value="Original lunch"' in html

    def test_get_all_categories_present(self, logged_in_client):
        """DoD 5: Every CATEGORY_META key appears as a selectable option."""
        client, _ = logged_in_client
        resp = client.get("/expenses/1/edit")
        html = resp.data.decode()
        for category in VALID_CATEGORIES:
            assert category in html, f"Category '{category}' missing from form"

    def test_get_csrf_token_rendered(self, logged_in_client):
        """DoD 6: The form contains a hidden CSRF token input."""
        client, _ = logged_in_client
        resp = client.get("/expenses/1/edit")
        html = resp.data.decode()
        assert 'name="_csrf_token"' in html
        assert 'type="hidden"' in html

    def test_get_title_says_edit(self, logged_in_client):
        """The page title says 'Edit Expense'."""
        client, _ = logged_in_client
        resp = client.get("/expenses/1/edit")
        html = resp.data.decode()
        assert "Edit Expense" in html

    def test_get_submit_button_says_save_changes(self, logged_in_client):
        """The submit button label is 'Save Changes'."""
        client, _ = logged_in_client
        resp = client.get("/expenses/1/edit")
        html = resp.data.decode()
        assert "Save Changes" in html


# ============================================================================ #
# DoD 2, 3 — Valid POST updates the row and redirects to /profile            #
# ============================================================================ #

class TestValidUpdate:
    """A POST with fully valid data must update the row and redirect to /profile."""

    def _valid_payload(self, **overrides):
        base = {
            "amount": "250.75",
            "category": "Transport",
            "date": "2026-06-10",
            "description": "Updated description",
        }
        base.update(overrides)
        return base

    def test_valid_post_redirects_to_profile(self, logged_in_client):
        """DoD 3: A successful POST redirects (302) to /profile."""
        client, td = logged_in_client
        resp = client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(),
        )
        assert resp.status_code == 302
        assert "/profile" in resp.headers["Location"]

    def test_valid_post_updates_amount(self, logged_in_client):
        """DoD 2: The stored amount matches the submitted value."""
        client, td = logged_in_client
        client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(amount="250.75"),
        )
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT amount FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()
        conn.close()
        assert row is not None
        assert abs(row["amount"] - 250.75) < 0.001

    def test_valid_post_updates_category(self, logged_in_client):
        """DoD 2: The stored category matches the submitted value."""
        client, td = logged_in_client
        client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(category="Health"),
        )
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT category FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()
        conn.close()
        assert row["category"] == "Health"

    def test_valid_post_updates_date(self, logged_in_client):
        """DoD 2: The stored date matches the submitted ISO date."""
        client, td = logged_in_client
        client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(date="2026-07-01"),
        )
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT date FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()
        conn.close()
        assert row["date"] == "2026-07-01"

    def test_valid_post_updates_description(self, logged_in_client):
        """DoD 2: The stored description matches the submitted text."""
        client, td = logged_in_client
        client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(description="New description text"),
        )
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()
        conn.close()
        assert row["description"] == "New description text"

    def test_valid_post_preserves_user_id(self, logged_in_client):
        """DoD 2: The expense remains associated with the owner's user_id."""
        client, td = logged_in_client
        client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(),
        )
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT user_id FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()
        conn.close()
        assert row["user_id"] == td["user_id"]

    def test_valid_post_preserves_created_at(self, logged_in_client):
        """DoD 2: created_at is not overwritten by the UPDATE."""
        client, td = logged_in_client
        conn = td["make_conn"]()
        original_created_at = conn.execute(
            "SELECT created_at FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()["created_at"]
        conn.close()

        client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(),
        )
        conn = td["make_conn"]()
        new_created_at = conn.execute(
            "SELECT created_at FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()["created_at"]
        conn.close()
        assert new_created_at == original_created_at

    def test_valid_post_does_not_create_new_row(self, logged_in_client):
        """DoD 2: A successful update does not add a new row."""
        client, td = logged_in_client
        client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(),
        )
        conn = td["make_conn"]()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_valid_post_flash_message_after_redirect(self, logged_in_client):
        """DoD 3: 'Expense updated successfully!' is visible after redirect."""
        client, td = logged_in_client
        resp = client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(),
            follow_redirects=True,
        )
        assert "Expense updated successfully!" in resp.data.decode()

    def test_valid_post_visible_on_profile(self, logged_in_client):
        """DoD 3: New values appear in the Recent Transactions table on /profile."""
        client, td = logged_in_client
        client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(
                amount="500.00", category="Bills", description="Visible on profile"
            ),
        )
        resp = client.get("/profile", follow_redirects=True)
        html = resp.data.decode()
        assert "500.00" in html
        assert "Visible on profile" in html

    def test_valid_post_optional_description_empty(self, logged_in_client):
        """An empty description is accepted (mirrors the Add flow)."""
        client, td = logged_in_client
        resp = client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(description=""),
        )
        assert resp.status_code == 302
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()
        conn.close()
        assert row["description"] in (None, "")

    def test_valid_post_integer_amount_accepted(self, logged_in_client):
        """An integer amount string is accepted."""
        client, td = logged_in_client
        resp = client.post(
            f"/expenses/{td['expense_id']}/edit",
            data=self._valid_payload(amount="500"),
        )
        assert resp.status_code == 302
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT amount FROM expenses WHERE id = ?", (td["expense_id"],)
        ).fetchone()
        conn.close()
        assert abs(row["amount"] - 500) < 0.001


# ============================================================================ #
# DoD 4 — Invalid data shows a validation error and does NOT modify the row   #
# ============================================================================ #

class TestValidationErrors:
    """POST with invalid data must return a 400 with an inline error; row unchanged."""

    def _post(self, logged_in_client, **data):
        client, td = logged_in_client
        return client.post(f"/expenses/{td['expense_id']}/edit", data=data)

    # ---- Amount validation -------------------------------------------------

    def test_negative_amount_returns_400(self, logged_in_client):
        """DoD 4: A negative amount is rejected with HTTP 400."""
        resp = self._post(
            logged_in_client, amount="-50", category="Food",
            date="2026-06-01", description="",
        )
        assert resp.status_code == 400

    def test_negative_amount_shows_error(self, logged_in_client):
        """DoD 4: A negative amount triggers 'Amount must be a positive number.'."""
        resp = self._post(
            logged_in_client, amount="-50", category="Food",
            date="2026-06-01", description="",
        )
        assert "Amount must be a positive number." in resp.data.decode()

    def test_zero_amount_rejected(self, logged_in_client):
        """DoD 4: Amount of 0 is not a positive number and must be rejected."""
        resp = self._post(
            logged_in_client, amount="0", category="Food",
            date="2026-06-01", description="",
        )
        assert resp.status_code == 400

    def test_non_numeric_amount_rejected(self, logged_in_client):
        """DoD 4: A non-numeric amount string is rejected with HTTP 400."""
        resp = self._post(
            logged_in_client, amount="abc", category="Food",
            date="2026-06-01", description="",
        )
        assert resp.status_code == 400

    def test_empty_amount_rejected(self, logged_in_client):
        """DoD 4: An empty amount field is rejected with HTTP 400."""
        resp = self._post(
            logged_in_client, amount="", category="Food",
            date="2026-06-01", description="",
        )
        assert resp.status_code == 400

    # ---- Category validation -----------------------------------------------

    def test_empty_category_returns_400(self, logged_in_client):
        """DoD 4: An empty category is rejected with HTTP 400."""
        resp = self._post(
            logged_in_client, amount="100", category="",
            date="2026-06-01", description="",
        )
        assert resp.status_code == 400

    def test_invalid_category_returns_400(self, logged_in_client):
        """DoD 4: A category not in CATEGORY_META is rejected with HTTP 400."""
        resp = self._post(
            logged_in_client, amount="100", category="NotARealCategory",
            date="2026-06-01", description="",
        )
        assert resp.status_code == 400

    def test_invalid_category_shows_error(self, logged_in_client):
        """DoD 4: An invalid category triggers a 'valid category' error."""
        resp = self._post(
            logged_in_client, amount="100", category="NotARealCategory",
            date="2026-06-01", description="",
        )
        html = resp.data.decode()
        assert "category" in html.lower() or "valid" in html.lower()

    # ---- Date validation ---------------------------------------------------

    def test_invalid_date_format_rejected(self, logged_in_client):
        """DoD 4: A date in a wrong format is rejected with HTTP 400."""
        resp = self._post(
            logged_in_client, amount="100", category="Food",
            date="01/06/2026", description="",
        )
        assert resp.status_code == 400

    def test_empty_date_rejected(self, logged_in_client):
        """DoD 4: An empty date is rejected with HTTP 400."""
        resp = self._post(
            logged_in_client, amount="100", category="Food",
            date="", description="",
        )
        assert resp.status_code == 400

    def test_invalid_date_shows_error(self, logged_in_client):
        """DoD 4: An invalid date triggers a 'valid date' error."""
        resp = self._post(
            logged_in_client, amount="100", category="Food",
            date="not-a-date", description="",
        )
        html = resp.data.decode()
        assert "date" in html.lower() or "valid" in html.lower()

    # ---- Description length validation -------------------------------------

    def test_description_over_200_chars_rejected(self, logged_in_client):
        """DoD 4: A description exceeding 200 characters is rejected."""
        long_desc = "x" * 201
        resp = self._post(
            logged_in_client, amount="100", category="Food",
            date="2026-06-01", description=long_desc,
        )
        assert resp.status_code == 400

    def test_description_exactly_200_chars_accepted(self, logged_in_client):
        """DoD 4 boundary: A 200-character description is the max and must succeed."""
        boundary_desc = "a" * 200
        resp = self._post(
            logged_in_client, amount="100", category="Food",
            date="2026-06-01", description=boundary_desc,
        )
        assert resp.status_code == 302

    # ---- Original row is unchanged -----------------------------------------

    def test_invalid_post_does_not_modify_row(self, logged_in_client):
        """DoD 4: A failed validation must not write any changes to the DB."""
        self._post(
            logged_in_client, amount="-99", category="Food",
            date="2026-06-01", description="",
        )
        client, td = logged_in_client
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (td["expense_id"],),
        ).fetchone()
        conn.close()
        assert row["amount"] == 150.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-05-15"
        assert row["description"] == "Original lunch"

    # ---- Form values preserved on error ------------------------------------

    def test_form_values_preserved_on_error(self, logged_in_client):
        """DoD 4: On validation error, entered values are re-rendered."""
        resp = self._post(
            logged_in_client, amount="-10", category="Shopping",
            date="2026-06-15", description="Gift purchase",
        )
        html = resp.data.decode()
        assert "-10" in html
        assert "Gift purchase" in html

    def test_error_page_still_shows_category_options(self, logged_in_client):
        """DoD 4 + 5: On error the category dropdown is still populated."""
        resp = self._post(
            logged_in_client, amount="-5", category="Food",
            date="2026-06-01", description="",
        )
        html = resp.data.decode()
        assert any(cat in html for cat in VALID_CATEGORIES)


# ============================================================================ #
# DoD 8 — Non-existent id and other-user id both return 404                  #
# ============================================================================ #

class TestOwnershipAndNotFound:
    """Missing or foreign rows must return 404, not a distinguishing error."""

    def test_get_nonexistent_id_returns_404(self, logged_in_client):
        """DoD 8: GET /expenses/9999/edit (no such row) returns 404."""
        client, _ = logged_in_client
        resp = client.get("/expenses/9999/edit")
        assert resp.status_code == 404

    def test_post_nonexistent_id_returns_404(self, logged_in_client):
        """DoD 8: POST to /expenses/9999/edit returns 404."""
        client, _ = logged_in_client
        resp = client.post(
            "/expenses/9999/edit",
            data={"amount": "100", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )
        assert resp.status_code == 404

    def test_get_other_users_expense_returns_404(self, logged_in_client, test_db):
        """DoD 8: GET another user's expense returns 404 (no info leak)."""
        _seed_other_user_with_expense(test_db)
        client, _ = logged_in_client
        conn = test_db["make_conn"]()
        other_expense_id = conn.execute(
            "SELECT id FROM expenses WHERE user_id != ? LIMIT 1",
            (test_db["user_id"],),
        ).fetchone()["id"]
        conn.close()
        resp = client.get(f"/expenses/{other_expense_id}/edit")
        assert resp.status_code == 404

    def test_post_other_users_expense_returns_404(self, logged_in_client, test_db):
        """DoD 8: POST to another user's expense returns 404 and does not change it."""
        _seed_other_user_with_expense(test_db)
        client, _ = logged_in_client
        conn = test_db["make_conn"]()
        other_expense_id = conn.execute(
            "SELECT id FROM expenses WHERE user_id != ? LIMIT 1",
            (test_db["user_id"],),
        ).fetchone()["id"]
        conn.close()
        resp = client.post(
            f"/expenses/{other_expense_id}/edit",
            data={"amount": "100", "category": "Food",
                  "date": "2026-06-01", "description": "Hijack"},
        )
        assert resp.status_code == 404

        conn = test_db["make_conn"]()
        row = conn.execute(
            "SELECT amount, category, date, description FROM expenses "
            "WHERE id = ?",
            (other_expense_id,),
        ).fetchone()
        conn.close()
        assert row["amount"] == 999.0
        assert row["category"] == "Other"
        assert row["description"] == "Other user expense"

    def test_404_does_not_flash_distinguishing_error(self, logged_in_client, test_db):
        """DoD 8: A 404 must not include a flash that names the actual reason."""
        _seed_other_user_with_expense(test_db)
        client, _ = logged_in_client
        conn = test_db["make_conn"]()
        other_expense_id = conn.execute(
            "SELECT id FROM expenses WHERE user_id != ? LIMIT 1",
            (test_db["user_id"],),
        ).fetchone()["id"]
        conn.close()
        resp = client.get(f"/expenses/{other_expense_id}/edit", follow_redirects=True)
        body = resp.data.decode().lower()
        assert "permission" not in body
        assert "not yours" not in body
        assert "another user" not in body


# ============================================================================ #
# DoD 9, 10 — Profile template surfaces an Edit control per row              #
# ============================================================================ #

class TestProfileEditLinks:
    """The profile page must render an Edit control per row, built from tx.id."""

    def test_profile_row_contains_edit_link(self, logged_in_client):
        """DoD 9: For each transaction row, the HTML has an edit link."""
        client, td = logged_in_client
        resp = client.get("/profile")
        html = resp.data.decode()
        assert f'href="/expenses/{td["expense_id"]}/edit"' in html

    def test_profile_edit_link_url_uses_row_id(self, logged_in_client):
        """DoD 9 + 10: The link href matches url_for('edit_expense', id=tx.id)."""
        client, td = logged_in_client
        resp = client.get("/profile")
        html = resp.data.decode()
        assert f"/expenses/{td['expense_id']}/edit" in html

    def test_profile_edit_link_uses_pencil_icon(self, logged_in_client):
        """DoD 9: The edit cell renders the Lucide pencil icon."""
        client, _ = logged_in_client
        resp = client.get("/profile")
        assert 'data-lucide="pencil"' in resp.data.decode()

    def test_profile_header_has_actions_column(self, logged_in_client):
        """DoD 9: The <thead> has 5 <th> cells (Date, Description, Category, Amount, Actions)."""
        import re
        client, _ = logged_in_client
        resp = client.get("/profile")
        html = resp.data.decode()
        thead_start = html.find("<thead>")
        thead_end = html.find("</thead>")
        assert thead_start != -1 and thead_end != -1
        thead = html[thead_start:thead_end]
        opening_th = re.findall(r"<th[\s>]", thead)
        assert len(opening_th) == 5


# ============================================================================ #
# DoD 10 — get_recent_transactions surfaces 'id' for the link                 #
# ============================================================================ #

class TestQueryHelpers:
    """Direct unit tests for the new query helpers."""

    def test_get_recent_transactions_returns_id(self, test_db):
        """DoD 10: get_recent_transactions surfaces 'id' in each dict."""
        txs = queries_module.get_recent_transactions(test_db["user_id"])
        assert len(txs) == 1
        assert "id" in txs[0]
        assert txs[0]["id"] == test_db["expense_id"]

    def test_get_expense_by_id_returns_dict_for_owner(self, test_db):
        """get_expense_by_id returns the row dict when the owner requests it."""
        row = queries_module.get_expense_by_id(
            test_db["expense_id"], test_db["user_id"]
        )
        assert row is not None
        assert row["id"] == test_db["expense_id"]
        assert row["amount"] == 150.0
        assert row["category"] == "Food"

    def test_get_expense_by_id_returns_none_for_other_user(self, test_db):
        """get_expense_by_id returns None when the user does not own the row."""
        _seed_other_user_with_expense(test_db)
        conn = test_db["make_conn"]()
        other_expense_id = conn.execute(
            "SELECT id FROM expenses WHERE user_id != ? LIMIT 1",
            (test_db["user_id"],),
        ).fetchone()["id"]
        conn.close()
        row = queries_module.get_expense_by_id(other_expense_id, test_db["user_id"])
        assert row is None

    def test_get_expense_by_id_returns_none_for_missing_id(self, test_db):
        """get_expense_by_id returns None for a non-existent id."""
        row = queries_module.get_expense_by_id(99999, test_db["user_id"])
        assert row is None

    def test_update_expense_returns_rowcount_one(self, test_db):
        """update_expense returns 1 on a successful update."""
        rc = queries_module.update_expense(
            test_db["expense_id"], test_db["user_id"],
            300.0, "Bills", "2026-06-15", "Updated",
        )
        assert rc == 1

    def test_update_expense_returns_rowcount_zero_for_other_user(self, test_db):
        """update_expense returns 0 when the user does not own the row."""
        _seed_other_user_with_expense(test_db)
        conn = test_db["make_conn"]()
        other_expense_id = conn.execute(
            "SELECT id FROM expenses WHERE user_id != ? LIMIT 1",
            (test_db["user_id"],),
        ).fetchone()["id"]
        conn.close()
        rc = queries_module.update_expense(
            other_expense_id, test_db["user_id"],
            300.0, "Bills", "2026-06-15", "Hijack",
        )
        assert rc == 0

    def test_update_expense_does_not_touch_user_id_or_created_at(self, test_db):
        """update_expense must not overwrite user_id or created_at."""
        conn = test_db["make_conn"]()
        before = conn.execute(
            "SELECT user_id, created_at FROM expenses WHERE id = ?",
            (test_db["expense_id"],),
        ).fetchone()
        conn.close()
        queries_module.update_expense(
            test_db["expense_id"], test_db["user_id"],
            999.0, "Other", "2026-12-31", "X",
        )
        conn = test_db["make_conn"]()
        after = conn.execute(
            "SELECT user_id, created_at FROM expenses WHERE id = ?",
            (test_db["expense_id"],),
        ).fetchone()
        conn.close()
        assert after["user_id"] == before["user_id"]
        assert after["created_at"] == before["created_at"]
