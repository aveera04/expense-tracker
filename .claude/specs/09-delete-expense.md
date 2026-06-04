# Spec: Delete Expense

## Overview
This feature lets logged-in users delete any of their existing expenses. It introduces a "Delete" affordance on each row of the Recent Transactions list on the profile page, which posts to `/expenses/<id>/delete` for the matching row. Successful deletion removes the row from the `expenses` table and flashes a success message before redirecting back to the profile page. This step completes the CRUD lifecycle for expenses (Add → Edit → Delete) and relies on the same ownership-by-`user_id` pattern used by the existing Edit Expense flow.

## Depends on
- Step 01 — Database setup (`expenses` table)
- Step 02 — Registration (user identity)
- Step 03 — Login and Logout (session + `@login_required`)
- Step 05 — Backend routes for profile page (query helpers)
- Step 07 — Add Expense (shared form patterns, CSRF, `CATEGORY_META`)
- Step 08 — Edit Expense (owner-only read pattern via `get_expense_by_id`, profile row layout)

## Routes
- `POST /expenses/<int:id>/delete` — Validate CSRF, verify ownership, and delete the matching `expenses` row. (Logged-in, owner-only)

`GET /expenses/<int:id>/delete` is intentionally **not** a route. The endpoint only accepts POST so destructive actions can never be triggered by a stray link, prefetch, or browser address-bar entry. A direct GET to this URL must return `405 Method Not Allowed`.

If a user submits a `POST` for an `id` that does not exist, or one that belongs to a different user, the route returns `404` (abort with 404). It must not leak whether the row exists for another user.

## Database changes
No database changes. The existing `expenses` table is deleted from:
```
expenses(id, user_id, amount, category, date, description, created_at)
```

## Templates
- **Create:** none
- **Modify:** `templates/profile.html` — adds a Delete control per row in the Recent Transactions table. The control is a small button rendered inside a `<form method="POST" action="{{ url_for('delete_expense', id=tx.id) }}">`, carrying a hidden CSRF input. It must be styled to sit alongside the existing Edit control without breaking the row layout.

## Files to change
- `app.py` — Replace the placeholder `/expenses/<int:id>/delete` route with a real `POST`-only handler that validates CSRF, loads the row through `get_expense_by_id` (so the ownership check is enforced in one place), deletes it, and flashes a success message.
- `database/queries.py` — Add a `delete_expense(expense_id, user_id)` helper that runs a parameterised `DELETE FROM expenses WHERE id = ? AND user_id = ?`, commits, and returns the affected row count (0 if the row was missing or owned by a different user, 1 on success).
- `templates/profile.html` — Add a Delete form per Recent Transactions row next to the existing Edit control.

## Files to create
- `static/css/delete_expense.css` — Styles for the Delete button on Recent Transactions rows, matching the existing Edit button language. Reuses the same design tokens (`--ink`, `--paper`, `--accent`, etc.) and stays consistent with `static/css/edit_expense.css`.
- `tests/test_delete_expense.py` — Pytest cases covering: owner can delete, owner deleting a non-existent id gets 404, non-owner gets 404, unauthenticated is redirected to login, GET to delete URL returns 405, missing/invalid CSRF is rejected.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- The delete endpoint must accept only `POST` (no `GET`). Implement it as `methods=["POST"]` on the route, or branch on `request.method` and abort(405) for everything else.
- Ownership check: ownership is verified via `get_expense_by_id(id, db_user_id)` before the delete runs. The `delete_expense` helper also includes `WHERE id = ? AND user_id = ?` as a second line of defence.
- If the row is missing or owned by another user, abort with `404` (do not redirect, do not flash a distinguishing error).
- CSRF token must be validated on POST using the same pattern as Add/Edit: when `app.config.get("TESTING")` is false, compare `session["_csrf_token"]` to `request.form.get("_csrf_token")`. On mismatch, abort with `400` (or re-render the profile with an error flash) — never silently succeed.
- On success, flash `"Expense deleted successfully!"` and redirect to `/profile`.
- Unauthenticated requests are redirected to `/login` via `@login_required`.
- The transactions query already returns `id` (from Step 08), so each row in the profile template can build a Delete form action with `url_for('delete_expense', id=tx.id)`.
- The Delete control must include a confirmation prompt (e.g., `onsubmit="return confirm('Delete this expense? This cannot be undone.');"`) to prevent accidental clicks. Progressive enhancement only — the server-side ownership check is the real safeguard.
- Do not implement soft-delete. This step hard-deletes the row.

## Implementation notes
- The route is decorated with `@login_required` and `methods=["POST"]` (so Flask returns 405 for any other method automatically).
- A small helper query `delete_expense(expense_id, user_id)` in `database/queries.py` keeps the SQL parameterised and the ownership check inside the SQL. The route should call it and treat a 0 rowcount the same as a missing row (abort 404).
- The Delete button on each row should be a small icon button (e.g., a trash icon) wrapped in its own form. Keep its visual weight similar to the Edit button so neither dominates the row.
- The flash message category should be `"success"` to match Add/Edit.

## Definition of done
- [ ] Each row in the Recent Transactions card on `profile.html` shows a Delete control (form-based, POST) next to the Edit control.
- [ ] Submitting the Delete form with a valid CSRF token removes the matching row from the `expenses` table.
- [ ] After a successful delete, the user is redirected to `/profile`, the row no longer appears in Recent Transactions, and any affected stats (total spent, transaction count, category breakdown) reflect the removal.
- [ ] A success flash `"Expense deleted successfully!"` is shown on the profile page after the redirect.
- [ ] The Delete form includes a JS confirmation prompt (`confirm(...)`) before submitting.
- [ ] CSRF token is present in the Delete form and validated on POST (matching the Add/Edit pattern).
- [ ] Unauthenticated users submitting the Delete form are redirected to the login page.
- [ ] A logged-in user deleting an `id` that does not exist or belongs to another user receives a `404`.
- [ ] `GET /expenses/<id>/delete` returns `405 Method Not Allowed` (the route is POST-only).
- [ ] `pytest tests/test_delete_expense.py` covers: owner can delete, deleted row is gone from DB, deleting a non-existent id is 404, non-owner is 404, unauthenticated is redirected to login, GET is 405, missing/invalid CSRF is rejected.
