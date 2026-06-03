# Spec: Add Expense

## Overview
This feature allows logged-in users to record new expenses. It provides a form to input the amount, category, date, and an optional description. This is a core functionality of the Spendly app, enabling users to build their transaction history for analytics.

## Depends on
Previous steps covering user authentication and database setup.

## Routes
- `GET /expenses/add` — Displays the "Add Expense" form. (Logged-in)
- `POST /expenses/add` — Validates and saves the new expense to the database. (Logged-in)

## Database changes
No database changes. Uses the existing `expenses` table:
```
expenses(id, user_id, amount, category, date, description, created_at)
```

## Templates
- **Create:** `templates/add_expense.html`
- **Modify:** `templates/profile.html` (adds an "Add Expense" action button in the Recent Transactions card header)

## Files to change
- `app.py`
- `templates/profile.html`
- `static/css/profile.css`

## Files to create
- `templates/add_expense.html`
- `static/css/add_expense.css`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use the `CATEGORY_META` map in `app.py` to populate the category dropdown in the form.
- Validate that `amount` is a positive number and `date` is a valid ISO format.
- `description` is optional; cap at 200 characters.
- On validation error, re-render the form with the entered values preserved and an inline error message.
- On success, flash a "Expense added successfully!" message and redirect to `/profile`.
- Unauthenticated requests are redirected to `/login` via the `@login_required` decorator.

## Implementation notes
- The route resolves `user_id` from `session["user_id"]` (email) via a DB lookup, matching the pattern used in `/profile`.
- The `add_expense` route accepts `GET` and `POST` methods and is decorated with `@login_required`.
- The `form` dict is always passed to the template so fields are pre-populated on validation errors.
- The "Add Expense" link on `profile.html` is placed as a `.card-header-action` button inside the Recent Transactions card header.

## Definition of done
- [x] Navigating to `/expenses/add` while logged in shows the expense form.
- [x] Submitting the form with valid data successfully inserts a record into the `expenses` table.
- [x] After a successful submission, the user is redirected to the profile page.
- [x] Submitting the form with invalid data (e.g., negative amount, empty category) displays a validation error on the page.
- [x] The "Add Expense" form includes a dropdown with categories defined in `CATEGORY_META`.
- [x] Unauthenticated users attempting to access `/expenses/add` are redirected to the login page.
