# Spec: Registration

## Overview
Implement user registration functionality that creates new user accounts with securely hashed passwords and establishes session-based authentication. This step adds the core authentication mechanism that subsequent features (login, profile, expense tracking) depend on.On success the user is shownwith a success message and then redirected to the login page. This is the entry pointfor all autmenticated features that follow.

## Depends on
- Step 01 (database-setup) — users table and database functions must be implemented

## Routes
- `GET /register` — show registration form (already exists)
- `POST /register` — process registration, create user, log in — public

## Database changes
No new tables or columns. The `users` table from Step 01 is used.

## Templates
- **Modify:** `templates/register.html` — add `form-error` block for validation messages (template already exists with form)

## Files to change
- `app.py` — add POST /register route, session configuration, login required decorator
- `templates/register.html` — add `{% block form_error %}` for error display

## Files to create
- None

## New dependencies
No new pip packages. Use:
- `flask` (already installed)
- `werkzeug.security` (already installed)

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterized queries only
- Passwords hashed with `werkzeug.security.generate_password_hash`
- Use Flask sessions for authentication
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Validate: name (required, min 2 chars), email (required, valid format, unique), password (required, min 8 chars)

## Definition of done
- [ ] POST /register creates new user with hashed password
- [ ] Duplicate email shows error "Email already registered"
- [ ] Invalid input shows appropriate error messages
- [ ] Successful registration logs user in and redirects to /profile
- [ ] User appears in database with hashed password (not plain text)
- [ ] Already logged-in user accessing /register redirects to /profile