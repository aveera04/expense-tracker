# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Spendly is a Flask-based expense tracking application. It is structured as a multi-step tutorial project where students implement features progressively.

## Development Commands

```bash
# Run the app (port 5001, debug mode)
python app.py

# Run tests
pytest

# Run a single test file
pytest tests/test_file.py

# Install dependencies
pip install -r requirements.txt
```

## Architecture

- **`app.py`** — Flask application with route definitions. Placeholder routes for future steps are clearly marked with comments.
- **`database/db.py`** — Database layer. Currently a placeholder; students implement `get_db()`, `init_db()`, and `seed_db()`.
- **`templates/`** — Jinja2 HTML templates extending `base.html`. Key templates: `landing.html`, `login.html`, `register.html`, `terms.html`, `privacy.html`.
- **`static/css/style.css`** — Design system using CSS custom properties (`--ink`, `--paper`, `--accent`, etc.). Fonts: DM Serif Display (headings) and DM Sans (body).
- **`static/js/main.js`** — Client-side JavaScript (currently empty placeholder).

## Key Patterns

- Routes follow Flask conventions in `app.py`
- Templates extend `base.html` and override `title`, `head`, `content`, and `scripts` blocks
- Database connections use SQLite with `row_factory` and foreign keys enabled (to be implemented in `db.py`)
- Forms post to routes and use `form-error` blocks for validation feedback
