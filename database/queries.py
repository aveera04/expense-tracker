"""
database/queries.py — Pure SQLite query helpers for the profile page.
No Flask imports. Each function opens and closes its own connection.
"""

import calendar

import database.db as _db_module


def _get_db():
    """Indirection layer so tests can monkeypatch database.db.get_db."""
    return _db_module.get_db()


def get_user_by_id(user_id):
    """
    Return a dict with 'name', 'email', 'member_since' for the given user_id.
    'member_since' is formatted as "Month YYYY" (e.g. "January 2026").
    Returns None if the user does not exist.
    """
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None

        # Parse created_at ("YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD")
        created_at = row["created_at"] or ""
        date_part = created_at.split(" ")[0]  # "YYYY-MM-DD"
        try:
            parts = date_part.split("-")
            year = int(parts[0])
            month = int(parts[1])
            member_since = f"{calendar.month_name[month]} {year}"
        except (IndexError, ValueError):
            member_since = ""

        return {
            "name": row["name"],
            "email": row["email"],
            "member_since": member_since,
        }
    finally:
        conn.close()


def get_summary_stats(user_id):
    """
    Return a dict with 'total_spent', 'transaction_count', 'top_category'
    for the given user_id.
    Returns zeros and "—" if the user has no expenses.
    """
    conn = _get_db()
    try:
        # Total spent and transaction count
        agg = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS transaction_count "
            "FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        total_spent = agg["total_spent"]
        transaction_count = agg["transaction_count"]

        # Top category by total amount spent
        top_row = conn.execute(
            "SELECT category FROM expenses WHERE user_id = ? "
            "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            (user_id,),
        ).fetchone()

        top_category = top_row["category"] if top_row else "—"

        return {
            "total_spent": total_spent,
            "transaction_count": transaction_count,
            "top_category": top_category,
        }
    finally:
        conn.close()


def get_recent_transactions(user_id, limit=10):
    """
    Return a list of dicts (newest-first), each with:
    'date', 'description', 'category', 'amount'.
    Returns an empty list if the user has no expenses.
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT date, description, category, amount "
            "FROM expenses WHERE user_id = ? "
            "ORDER BY date DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()

        return [
            {
                "date": row["date"],
                "description": row["description"] or "",
                "category": row["category"],
                "amount": row["amount"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_category_breakdown(user_id):
    """
    Return a list of dicts (ordered by amount desc), each with:
    'name', 'amount', 'pct'.
    'pct' values are integers that sum to exactly 100.
    Returns an empty list if the user has no expenses.
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT category AS name, SUM(amount) AS amount "
            "FROM expenses WHERE user_id = ? "
            "GROUP BY category ORDER BY amount DESC",
            (user_id,),
        ).fetchall()

        if not rows:
            return []

        total = sum(row["amount"] for row in rows)
        if total == 0:
            return []

        # Compute raw percentages and floor them
        items = []
        for row in rows:
            raw = row["amount"] / total * 100
            items.append({
                "name": row["name"],
                "amount": row["amount"],
                "pct": int(raw),          # floor
                "_raw": raw,
            })

        # Adjust so pct values sum to exactly 100
        remainder = 100 - sum(item["pct"] for item in items)
        # Sort by fractional part descending to distribute remainder
        items.sort(key=lambda x: x["_raw"] - x["pct"], reverse=True)
        for i in range(remainder):
            items[i]["pct"] += 1

        # Re-sort by amount descending
        items.sort(key=lambda x: x["amount"], reverse=True)

        # Strip the internal helper key
        for item in items:
            del item["_raw"]

        return items
    finally:
        conn.close()
