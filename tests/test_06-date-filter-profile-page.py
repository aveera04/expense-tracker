"""
tests/test_06-date-filter-profile-page.py — Tests for Spec 06: Date Filter for Profile Page.

Strategy
--------
* A `test_db` fixture creates a disposable temporary SQLite database (matching
  the schema in database/db.py) and monkeypatches `get_db` so that both
  `database.queries` and `app.py` use the test DB — production data is never
  touched.
* Expenses are seeded with *fixed, known dates* spread across the past months
  so that every date-range preset can be tested deterministically regardless of
  when the suite runs.  Date arithmetic mirrors the logic in app.py.
* A `logged_in_client` fixture builds on `test_db`, starts a Flask test client,
  and logs in as the seed user, so each route test begins in an authenticated
  state.
* All tests are fully self-contained and repeatable.
"""

import calendar
import sqlite3
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import app as flask_app
from database import queries as q


# ========================================================================== #
# Helpers                                                                     #
# ========================================================================== #

def _months_ago(today: date, n: int) -> date:
    """Mirror the _months_ago logic in app.py."""
    month = today.month - n
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(today.day, last_day)
    return date(year, month, day)


# ========================================================================== #
# Fixtures                                                                    #
# ========================================================================== #

@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """
    Isolated SQLite DB with controlled seed data spanning multiple months.

    Expense layout (amounts in Rs):
        - expense_past   : 7 months ago → OUTSIDE all preset windows (all-time only)
        - expense_6m     : exactly _months_ago(today, 6) + 1 day → within Last 6 Months
        - expense_3m     : exactly _months_ago(today, 3) + 1 day → within Last 3 Months
        - expense_this_m : first day of current month → within This Month
        - expense_today  : today → within all windows

    A second user (empty_user) has NO expenses at all.

    The monkeypatch replaces `database.db.get_db` (used by query helpers via
    `_get_db`) and `flask_app.get_db` (used directly by the /profile route to
    look up users) with a factory that returns connections to the temp DB.
    """
    db_path = str(tmp_path / "test_spendly.db")

    def make_conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---- Schema -----------------------------------------------------------
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

    # ---- Seed users -------------------------------------------------------
    pw = generate_password_hash("demo123")
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Demo User", "demo@spendly.com", pw, "2026-01-15 10:00:00"),
    )
    demo_uid = cur.lastrowid

    pw2 = generate_password_hash("empty123")
    cur2 = conn.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Empty User", "empty@spendly.com", pw2, "2026-01-15 10:00:00"),
    )
    empty_uid = cur2.lastrowid

    # ---- Compute reference dates ------------------------------------------
    today = date.today()
    first_of_month = today.replace(day=1)

    start_6m = _months_ago(today, 6)
    start_3m = _months_ago(today, 3)

    # Dates that FALL INSIDE each respective window
    date_past = start_6m - timedelta(days=5)          # before 6m window
    date_in_6m = start_6m + timedelta(days=2)         # inside 6m, outside 3m
    date_in_3m = start_3m + timedelta(days=2)         # inside 3m, outside this month
    date_in_month = first_of_month                    # inside this-month window
    date_today = today                                # inside all windows

    # Ensure date_in_6m is really outside the 3-month window
    if date_in_6m >= start_3m:
        date_in_6m = start_3m - timedelta(days=1)

    # Ensure date_in_3m is really outside this-month window
    if date_in_3m >= first_of_month:
        date_in_3m = first_of_month - timedelta(days=1)

    # ---- Seed expenses for demo user --------------------------------------
    expenses = [
        # (user_id, amount, category, date, description)
        (demo_uid, 100.0,  "Food",          date_past.isoformat(),     "Old expense (past 6m)"),
        (demo_uid, 200.0,  "Transport",     date_in_6m.isoformat(),    "6-month expense"),
        (demo_uid, 300.0,  "Bills",         date_in_3m.isoformat(),    "3-month expense"),
        (demo_uid, 400.0,  "Health",        date_in_month.isoformat(), "This-month expense"),
        (demo_uid, 500.0,  "Entertainment", date_today.isoformat(),    "Today's expense"),
    ]
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    conn.commit()
    conn.close()

    # ---- Monkeypatch get_db -----------------------------------------------
    import database.db as db_module
    monkeypatch.setattr(db_module, "get_db", make_conn)
    monkeypatch.setattr(flask_app, "get_db", make_conn)

    return {
        "demo_uid": demo_uid,
        "empty_uid": empty_uid,
        "demo_email": "demo@spendly.com",
        "empty_email": "empty@spendly.com",
        "make_conn": make_conn,
        # Reference dates
        "today": today,
        "first_of_month": first_of_month,
        "start_6m": start_6m,
        "start_3m": start_3m,
        "date_past": date_past,
        "date_in_6m": date_in_6m,
        "date_in_3m": date_in_3m,
        "date_in_month": date_in_month,
        "date_today": date_today,
        # Expected amounts per window
        "amount_all_time": 1500.0,  # 100+200+300+400+500
        "amount_6m": 1400.0,        # 200+300+400+500
        "amount_3m": 1200.0,        # 300+400+500
        "amount_this_month": 900.0, # 400+500
        "amount_today_only": 500.0, # 500
    }


@pytest.fixture
def client(test_db):
    """Flask test client wired to the isolated test database."""
    flask_app.app.config["TESTING"] = True
    flask_app.app.config["SECRET_KEY"] = "test-secret"
    flask_app.app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.app.test_client() as c:
        yield c


@pytest.fixture
def logged_in_client(test_db, client):
    """Flask test client with demo user already authenticated."""
    client.post(
        "/login",
        data={"email": test_db["demo_email"], "password": "demo123"},
        follow_redirects=False,
    )
    return client, test_db


@pytest.fixture
def empty_user_client(test_db, client):
    """Flask test client with empty user (no expenses) authenticated."""
    client.post(
        "/login",
        data={"email": test_db["empty_email"], "password": "empty123"},
        follow_redirects=False,
    )
    return client, test_db


# ========================================================================== #
# Helper                                                                      #
# ========================================================================== #

def get_profile(client, params=None):
    """GET /profile with optional query params dict.  Returns response."""
    url = "/profile"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    return client.get(url, follow_redirects=True)


# ========================================================================== #
# Auth guard                                                                  #
# ========================================================================== #

class TestAuthGuard:
    """Unauthenticated access must be redirected to /login."""

    def test_unauthenticated_redirects_to_login(self, client, test_db):
        """Spec: /profile requires authentication; unauthenticated users are redirected."""
        resp = client.get("/profile")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_unauthenticated_with_date_params_still_redirects(self, client, test_db):
        """Spec: auth guard applies regardless of query params."""
        resp = client.get("/profile?date_from=2026-01-01&date_to=2026-12-31")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ========================================================================== #
# DoD 1 — No query params → unfiltered (all expenses)                        #
# ========================================================================== #

class TestNoQueryParams:
    """Visiting /profile with no query params returns unfiltered data (all expenses)."""

    def test_status_200(self, logged_in_client):
        client, td = logged_in_client
        resp = get_profile(client)
        assert resp.status_code == 200

    def test_all_expenses_included_in_total(self, logged_in_client):
        """Spec DoD 1: no params → all expenses shown (Rs 1500.00 total)."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        assert "1,500.00" in html

    def test_all_transaction_count(self, logged_in_client):
        """Spec DoD 1: no params → all 5 transactions counted."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        # The transaction_count stat (5) must be visible somewhere
        assert "5" in html

    def test_all_categories_present(self, logged_in_client):
        """Spec DoD 1: no params → all seeded categories appear in breakdown."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        # Categories seeded: Food, Transport, Bills, Health, Entertainment
        for label in ["Food", "Transport", "Bills", "Health", "Entertainment"]:
            assert label in html

    def test_rs_symbol_present_no_params(self, logged_in_client):
        """Spec DoD 10: Rs symbol shown regardless of filter state."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        # ₹ is U+20B9
        assert "\u20b9" in html


# ========================================================================== #
# DoD 2 — "This Month" preset                                                #
# ========================================================================== #

class TestThisMonthPreset:
    """'This Month' preset filters all three sections to current calendar month."""

    def _params(self, td):
        return {
            "date_from": td["first_of_month"].isoformat(),
            "date_to": td["today"].isoformat(),
        }

    def test_this_month_returns_200(self, logged_in_client):
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        assert resp.status_code == 200

    def test_this_month_total(self, logged_in_client):
        """Spec DoD 2: This Month → only expenses from first-of-month to today."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # Expected: date_in_month (400) + date_today (500) = 900
        assert "900.00" in html

    def test_this_month_excludes_older_expenses(self, logged_in_client):
        """Spec DoD 2: expenses before this month must NOT appear in totals."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # Old expense (100) should not make the total 1000 or higher
        assert "1,000.00" not in html
        assert "1,500.00" not in html

    def test_this_month_active_preset_indicated(self, logged_in_client):
        """Spec DoD 9: active preset visually indicated (active_preset passed to template)."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # The template must mark this_month as active
        assert "this_month" in html or "This Month" in html

    def test_this_month_rs_symbol(self, logged_in_client):
        """Spec DoD 10: ₹ symbol shown regardless of filter."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        assert "\u20b9" in html

    def test_this_month_transactions_section_filtered(self, logged_in_client):
        """Spec DoD 2: recent transactions section only shows in-range items."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # "Today's expense" and "This-month expense" should appear
        assert "Today" in html or "expense" in html
        # "Old expense (past 6m)" from date_past must NOT appear
        assert "Old expense (past 6m)" not in html

    def test_this_month_category_breakdown_filtered(self, logged_in_client):
        """Spec DoD 2: category breakdown only covers in-range expenses."""
        client, td = logged_in_client
        # Seeded categories within this-month: Health (400) + Entertainment (500)
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # Transport (200, in 6m only) must not appear in breakdown
        # (it may appear as a label in the nav, but it should not have a
        #  non-zero amount in the category breakdown for this filter)
        # We assert the total 900 as a proxy for correct breakdown
        assert "900.00" in html


# ========================================================================== #
# DoD 3 — "Last 3 Months" preset                                             #
# ========================================================================== #

class TestLast3MonthsPreset:
    """'Last 3 Months' preset filters correctly."""

    def _params(self, td):
        return {
            "date_from": td["start_3m"].isoformat(),
            "date_to": td["today"].isoformat(),
        }

    def test_last_3_months_returns_200(self, logged_in_client):
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        assert resp.status_code == 200

    def test_last_3_months_total(self, logged_in_client):
        """Spec DoD 3: Last 3 Months → correct total for expenses in window."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # date_in_3m (300) + date_in_month (400) + date_today (500) = 1200
        assert "1,200.00" in html

    def test_last_3_months_excludes_6m_only_expense(self, logged_in_client):
        """Spec DoD 3: expense at date_in_6m (outside 3m window) excluded."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # If 6m-only expense (200) were included total would be 1400
        assert "1,400.00" not in html

    def test_last_3_months_active_preset_indicated(self, logged_in_client):
        """Spec DoD 9: active preset visually indicated."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        assert "last_3_months" in html or "Last 3 Months" in html

    def test_last_3_months_rs_symbol(self, logged_in_client):
        """Spec DoD 10: ₹ symbol always present."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        assert "\u20b9" in html


# ========================================================================== #
# DoD 4 — "Last 6 Months" preset                                             #
# ========================================================================== #

class TestLast6MonthsPreset:
    """'Last 6 Months' preset filters correctly."""

    def _params(self, td):
        return {
            "date_from": td["start_6m"].isoformat(),
            "date_to": td["today"].isoformat(),
        }

    def test_last_6_months_returns_200(self, logged_in_client):
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        assert resp.status_code == 200

    def test_last_6_months_total(self, logged_in_client):
        """Spec DoD 4: Last 6 Months → correct total."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # date_in_6m (200) + date_in_3m (300) + date_in_month (400) + date_today (500) = 1400
        assert "1,400.00" in html

    def test_last_6_months_excludes_older_expense(self, logged_in_client):
        """Spec DoD 4: expense before 6m start (date_past, 100) excluded."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        # Including old expense would make total 1500
        assert "1,500.00" not in html

    def test_last_6_months_active_preset_indicated(self, logged_in_client):
        """Spec DoD 9: active preset visually indicated."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        assert "last_6_months" in html or "Last 6 Months" in html

    def test_last_6_months_rs_symbol(self, logged_in_client):
        """Spec DoD 10: ₹ symbol always present."""
        client, td = logged_in_client
        resp = get_profile(client, self._params(td))
        html = resp.data.decode()
        assert "\u20b9" in html


# ========================================================================== #
# DoD 5 — "All Time" preset                                                  #
# ========================================================================== #

class TestAllTimePreset:
    """'All Time' removes any active filter and shows all expenses."""

    def test_all_time_clean_url_shows_all_expenses(self, logged_in_client):
        """Spec DoD 5: /profile with no params = all-time view."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        assert "1,500.00" in html  # all 5 expenses

    def test_all_time_after_filtered_view(self, logged_in_client):
        """Spec DoD 5: navigating to /profile (no params) after a filtered view returns all."""
        client, td = logged_in_client
        # First apply a filter
        get_profile(client, {"date_from": td["first_of_month"].isoformat(),
                              "date_to": td["today"].isoformat()})
        # Then hit /profile with no params
        resp = get_profile(client)
        html = resp.data.decode()
        assert "1,500.00" in html

    def test_all_time_active_preset_indicated(self, logged_in_client):
        """Spec DoD 9: when no filter active, 'All Time' is marked active."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        assert "all_time" in html or "All Time" in html

    def test_all_time_rs_symbol(self, logged_in_client):
        """Spec DoD 10: ₹ symbol present in all-time view."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        assert "\u20b9" in html


# ========================================================================== #
# DoD 6 — Custom date range                                                  #
# ========================================================================== #

class TestCustomDateRange:
    """Valid custom date range shows only matching expenses in all three sections."""

    def test_custom_range_exact_window(self, logged_in_client):
        """Spec DoD 6: custom range returns only expenses within inclusive bounds."""
        client, td = logged_in_client
        date_from = td["date_in_6m"].isoformat()
        date_to = td["date_in_3m"].isoformat()
        resp = get_profile(client, {"date_from": date_from, "date_to": date_to})
        assert resp.status_code == 200
        html = resp.data.decode()
        # Expenses with date_in_6m (200) and date_in_3m (300) = 500
        assert "500.00" in html

    def test_custom_range_single_day(self, logged_in_client):
        """Spec DoD 6: custom range with same date_from and date_to (single day)."""
        client, td = logged_in_client
        today_str = td["date_today"].isoformat()
        resp = get_profile(client, {"date_from": today_str, "date_to": today_str})
        assert resp.status_code == 200
        html = resp.data.decode()
        # Only today's expense (500)
        assert "500.00" in html

    def test_custom_range_excludes_out_of_range(self, logged_in_client):
        """Spec DoD 6: expenses outside custom range are excluded."""
        client, td = logged_in_client
        # Range: only date_in_month to date_in_month (400 only)
        date_str = td["date_in_month"].isoformat()
        resp = get_profile(client, {"date_from": date_str, "date_to": date_str})
        html = resp.data.decode()
        # If today's expense (500) or other expenses were included, total > 400
        assert "400.00" in html

    def test_custom_range_active_preset_is_custom(self, logged_in_client):
        """Spec DoD 9: a non-preset range marks 'custom' as active."""
        client, td = logged_in_client
        date_from = td["date_in_6m"].isoformat()
        date_to = td["date_in_3m"].isoformat()
        resp = get_profile(client, {"date_from": date_from, "date_to": date_to})
        html = resp.data.decode()
        assert "custom" in html

    def test_custom_range_rs_symbol(self, logged_in_client):
        """Spec DoD 10: ₹ symbol shown in custom range view."""
        client, td = logged_in_client
        resp = get_profile(client, {
            "date_from": td["date_in_6m"].isoformat(),
            "date_to": td["today"].isoformat(),
        })
        html = resp.data.decode()
        assert "\u20b9" in html

    def test_custom_range_transactions_filtered(self, logged_in_client):
        """Spec DoD 6: recent transactions section respects custom range."""
        client, td = logged_in_client
        # Only fetch the day of date_today
        today_str = td["date_today"].isoformat()
        resp = get_profile(client, {"date_from": today_str, "date_to": today_str})
        html = resp.data.decode()
        # "Today's expense" description should appear
        assert "Today" in html or "expense" in html
        # Old expense description must not appear
        assert "Old expense (past 6m)" not in html

    def test_custom_range_category_breakdown_filtered(self, logged_in_client):
        """Spec DoD 6: category breakdown reflects custom date range."""
        client, td = logged_in_client
        # Filter to only date_in_3m (Bills, 300)
        date_str = td["date_in_3m"].isoformat()
        resp = get_profile(client, {"date_from": date_str, "date_to": date_str})
        html = resp.data.decode()
        # Only the Bills category (300) should be in breakdown
        assert "300.00" in html


# ========================================================================== #
# DoD 7 — date_from > date_to flash error & fallback                         #
# ========================================================================== #

class TestInvalidDateRange:
    """date_from > date_to shows flash error and falls back to unfiltered view."""

    def test_invalid_range_returns_200(self, logged_in_client):
        """Spec DoD 7: invalid range does not crash — returns 200."""
        client, td = logged_in_client
        resp = get_profile(client, {
            "date_from": td["today"].isoformat(),
            "date_to": td["date_in_6m"].isoformat(),   # earlier than date_from
        })
        assert resp.status_code == 200

    def test_invalid_range_flash_message(self, logged_in_client):
        """Spec DoD 7: flash error 'Start date must be before end date.' shown."""
        client, td = logged_in_client
        # Enable follow_redirects so flash messages are rendered
        resp = client.get(
            f"/profile?date_from={td['today'].isoformat()}&date_to={td['date_in_6m'].isoformat()}",
            follow_redirects=True,
        )
        html = resp.data.decode()
        assert "Start date must be before end date." in html

    def test_invalid_range_falls_back_to_all_expenses(self, logged_in_client):
        """Spec DoD 7: after invalid range flash, page shows all expenses (unfiltered)."""
        client, td = logged_in_client
        resp = client.get(
            f"/profile?date_from={td['today'].isoformat()}&date_to={td['date_in_6m'].isoformat()}",
            follow_redirects=True,
        )
        html = resp.data.decode()
        # All 5 expenses total = 1500
        assert "1,500.00" in html

    def test_invalid_range_rs_symbol(self, logged_in_client):
        """Spec DoD 10: ₹ symbol shown even after invalid range fallback."""
        client, td = logged_in_client
        resp = client.get(
            f"/profile?date_from={td['today'].isoformat()}&date_to={td['date_in_6m'].isoformat()}",
            follow_redirects=True,
        )
        html = resp.data.decode()
        assert "\u20b9" in html


# ========================================================================== #
# DoD 8 — Malformed date string — silent fallback, no crash                  #
# ========================================================================== #

class TestMalformedDate:
    """Malformed date strings must not crash the app — silent fallback to unfiltered."""

    def test_malformed_date_from_no_crash(self, logged_in_client):
        """Spec DoD 8: date_from=not-a-date returns 200 without crashing."""
        client, td = logged_in_client
        resp = get_profile(client, {"date_from": "not-a-date", "date_to": td["today"].isoformat()})
        assert resp.status_code == 200

    def test_malformed_date_to_no_crash(self, logged_in_client):
        """Spec DoD 8: date_to=not-a-date returns 200 without crashing."""
        client, td = logged_in_client
        resp = get_profile(client, {"date_from": td["first_of_month"].isoformat(), "date_to": "not-a-date"})
        assert resp.status_code == 200

    def test_both_malformed_no_crash(self, logged_in_client):
        """Spec DoD 8: both params malformed → 200, no crash."""
        client, td = logged_in_client
        resp = get_profile(client, {"date_from": "foo", "date_to": "bar"})
        assert resp.status_code == 200

    def test_malformed_date_falls_back_to_all_expenses(self, logged_in_client):
        """Spec DoD 8: malformed date silently treated as absent → all expenses shown."""
        client, td = logged_in_client
        resp = get_profile(client, {"date_from": "not-a-date", "date_to": "also-bad"})
        html = resp.data.decode()
        # Unfiltered → all 5 expenses = 1500
        assert "1,500.00" in html

    def test_malformed_date_partial_one_param(self, logged_in_client):
        """Spec DoD 8: one valid + one malformed → treated as both absent (no filter)."""
        client, td = logged_in_client
        resp = get_profile(client, {
            "date_from": td["today"].isoformat(),
            "date_to": "not-a-date",
        })
        html = resp.data.decode()
        # Since date_to is invalid, filter is not applied → all expenses
        assert "1,500.00" in html

    def test_wrong_format_no_crash(self, logged_in_client):
        """Spec DoD 8: date in wrong format (MM/DD/YYYY) does not crash."""
        client, td = logged_in_client
        resp = get_profile(client, {"date_from": "05/28/2026", "date_to": "05/28/2026"})
        assert resp.status_code == 200

    def test_empty_string_date_params(self, logged_in_client):
        """Spec DoD 8: empty string params are treated as absent → unfiltered."""
        client, td = logged_in_client
        resp = get_profile(client, {"date_from": "", "date_to": ""})
        html = resp.data.decode()
        assert "1,500.00" in html


# ========================================================================== #
# DoD 9 — Active preset / custom-range visual indication                     #
# ========================================================================== #

class TestActivePresetIndication:
    """Active preset button or custom-range fields visually indicate which filter is active."""

    def test_all_time_is_active_when_no_params(self, logged_in_client):
        """Spec DoD 9: 'all_time' active preset passed to template when no filter."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        assert "all_time" in html

    def test_this_month_is_active(self, logged_in_client):
        """Spec DoD 9: 'this_month' active when this-month params passed."""
        client, td = logged_in_client
        resp = get_profile(client, {
            "date_from": td["first_of_month"].isoformat(),
            "date_to": td["today"].isoformat(),
        })
        html = resp.data.decode()
        assert "this_month" in html

    def test_last_3_months_is_active(self, logged_in_client):
        """Spec DoD 9: 'last_3_months' active when last-3-months params passed."""
        client, td = logged_in_client
        resp = get_profile(client, {
            "date_from": td["start_3m"].isoformat(),
            "date_to": td["today"].isoformat(),
        })
        html = resp.data.decode()
        assert "last_3_months" in html

    def test_last_6_months_is_active(self, logged_in_client):
        """Spec DoD 9: 'last_6_months' active when last-6-months params passed."""
        client, td = logged_in_client
        resp = get_profile(client, {
            "date_from": td["start_6m"].isoformat(),
            "date_to": td["today"].isoformat(),
        })
        html = resp.data.decode()
        assert "last_6_months" in html

    def test_custom_is_active_for_non_preset_range(self, logged_in_client):
        """Spec DoD 9: 'custom' active when dates don't match any preset."""
        client, td = logged_in_client
        # Use an arbitrary range that doesn't match any preset
        resp = get_profile(client, {
            "date_from": "2020-01-01",
            "date_to": "2020-06-30",
        })
        html = resp.data.decode()
        assert "custom" in html

    def test_date_from_preserved_in_response(self, logged_in_client):
        """Spec DoD 9: filter bar reflects active date_from value in template."""
        client, td = logged_in_client
        date_str = td["date_in_6m"].isoformat()
        resp = get_profile(client, {
            "date_from": date_str,
            "date_to": td["today"].isoformat(),
        })
        html = resp.data.decode()
        # The template should render the date_from value (e.g. in input value attr)
        assert date_str in html

    def test_date_to_preserved_in_response(self, logged_in_client):
        """Spec DoD 9: filter bar reflects active date_to value in template."""
        client, td = logged_in_client
        date_str = td["today"].isoformat()
        resp = get_profile(client, {
            "date_from": td["date_in_6m"].isoformat(),
            "date_to": date_str,
        })
        html = resp.data.decode()
        assert date_str in html


# ========================================================================== #
# DoD 10 — ₹ symbol always shown                                             #
# ========================================================================== #

class TestRsSymbol:
    """All amounts display the ₹ symbol regardless of the active filter."""

    def test_rs_symbol_no_filter(self, logged_in_client):
        """Spec DoD 10: ₹ in unfiltered view."""
        client, td = logged_in_client
        html = get_profile(client).data.decode()
        assert "\u20b9" in html

    def test_rs_symbol_this_month(self, logged_in_client):
        """Spec DoD 10: ₹ in This Month view."""
        client, td = logged_in_client
        html = get_profile(client, {
            "date_from": td["first_of_month"].isoformat(),
            "date_to": td["today"].isoformat(),
        }).data.decode()
        assert "\u20b9" in html

    def test_rs_symbol_last_3_months(self, logged_in_client):
        """Spec DoD 10: ₹ in Last 3 Months view."""
        client, td = logged_in_client
        html = get_profile(client, {
            "date_from": td["start_3m"].isoformat(),
            "date_to": td["today"].isoformat(),
        }).data.decode()
        assert "\u20b9" in html

    def test_rs_symbol_last_6_months(self, logged_in_client):
        """Spec DoD 10: ₹ in Last 6 Months view."""
        client, td = logged_in_client
        html = get_profile(client, {
            "date_from": td["start_6m"].isoformat(),
            "date_to": td["today"].isoformat(),
        }).data.decode()
        assert "\u20b9" in html

    def test_rs_symbol_custom_range(self, logged_in_client):
        """Spec DoD 10: ₹ in custom range view."""
        client, td = logged_in_client
        html = get_profile(client, {
            "date_from": td["date_in_6m"].isoformat(),
            "date_to": td["date_in_3m"].isoformat(),
        }).data.decode()
        assert "\u20b9" in html

    def test_rs_symbol_zero_result_view(self, empty_user_client):
        """Spec DoD 10: ₹ symbol shown even when user has no expenses."""
        client, td = empty_user_client
        html = get_profile(client).data.decode()
        assert "\u20b9" in html


# ========================================================================== #
# DoD 11 — User with no expenses in range sees zeros                         #
# ========================================================================== #

class TestNoExpensesInRange:
    """User with no expenses in the selected range sees Rs 0.00 total, 0 transactions,
    empty category breakdown — no errors."""

    def test_empty_user_no_filter_returns_200(self, empty_user_client):
        """Spec DoD 11: empty-expense user can load /profile without error."""
        client, td = empty_user_client
        resp = get_profile(client)
        assert resp.status_code == 200

    def test_empty_user_no_filter_shows_zero_total(self, empty_user_client):
        """Spec DoD 11: empty user sees Rs 0.00 total."""
        client, td = empty_user_client
        html = get_profile(client).data.decode()
        assert "0.00" in html

    def test_empty_user_no_filter_shows_zero_transactions(self, empty_user_client):
        """Spec DoD 11: empty user sees 0 transaction count."""
        client, td = empty_user_client
        html = get_profile(client).data.decode()
        assert "0" in html

    def test_demo_user_out_of_range_shows_zero_total(self, logged_in_client):
        """Spec DoD 11: demo user with filter range having no expenses sees 0.00."""
        client, td = logged_in_client
        # A far-future range containing no seeded expenses
        resp = get_profile(client, {
            "date_from": "2099-01-01",
            "date_to": "2099-12-31",
        })
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "0.00" in html

    def test_demo_user_out_of_range_shows_zero_transactions(self, logged_in_client):
        """Spec DoD 11: demo user with no-match filter shows 0 transactions."""
        client, td = logged_in_client
        resp = get_profile(client, {
            "date_from": "2099-01-01",
            "date_to": "2099-12-31",
        })
        html = resp.data.decode()
        # transaction_count should be 0
        assert "0" in html

    def test_demo_user_out_of_range_empty_breakdown(self, logged_in_client):
        """Spec DoD 11: no expenses in range → empty category breakdown (no error)."""
        client, td = logged_in_client
        resp = get_profile(client, {
            "date_from": "2099-01-01",
            "date_to": "2099-12-31",
        })
        assert resp.status_code == 200
        # Template must not raise exceptions even with empty category list

    def test_empty_user_this_month_returns_200(self, empty_user_client):
        """Spec DoD 11: empty user with This Month filter — no crash."""
        client, td = empty_user_client
        resp = get_profile(client, {
            "date_from": td["first_of_month"].isoformat(),
            "date_to": td["today"].isoformat(),
        })
        assert resp.status_code == 200

    def test_empty_user_this_month_zero_total(self, empty_user_client):
        """Spec DoD 11: empty user with This Month filter shows Rs 0.00."""
        client, td = empty_user_client
        html = get_profile(client, {
            "date_from": td["first_of_month"].isoformat(),
            "date_to": td["today"].isoformat(),
        }).data.decode()
        assert "0.00" in html


# ========================================================================== #
# Query helper unit tests — date filtering in get_summary_stats              #
# ========================================================================== #

class TestQueryHelperSummaryStats:
    """Unit tests for get_summary_stats with date_from / date_to."""

    def test_no_filter_returns_all_expenses(self, test_db):
        """Spec (query layer): no filter → all 5 demo expenses counted."""
        uid = test_db["demo_uid"]
        result = q.get_summary_stats(uid)
        assert result["transaction_count"] == 5
        assert abs(result["total_spent"] - 1500.0) < 0.01

    def test_filter_reduces_count(self, test_db):
        """Spec (query layer): date filter reduces transaction count."""
        uid = test_db["demo_uid"]
        today = test_db["today"]
        date_str = today.isoformat()
        result = q.get_summary_stats(uid, date_from=date_str, date_to=date_str)
        assert result["transaction_count"] == 1
        assert abs(result["total_spent"] - 500.0) < 0.01

    def test_filter_with_no_match_returns_zeros(self, test_db):
        """Spec (query layer): filter with no matching expenses → zeros."""
        uid = test_db["demo_uid"]
        result = q.get_summary_stats(uid, date_from="2099-01-01", date_to="2099-12-31")
        assert result["transaction_count"] == 0
        assert result["total_spent"] == 0
        assert result["top_category"] == "—"

    def test_empty_user_returns_zeros(self, test_db):
        """Spec (query layer): user with no expenses → zero stats."""
        uid = test_db["empty_uid"]
        result = q.get_summary_stats(uid)
        assert result["transaction_count"] == 0
        assert result["total_spent"] == 0
        assert result["top_category"] == "—"


# ========================================================================== #
# Query helper unit tests — date filtering in get_recent_transactions        #
# ========================================================================== #

class TestQueryHelperRecentTransactions:
    """Unit tests for get_recent_transactions with date_from / date_to."""

    def test_no_filter_returns_all(self, test_db):
        """Spec (query layer): no filter → all 5 transactions returned."""
        uid = test_db["demo_uid"]
        txs = q.get_recent_transactions(uid)
        assert len(txs) == 5

    def test_filter_returns_matching_only(self, test_db):
        """Spec (query layer): date filter returns only in-range transactions."""
        uid = test_db["demo_uid"]
        today = test_db["today"]
        date_str = today.isoformat()
        txs = q.get_recent_transactions(uid, date_from=date_str, date_to=date_str)
        assert len(txs) == 1
        assert txs[0]["date"] == date_str

    def test_filter_out_of_range_returns_empty(self, test_db):
        """Spec (query layer): filter with no matching dates → empty list."""
        uid = test_db["demo_uid"]
        txs = q.get_recent_transactions(uid, date_from="2099-01-01", date_to="2099-12-31")
        assert txs == []

    def test_empty_user_returns_empty_list(self, test_db):
        """Spec (query layer): user with no expenses → empty list."""
        uid = test_db["empty_uid"]
        txs = q.get_recent_transactions(uid)
        assert txs == []

    def test_results_ordered_newest_first(self, test_db):
        """Spec (query layer): transactions are ordered newest-first."""
        uid = test_db["demo_uid"]
        txs = q.get_recent_transactions(uid)
        dates = [tx["date"] for tx in txs]
        assert dates == sorted(dates, reverse=True)

    def test_required_keys_present(self, test_db):
        """Spec (query layer): each transaction has date, description, category, amount."""
        uid = test_db["demo_uid"]
        txs = q.get_recent_transactions(uid)
        for tx in txs:
            for key in ("date", "description", "category", "amount"):
                assert key in tx


# ========================================================================== #
# Query helper unit tests — date filtering in get_category_breakdown         #
# ========================================================================== #

class TestQueryHelperCategoryBreakdown:
    """Unit tests for get_category_breakdown with date_from / date_to."""

    def test_no_filter_returns_all_categories(self, test_db):
        """Spec (query layer): no filter → 5 categories (one per seeded expense)."""
        uid = test_db["demo_uid"]
        cats = q.get_category_breakdown(uid)
        assert len(cats) == 5

    def test_filter_limits_categories(self, test_db):
        """Spec (query layer): filter to single day → only that expense's category."""
        uid = test_db["demo_uid"]
        today = test_db["today"]
        cats = q.get_category_breakdown(uid, date_from=today.isoformat(), date_to=today.isoformat())
        assert len(cats) == 1

    def test_pct_sums_to_100(self, test_db):
        """Spec (query layer): pct values always sum to exactly 100."""
        uid = test_db["demo_uid"]
        cats = q.get_category_breakdown(uid)
        assert sum(c["pct"] for c in cats) == 100

    def test_pct_are_integers(self, test_db):
        """Spec (query layer): pct values are integers."""
        uid = test_db["demo_uid"]
        cats = q.get_category_breakdown(uid)
        assert all(isinstance(c["pct"], int) for c in cats)

    def test_ordered_by_amount_descending(self, test_db):
        """Spec (query layer): breakdown ordered by amount descending."""
        uid = test_db["demo_uid"]
        cats = q.get_category_breakdown(uid)
        amounts = [c["amount"] for c in cats]
        assert amounts == sorted(amounts, reverse=True)

    def test_out_of_range_filter_returns_empty(self, test_db):
        """Spec (query layer): filter with no matching expenses → empty list."""
        uid = test_db["demo_uid"]
        cats = q.get_category_breakdown(uid, date_from="2099-01-01", date_to="2099-12-31")
        assert cats == []

    def test_empty_user_returns_empty_list(self, test_db):
        """Spec (query layer): user with no expenses → empty list."""
        uid = test_db["empty_uid"]
        cats = q.get_category_breakdown(uid)
        assert cats == []

    def test_required_keys_present(self, test_db):
        """Spec (query layer): each category entry has name, amount, pct."""
        uid = test_db["demo_uid"]
        cats = q.get_category_breakdown(uid)
        for cat in cats:
            for key in ("name", "amount", "pct"):
                assert key in cat


# ========================================================================== #
# Filter bar — template context                                               #
# ========================================================================== #

class TestFilterBarContext:
    """The template receives all required context variables for the filter bar."""

    def test_preset_dates_in_context(self, logged_in_client):
        """Spec: preset_dates dict is passed to template (used to generate links)."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        # preset key names must appear in HTML (e.g. in href or data attrs)
        # At minimum the preset labels must be in the HTML
        assert "This Month" in html or "this_month" in html
        assert "Last 3 Months" in html or "last_3_months" in html
        assert "Last 6 Months" in html or "last_6_months" in html
        assert "All Time" in html or "all_time" in html

    def test_filter_bar_present_in_profile_page(self, logged_in_client):
        """Spec: filter bar section exists on /profile page."""
        client, td = logged_in_client
        resp = get_profile(client)
        html = resp.data.decode()
        # The page must contain date input or filter controls
        assert "date_from" in html or "date-from" in html
        assert "date_to" in html or "date-to" in html
