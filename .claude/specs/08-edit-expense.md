# Spec: Edit Expense

## Overview
This feature lets logged-in users edit any of their existing expenses in place. It introduces an "Edit" affordance on each row of the Recent Transactions list on the profile page, which navigates to a pre-filled `/expenses/<id>/edit` form. Submitting a valid form updates the row in the `expenses` table; validation errors are re-rendered inline. This step is a prerequisite for the upcoming delete flow and keeps the app's data writable end-to-end now that adding expenses is in place.

## Depends on
- Step 01 — Database setup (`expenses` table)
- Step 02 — Registration (user identity)
- Step 03 — Login and Logout (session + `@login_required`)
- Step 05 — Backend routes for profile page (query helpers)
- Step 07 — Add Expense (shared form patterns, CSRF, `CATEGORY_META`)

## Routes
- `GET /expenses/<int:id>/edit` — Render the edit form pre-filled with the existing expense's data. (Logged-in, owner-only)
- `POST /expenses/<int:id>/edit` — Validate the submitted form and update the matching `expenses` row. (Logged-in, owner-only)

If a user requests an `id` that does not exist, or one that belongs to a different user, the route returns `404` (abort with 404). It must not leak whether the row exists for another user.

## Database changes
No database changes. The existing `expenses` table is updated in place:
```
expenses(id, user_id, amount, category, date, description, created_at)
```
All edits write to `amount`, `category`, `date`, and `description` only. `user_id` and `created_at` are never overwritten by this flow.

## Templates
- **Create:** `templates/edit_expense.html`
- **Modify:** `templates/profile.html` — adds an Edit link/button per row in the Recent Transactions table, linking to `url_for('edit_expense', id=tx.id)`.

## Files to change
- `app.py` — Replace the placeholder `/expenses/<int:id>/edit` route with a real `GET`/`POST` handler that loads the existing row, validates, and updates it.
- `templates/profile.html` — Wire up the new Edit control on each Recent Transactions row (the query layer for transactions must be extended to return `id`).

## Files to create
- `templates/edit_expense.html`
- `static/css/edit_expense.css`
- `tests/test_edit_expense.py`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Reuse the same `CATEGORY_META` map, validation rules, CSRF handling, and inline error block used in the Add Expense flow. Keep the visual language of the form consistent with `add_expense.html`.
- Ownership check: every read and update must include `WHERE id = ? AND user_id = ?`. Never trust a URL id alone.
- If the row is missing or owned by another user, abort with `404` (do not redirect, do not flash a distinguishing error).
- On validation error, re-render the form with the entered values preserved and an inline error message (same `.expense-error` block as Add).
- On success, flash `"Expense updated successfully!"` and redirect to `/profile`.
- Unauthenticated requests are redirected to `/login` via `@login_required`.
- The transactions query must surface the `id` so each row in the profile template can build an Edit link.

## Implementation notes
- The route accepts `GET` and `POST` and is decorated with `@login_required`.
- A small helper query (e.g. `get_expense_by_id(expense_id, user_id)` in `database/queries.py`) is the cleanest way to load the row with the ownership check in one place. This keeps the SQL parameterised and reusable.
- The edit form should mirror `add_expense.html` structure, swapping the title to "Edit Expense", the submit button label to "Save Changes", and using a pencil-style icon in place of the plus icon. The action URL should be `url_for('edit_expense', id=expense.id)`.
- The Recent Transactions row in `profile.html` should expose an Edit control (a small button or icon link) that is visible on hover/focus and at all times on touch devices. It must not break the existing card layout.
- When the row fails to load (404), no flash message is needed; Flask's default 404 page is acceptable.

## Definition of done
- [ ] Navigating to `/expenses/<id>/edit` for a row owned by the current user shows a pre-filled edit form.
- [ ] Submitting the form with valid data updates the matching row in the `expenses` table.
- [ ] After a successful update, the user is redirected to the profile page and the new values are reflected in the Recent Transactions list and any affected stats.
- [ ] Submitting the form with invalid data (e.g., negative amount, empty category, malformed date, description > 200 chars) re-renders the form with an inline error and the user's entered values preserved.
- [ ] The category dropdown is populated from `CATEGORY_META` and the saved value is selected on load.
- [ ] CSRF token is present in the form and validated on POST (matching the Add Expense pattern).
- [ ] Unauthenticated users requesting `/expenses/<id>/edit` are redirected to the login page.
- [ ] A logged-in user requesting an `id` that does not exist or belongs to another user receives a `404` (not a 403, not a 200 with a friendly page).
- [ ] Each row in the Recent Transactions card on `profile.html` has an Edit control that links to the correct `edit_expense` URL.
- [ ] `pytest tests/test_edit_expense.py` covers: owner can GET, owner can POST a valid update, owner cannot POST an invalid update, non-owner gets 404, unauthenticated is redirected to login, missing id gets 404.
