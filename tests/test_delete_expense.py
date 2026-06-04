"""
tests/test_delete_expense.py — Tests for Spec 09: Delete Expense

Strategy
--------
* Shared fixtures (``test_db``, ``client``, ``logged_in_client``) are provided
  by ``tests/conftest.py`` — no duplication with other test modules.
* ``seed_other_user_with_expense`` is imported from conftest as a plain helper.
* CSRF tests use ``monkeypatch`` to toggle TESTING=False safely; no manual
  try/finally needed.
* All tests are fully independent; no test relies on execution order.
* Every test maps to at least one Definition-of-Done item from the spec.

DoD coverage
------------
DoD 1  — Each row in Recent Transactions shows a Delete control (form-based, POST).
DoD 2  — Submitting the Delete form with a valid CSRF token removes the row.
DoD 3  — After a successful delete, the user is redirected to /profile; row is gone.
DoD 4  — A success flash "Expense deleted successfully!" is shown on profile.
DoD 5  — The Delete form triggers a JS confirm dialog (via event delegation).
DoD 6  — CSRF token is present in the Delete form and validated on POST.
DoD 7  — Unauthenticated users submitting the Delete form are redirected to login.
DoD 8  — A logged-in user deleting an id that does not exist or belongs to another gets 404.
DoD 9  — GET /expenses/<id>/delete returns 405 Method Not Allowed.
DoD 10 — pytest covers: owner can delete, deleted row is gone from DB, non-existent id is 404,
          non-owner is 404, unauthenticated is redirected, GET is 405, invalid CSRF rejected.
"""

import pytest

import app as flask_app
import database.queries as queries_module
from tests.conftest import seed_other_user_with_expense


# ============================================================================ #
# Helper                                                                        #
# ============================================================================ #

def _expense_exists(test_db, expense_id):
    """Return True if the expense row still exists in the test DB."""
    conn = test_db["make_conn"]()
    row = conn.execute(
        "SELECT id FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()
    conn.close()
    return row is not None


# ============================================================================ #
# DoD 1 — Profile page renders a Delete control per row                         #
# ============================================================================ #

class TestDeleteControlInProfile:
    """DoD 1 and DoD 5: Delete form and JS confirm appear in the profile table."""

    def test_delete_form_present_for_owner_expense(self, logged_in_client):
        """Each transaction row must contain a form posting to the delete URL."""
        client, test_db = logged_in_client
        expense_id = test_db["expense_id"]

        resp = client.get("/profile")
        assert resp.status_code == 200

        html = resp.data.decode()
        expected_action = f"/expenses/{expense_id}/delete"
        assert expected_action in html, (
            f"Expected delete action URL '{expected_action}' in profile HTML"
        )
        assert 'method="POST"' in html or "method=POST" in html.lower(), (
            "Delete form must use POST method"
        )

    def test_delete_form_has_csrf_input(self, logged_in_client):
        """DoD 6: The Delete form must contain a hidden _csrf_token input."""
        client, test_db = logged_in_client
        resp = client.get("/profile")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'name="_csrf_token"' in html, (
            "Delete form must include a hidden _csrf_token input"
        )

    def test_delete_form_event_delegation_script_present(self, logged_in_client):
        """DoD 5: Profile page must contain the event-delegated delete confirm script."""
        client, test_db = logged_in_client
        resp = client.get("/profile")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "tx-delete-form" in html, (
            "Event-delegation script must reference the tx-delete-form class"
        )
        assert "confirm(" in html, (
            "Delete confirmation must use confirm() in the script block"
        )


# ============================================================================ #
# DoD 2 & 3 — Owner can delete; row removed; redirect to profile                #
# ============================================================================ #

class TestOwnerCanDelete:
    """DoD 2, 3: Owner deleting their own expense removes the row and redirects."""

    def test_owner_delete_returns_redirect(self, logged_in_client):
        client, test_db = logged_in_client
        expense_id = test_db["expense_id"]

        resp = client.post(
            f"/expenses/{expense_id}/delete",
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302, (
            f"Expected 302 redirect, got {resp.status_code}"
        )
        assert "/profile" in resp.headers.get("Location", ""), (
            "Redirect location should be /profile"
        )

    def test_owner_delete_removes_row_from_db(self, logged_in_client):
        """DoD 2: The deleted row is gone from the expenses table."""
        client, test_db = logged_in_client
        expense_id = test_db["expense_id"]

        assert _expense_exists(test_db, expense_id), (
            "Expense should exist before deletion"
        )

        client.post(f"/expenses/{expense_id}/delete", data={})

        assert not _expense_exists(test_db, expense_id), (
            "Expense should no longer exist in the DB after deletion"
        )

    def test_owner_delete_row_absent_from_profile(self, logged_in_client):
        """DoD 3: After deletion the row no longer appears in Recent Transactions."""
        client, test_db = logged_in_client
        expense_id = test_db["expense_id"]

        client.post(f"/expenses/{expense_id}/delete", data={}, follow_redirects=True)

        resp = client.get("/profile")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert f"/expenses/{expense_id}/delete" not in html, (
            "Deleted expense's delete form should no longer appear in the profile"
        )


# ============================================================================ #
# DoD 4 — Success flash message                                                 #
# ============================================================================ #

class TestSuccessFlash:
    """DoD 4: A success flash 'Expense deleted successfully!' is shown after delete."""

    def test_success_flash_shown_on_profile_after_delete(self, logged_in_client):
        client, test_db = logged_in_client
        expense_id = test_db["expense_id"]

        resp = client.post(
            f"/expenses/{expense_id}/delete",
            data={},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Expense deleted successfully!" in html, (
            "Success flash message should appear on profile after delete"
        )


# ============================================================================ #
# DoD 7 — Unauthenticated users are redirected to login                         #
# ============================================================================ #

class TestUnauthenticatedRedirect:
    """DoD 7: Unauthenticated DELETE requests redirect to /login."""

    def test_unauthenticated_post_redirects_to_login(self, client, test_db):
        expense_id = test_db["expense_id"]
        resp = client.post(
            f"/expenses/{expense_id}/delete",
            data={},
            follow_redirects=False,
        )
        assert resp.status_code == 302, (
            f"Expected 302 redirect for unauthenticated user, got {resp.status_code}"
        )
        location = resp.headers.get("Location", "")
        assert "/login" in location, (
            f"Unauthenticated user should be redirected to /login, got '{location}'"
        )


# ============================================================================ #
# DoD 8 — Non-existent id and non-owner id both return 404                      #
# ============================================================================ #

class TestOwnershipAndNotFound:
    """DoD 8: Missing or wrong-owner expense returns 404."""

    def test_nonexistent_id_returns_404(self, logged_in_client):
        client, test_db = logged_in_client
        resp = client.post("/expenses/999999/delete", data={})
        assert resp.status_code == 404, (
            f"Non-existent expense id should return 404, got {resp.status_code}"
        )

    def test_non_owner_id_returns_404(self, logged_in_client):
        """A logged-in user cannot delete another user's expense."""
        client, test_db = logged_in_client
        _, other_expense_id = seed_other_user_with_expense(test_db)

        resp = client.post(f"/expenses/{other_expense_id}/delete", data={})
        assert resp.status_code == 404, (
            f"Non-owner should receive 404, got {resp.status_code}"
        )

    def test_non_owner_expense_still_exists_in_db(self, logged_in_client):
        """The other user's expense must NOT be deleted on a 404 attempt."""
        client, test_db = logged_in_client
        _, other_expense_id = seed_other_user_with_expense(test_db)

        client.post(f"/expenses/{other_expense_id}/delete", data={})

        assert _expense_exists(test_db, other_expense_id), (
            "Other user's expense must remain in the DB after a failed delete attempt"
        )


# ============================================================================ #
# DoD 9 — GET /expenses/<id>/delete returns 405                                 #
# ============================================================================ #

class TestGetNotAllowed:
    """DoD 9: GET to the delete URL must return 405 Method Not Allowed."""

    def test_get_delete_url_returns_405(self, logged_in_client):
        client, test_db = logged_in_client
        expense_id = test_db["expense_id"]
        resp = client.get(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 405, (
            f"GET to /expenses/<id>/delete should return 405, got {resp.status_code}"
        )

    def test_get_delete_url_unauthenticated_returns_405(self, client, test_db):
        """Even unauthenticated GETs should get 405 — route is POST-only."""
        expense_id = test_db["expense_id"]
        resp = client.get(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 405, (
            f"Unauthenticated GET to /expenses/<id>/delete should return 405, got {resp.status_code}"
        )


# ============================================================================ #
# DoD 6 — CSRF validation                                                       #
# ============================================================================ #

class TestCsrfValidation:
    """DoD 6: Missing or invalid CSRF token is rejected (when TESTING=False)."""

    def test_missing_csrf_token_rejected(self, test_db, monkeypatch):
        """POST without a CSRF token should be rejected with 400."""
        monkeypatch.setitem(flask_app.app.config, "TESTING", False)
        import database.db as db_module
        monkeypatch.setattr(db_module, "get_db", test_db["make_conn"])
        monkeypatch.setattr(flask_app, "get_db", test_db["make_conn"])

        with flask_app.app.test_client() as c:
            c.post(
                "/login",
                data={"email": test_db["email"], "password": test_db["password"]},
            )
            resp = c.post(
                f"/expenses/{test_db['expense_id']}/delete",
                data={},  # deliberately no _csrf_token
            )
        assert resp.status_code == 400, (
            f"Missing CSRF token should return 400, got {resp.status_code}"
        )

    def test_invalid_csrf_token_rejected(self, test_db, monkeypatch):
        """POST with a wrong CSRF token should be rejected with 400."""
        monkeypatch.setitem(flask_app.app.config, "TESTING", False)
        import database.db as db_module
        monkeypatch.setattr(db_module, "get_db", test_db["make_conn"])
        monkeypatch.setattr(flask_app, "get_db", test_db["make_conn"])

        with flask_app.app.test_client() as c:
            c.post(
                "/login",
                data={"email": test_db["email"], "password": test_db["password"]},
            )
            resp = c.post(
                f"/expenses/{test_db['expense_id']}/delete",
                data={"_csrf_token": "totally-wrong-token"},
            )
        assert resp.status_code == 400, (
            f"Invalid CSRF token should return 400, got {resp.status_code}"
        )


# ============================================================================ #
# database/queries.py — delete_expense_row unit tests                           #
# ============================================================================ #

class TestDeleteExpenseRow:
    """Direct unit tests for the delete_expense_row query helper."""

    def test_returns_1_on_success(self, test_db, monkeypatch):
        import database.db as db_module
        monkeypatch.setattr(db_module, "get_db", test_db["make_conn"])

        result = queries_module.delete_expense_row(
            test_db["expense_id"], test_db["user_id"]
        )
        assert result == 1, f"Expected rowcount 1, got {result}"

    def test_returns_0_for_wrong_user(self, test_db, monkeypatch):
        import database.db as db_module
        monkeypatch.setattr(db_module, "get_db", test_db["make_conn"])

        result = queries_module.delete_expense_row(
            test_db["expense_id"], test_db["user_id"] + 9999
        )
        assert result == 0, f"Expected rowcount 0 for wrong user, got {result}"

    def test_returns_0_for_nonexistent_id(self, test_db, monkeypatch):
        import database.db as db_module
        monkeypatch.setattr(db_module, "get_db", test_db["make_conn"])

        result = queries_module.delete_expense_row(999999, test_db["user_id"])
        assert result == 0, f"Expected rowcount 0 for nonexistent id, got {result}"

    def test_actually_removes_row(self, test_db, monkeypatch):
        import database.db as db_module
        monkeypatch.setattr(db_module, "get_db", test_db["make_conn"])

        queries_module.delete_expense_row(test_db["expense_id"], test_db["user_id"])
        assert not _expense_exists(test_db, test_db["expense_id"]), (
            "delete_expense_row must remove the row from the DB"
        )

    def test_does_not_remove_other_users_row(self, test_db, monkeypatch):
        import database.db as db_module
        monkeypatch.setattr(db_module, "get_db", test_db["make_conn"])

        _, other_expense_id = seed_other_user_with_expense(test_db)
        queries_module.delete_expense_row(other_expense_id, test_db["user_id"])
        assert _expense_exists(test_db, other_expense_id), (
            "delete_expense_row must not remove rows owned by a different user"
        )
