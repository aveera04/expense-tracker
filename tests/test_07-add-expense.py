"""
tests/test_07-add-expense.py — Tests for Spec 07: Add Expense

Strategy
--------
* A ``test_db`` fixture creates an isolated temporary SQLite database that
  mirrors the schema in database/db.py and monkeypatches ``get_db`` so that
  both app.py and database.queries use the test DB — the real spendly.db is
  never touched.
* A seed user is inserted with a known plain-text password so that the
  ``logged_in_client`` fixture can authenticate via the real /login route,
  establishing a proper session cookie.
* All tests are fully independent; no test relies on execution order.
* Every test maps to at least one Definition-of-Done item from the spec.

DoD coverage
------------
DoD 1  — GET /expenses/add while logged in shows the expense form.
DoD 2  — POST with valid data inserts a record into the expenses table.
DoD 3  — After a successful POST the user is redirected to the profile page.
DoD 4  — POST with invalid data (negative amount, empty category) shows a
          validation error on the page.
DoD 5  — The form includes a dropdown with categories from CATEGORY_META.
DoD 6  — Unauthenticated users are redirected to the login page.
"""

import sqlite3

import pytest
from werkzeug.security import generate_password_hash

import app as flask_app


# ============================================================================ #
# Constants — must match CATEGORY_META in app.py                               #
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
# Fixtures                                                                      #
# ============================================================================ #

@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """
    Isolated in-memory-style SQLite DB backed by a temp file.

    * Creates the users and expenses tables.
    * Seeds one test user (test@spendly.com / testpass1).
    * Monkeypatches database.db.get_db AND flask_app.get_db so the app never
      touches the real spendly.db.
    * Returns a dict with connection factory, user info, and the user's DB id.
    """
    db_path = str(tmp_path / "test_add_expense.db")

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
    }


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
    # Login must succeed (redirect to /profile)
    assert resp.status_code == 302, (
        f"Login fixture failed — expected 302, got {resp.status_code}"
    )
    return client, test_db


# ============================================================================ #
# DoD 6 — Auth guard: unauthenticated users are redirected to /login           #
# ============================================================================ #

class TestAuthGuard:
    """Unauthenticated access to /expenses/add must redirect to /login."""

    def test_get_unauthenticated_redirects(self, client, test_db):
        """DoD 6: GET /expenses/add without a session → 302 to /login."""
        resp = client.get("/expenses/add")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_post_unauthenticated_redirects(self, client, test_db):
        """DoD 6: POST /expenses/add without a session → 302 to /login."""
        resp = client.post(
            "/expenses/add",
            data={
                "amount": "100",
                "category": "Food",
                "date": "2026-01-15",
                "description": "Lunch",
            },
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_unauthenticated_no_expense_inserted(self, client, test_db):
        """DoD 6: unauthenticated POST must NOT insert anything into the DB."""
        client.post(
            "/expenses/add",
            data={
                "amount": "50",
                "category": "Food",
                "date": "2026-01-10",
                "description": "Test",
            },
        )
        conn = test_db["make_conn"]()
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        assert count == 0


# ============================================================================ #
# DoD 1 — GET /expenses/add while logged in shows the expense form             #
# ============================================================================ #

class TestGetAddExpenseForm:
    """GET /expenses/add for a logged-in user must render the expense form."""

    def test_get_returns_200(self, logged_in_client):
        """DoD 1: GET /expenses/add returns HTTP 200 for an authenticated user."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        assert resp.status_code == 200

    def test_get_contains_form_element(self, logged_in_client):
        """DoD 1: The response body contains an HTML <form> element."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        html = resp.data.decode()
        assert "<form" in html

    def test_get_contains_amount_field(self, logged_in_client):
        """DoD 1: The form contains an 'amount' input field."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        html = resp.data.decode()
        assert 'name="amount"' in html

    def test_get_contains_category_field(self, logged_in_client):
        """DoD 1: The form contains a 'category' field (select/input)."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        html = resp.data.decode()
        assert 'name="category"' in html

    def test_get_contains_date_field(self, logged_in_client):
        """DoD 1: The form contains a 'date' input field."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        html = resp.data.decode()
        assert 'name="date"' in html

    def test_get_contains_description_field(self, logged_in_client):
        """DoD 1: The form contains a 'description' input/textarea field."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        html = resp.data.decode()
        assert 'name="description"' in html

    def test_get_date_field_prefilled_with_today(self, logged_in_client):
        """DoD 1: The date field is pre-filled with today's ISO date."""
        from datetime import date
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        html = resp.data.decode()
        today = date.today().isoformat()
        assert today in html


# ============================================================================ #
# DoD 5 — Category dropdown is populated from CATEGORY_META                   #
# ============================================================================ #

class TestCategoryDropdown:
    """The form's category dropdown must list every key from CATEGORY_META."""

    def test_all_categories_present_in_form(self, logged_in_client):
        """DoD 5: Every CATEGORY_META key appears as a selectable option."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        html = resp.data.decode()
        for category in VALID_CATEGORIES:
            assert category in html, (
                f"Category '{category}' missing from the add-expense form"
            )

    def test_food_category_option_present(self, logged_in_client):
        """DoD 5: 'Food' category option is visible in the form."""
        client, _ = logged_in_client
        html = client.get("/expenses/add").data.decode()
        assert "Food" in html

    def test_transport_category_option_present(self, logged_in_client):
        """DoD 5: 'Transport' category option is visible in the form."""
        client, _ = logged_in_client
        html = client.get("/expenses/add").data.decode()
        assert "Transport" in html

    def test_other_category_option_present(self, logged_in_client):
        """DoD 5: 'Other' category option is visible in the form."""
        client, _ = logged_in_client
        html = client.get("/expenses/add").data.decode()
        assert "Other" in html


# ============================================================================ #
# DoD 2 & 3 — Valid POST inserts a DB record and redirects to /profile        #
# ============================================================================ #

class TestValidPost:
    """A POST with fully valid data must save the expense and redirect to /profile."""

    def _valid_payload(self, **overrides):
        base = {
            "amount": "150.50",
            "category": "Food",
            "date": "2026-06-01",
            "description": "Lunch at the office",
        }
        base.update(overrides)
        return base

    def test_valid_post_redirects_to_profile(self, logged_in_client):
        """DoD 3: A successful POST redirects (302) to /profile."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data=self._valid_payload())
        assert resp.status_code == 302
        assert "/profile" in resp.headers["Location"]

    def test_valid_post_inserts_expense_row(self, logged_in_client):
        """DoD 2: A successful POST inserts exactly one row into the expenses table."""
        client, td = logged_in_client
        client.post("/expenses/add", data=self._valid_payload())
        conn = td["make_conn"]()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_valid_post_correct_amount_stored(self, logged_in_client):
        """DoD 2: The stored amount matches the submitted value."""
        client, td = logged_in_client
        client.post("/expenses/add", data=self._valid_payload(amount="250.75"))
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT amount FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()
        conn.close()
        assert row is not None
        assert abs(row["amount"] - 250.75) < 0.001

    def test_valid_post_correct_category_stored(self, logged_in_client):
        """DoD 2: The stored category matches the submitted value."""
        client, td = logged_in_client
        client.post("/expenses/add", data=self._valid_payload(category="Transport"))
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT category FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()
        conn.close()
        assert row["category"] == "Transport"

    def test_valid_post_correct_date_stored(self, logged_in_client):
        """DoD 2: The stored date matches the submitted ISO date."""
        client, td = logged_in_client
        client.post("/expenses/add", data=self._valid_payload(date="2026-05-20"))
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT date FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()
        conn.close()
        assert row["date"] == "2026-05-20"

    def test_valid_post_correct_description_stored(self, logged_in_client):
        """DoD 2: The stored description matches the submitted text."""
        client, td = logged_in_client
        client.post("/expenses/add", data=self._valid_payload(description="Gym membership"))
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT description FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()
        conn.close()
        assert row["description"] == "Gym membership"

    def test_valid_post_links_to_correct_user(self, logged_in_client):
        """DoD 2: The expense is associated with the logged-in user's DB id."""
        client, td = logged_in_client
        client.post("/expenses/add", data=self._valid_payload())
        conn = td["make_conn"]()
        row = conn.execute(
            "SELECT user_id FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()
        conn.close()
        assert row["user_id"] == td["user_id"]

    def test_valid_post_flash_message_after_redirect(self, logged_in_client):
        """DoD 3: Flash message 'Expense added successfully!' is visible after redirect."""
        client, _ = logged_in_client
        resp = client.post(
            "/expenses/add",
            data=self._valid_payload(),
            follow_redirects=True,
        )
        html = resp.data.decode()
        assert "Expense added successfully!" in html

    def test_valid_post_optional_description_empty(self, logged_in_client):
        """DoD 2: An empty description is accepted (description is optional)."""
        client, td = logged_in_client
        resp = client.post(
            "/expenses/add",
            data=self._valid_payload(description=""),
        )
        assert resp.status_code == 302
        conn = td["make_conn"]()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_valid_post_integer_amount(self, logged_in_client):
        """DoD 2: An integer amount string (e.g. '500') is accepted."""
        client, td = logged_in_client
        resp = client.post(
            "/expenses/add",
            data=self._valid_payload(amount="500"),
        )
        assert resp.status_code == 302

    def test_multiple_valid_posts_create_multiple_rows(self, logged_in_client):
        """DoD 2: Two sequential valid POSTs result in two rows in the DB."""
        client, td = logged_in_client
        client.post("/expenses/add", data=self._valid_payload(amount="100", date="2026-06-01"))
        client.post("/expenses/add", data=self._valid_payload(amount="200", date="2026-06-02"))
        conn = td["make_conn"]()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_valid_post_all_valid_categories_accepted(self, logged_in_client):
        """DoD 2: Every category defined in CATEGORY_META is accepted without error."""
        client, td = logged_in_client
        for i, category in enumerate(VALID_CATEGORIES):
            resp = client.post(
                "/expenses/add",
                data={
                    "amount": "10.00",
                    "category": category,
                    "date": f"2026-0{(i % 9) + 1}-01",
                    "description": "",
                },
            )
            assert resp.status_code == 302, (
                f"Category '{category}' was unexpectedly rejected"
            )


# ============================================================================ #
# DoD 4 — Invalid data shows a validation error and does NOT insert a row      #
# ============================================================================ #

class TestValidationErrors:
    """POST with invalid data must return a 400 with an inline error; no DB row created."""

    def _post(self, client, **data):
        return client.post("/expenses/add", data=data)

    # ---- Amount validation -------------------------------------------------

    def test_negative_amount_returns_400(self, logged_in_client):
        """DoD 4: A negative amount is rejected with HTTP 400."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="-50", category="Food", date="2026-06-01", description=""
        )
        assert resp.status_code == 400

    def test_negative_amount_shows_error_message(self, logged_in_client):
        """DoD 4: A negative amount causes a validation error message in the response."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="-50", category="Food", date="2026-06-01", description=""
        )
        html = resp.data.decode()
        assert "Amount must be a positive number." in html

    def test_zero_amount_rejected(self, logged_in_client):
        """DoD 4: Amount of 0 is not a positive number and must be rejected."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="0", category="Food", date="2026-06-01", description=""
        )
        assert resp.status_code == 400

    def test_zero_amount_shows_error_message(self, logged_in_client):
        """DoD 4: Amount of 0 triggers the 'positive number' error message."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="0", category="Food", date="2026-06-01", description=""
        )
        html = resp.data.decode()
        assert "Amount must be a positive number." in html

    def test_non_numeric_amount_rejected(self, logged_in_client):
        """DoD 4: A non-numeric amount string is rejected with HTTP 400."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="abc", category="Food", date="2026-06-01", description=""
        )
        assert resp.status_code == 400

    def test_empty_amount_rejected(self, logged_in_client):
        """DoD 4: An empty amount field is rejected with HTTP 400."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="", category="Food", date="2026-06-01", description=""
        )
        assert resp.status_code == 400

    # ---- Category validation -----------------------------------------------

    def test_empty_category_returns_400(self, logged_in_client):
        """DoD 4: An empty category is rejected with HTTP 400."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="100", category="", date="2026-06-01", description=""
        )
        assert resp.status_code == 400

    def test_empty_category_shows_error_message(self, logged_in_client):
        """DoD 4: An empty category triggers a validation error message."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="100", category="", date="2026-06-01", description=""
        )
        html = resp.data.decode()
        assert "category" in html.lower() or "valid" in html.lower()

    def test_invalid_category_value_rejected(self, logged_in_client):
        """DoD 4: A category not in CATEGORY_META is rejected with HTTP 400."""
        client, _ = logged_in_client
        resp = self._post(
            client,
            amount="100",
            category="NotARealCategory",
            date="2026-06-01",
            description="",
        )
        assert resp.status_code == 400

    def test_invalid_category_shows_error_message(self, logged_in_client):
        """DoD 4: An invalid category value triggers a validation error message."""
        client, _ = logged_in_client
        resp = self._post(
            client,
            amount="100",
            category="NotARealCategory",
            date="2026-06-01",
            description="",
        )
        html = resp.data.decode()
        assert "category" in html.lower() or "valid" in html.lower()

    # ---- Date validation ---------------------------------------------------

    def test_invalid_date_format_rejected(self, logged_in_client):
        """DoD 4: A date in a wrong format (not ISO) is rejected with HTTP 400."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="100", category="Food", date="01/06/2026", description=""
        )
        assert resp.status_code == 400

    def test_empty_date_rejected(self, logged_in_client):
        """DoD 4: An empty date is rejected with HTTP 400."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="100", category="Food", date="", description=""
        )
        assert resp.status_code == 400

    def test_invalid_date_shows_error_message(self, logged_in_client):
        """DoD 4: An invalid date triggers a validation error message."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="100", category="Food", date="not-a-date", description=""
        )
        html = resp.data.decode()
        assert "date" in html.lower() or "valid" in html.lower()

    # ---- Description length validation -------------------------------------

    def test_description_over_200_chars_rejected(self, logged_in_client):
        """DoD 4: A description exceeding 200 characters is rejected with HTTP 400."""
        client, _ = logged_in_client
        long_desc = "x" * 201
        resp = self._post(
            client,
            amount="100",
            category="Food",
            date="2026-06-01",
            description=long_desc,
        )
        assert resp.status_code == 400

    def test_description_over_200_chars_shows_error(self, logged_in_client):
        """DoD 4: Oversized description triggers an error mentioning the 200-char limit."""
        client, _ = logged_in_client
        long_desc = "x" * 201
        resp = self._post(
            client,
            amount="100",
            category="Food",
            date="2026-06-01",
            description=long_desc,
        )
        html = resp.data.decode()
        assert "200" in html or "description" in html.lower()

    def test_description_exactly_200_chars_accepted(self, logged_in_client):
        """DoD 4 (boundary): A 200-character description is the maximum and must succeed."""
        client, td = logged_in_client
        boundary_desc = "a" * 200
        resp = self._post(
            client,
            amount="100",
            category="Food",
            date="2026-06-01",
            description=boundary_desc,
        )
        assert resp.status_code == 302

    # ---- No DB row on validation error -------------------------------------

    def test_invalid_post_does_not_insert_row(self, logged_in_client):
        """DoD 4: A failed validation must not write any row to the expenses table."""
        client, td = logged_in_client
        self._post(
            client, amount="-99", category="Food", date="2026-06-01", description=""
        )
        conn = td["make_conn"]()
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (td["user_id"],)
        ).fetchone()[0]
        conn.close()
        assert count == 0

    # ---- Form values preserved on validation error -------------------------

    def test_form_values_preserved_on_error(self, logged_in_client):
        """DoD 4 (spec rule): On validation error, entered values are re-rendered in the form."""
        client, _ = logged_in_client
        resp = self._post(
            client,
            amount="-10",
            category="Shopping",
            date="2026-06-15",
            description="Gift purchase",
        )
        html = resp.data.decode()
        # The submitted (invalid) amount and the description should be re-populated
        assert "-10" in html
        assert "Gift purchase" in html

    def test_error_page_still_shows_category_options(self, logged_in_client):
        """DoD 4 + DoD 5: On validation error the category dropdown is still rendered."""
        client, _ = logged_in_client
        resp = self._post(
            client, amount="-5", category="Food", date="2026-06-01", description=""
        )
        html = resp.data.decode()
        # At least one valid category key must still appear in the re-rendered form
        assert any(cat in html for cat in VALID_CATEGORIES)
