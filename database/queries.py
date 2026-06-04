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


def _build_date_filter(date_from=None, date_to=None):
    """Build a date filter clause and param list for SQLite."""
    date_filter = ""
    params = []
    if date_from and date_to:
        date_filter = " AND date BETWEEN ? AND ?"
        params.extend([date_from, date_to])
    elif date_from:
        date_filter = " AND date >= ?"
        params.append(date_from)
    elif date_to:
        date_filter = " AND date <= ?"
        params.append(date_to)
    return date_filter, params


def get_summary_stats(user_id, date_from=None, date_to=None):
    """
    Return a dict with 'total_spent', 'transaction_count', 'top_category'
    for the given user_id.
    When date_from and/or date_to are provided, expenses are filtered accordingly.
    Returns zeros and "—" if the user has no expenses.
    """
    conn = _get_db()
    try:
        date_filter, date_params = _build_date_filter(date_from, date_to)
        params_base = [user_id] + date_params

        # Total spent and transaction count
        agg = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS transaction_count "
            "FROM expenses WHERE user_id = ?" + date_filter,
            params_base,
        ).fetchone()

        total_spent = agg["total_spent"]
        transaction_count = agg["transaction_count"]

        # Top category by total amount spent
        top_row = conn.execute(
            "SELECT category FROM expenses WHERE user_id = ?" + date_filter +
            " GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            params_base,
        ).fetchone()

        top_category = top_row["category"] if top_row else "—"

        return {
            "total_spent": total_spent,
            "transaction_count": transaction_count,
            "top_category": top_category,
        }
    finally:
        conn.close()


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    """
    Return a list of dicts (newest-first), each with:
    'id', 'date', 'description', 'category', 'amount'.
    When date_from and/or date_to are provided, expenses are filtered accordingly.
    Returns an empty list if the user has no expenses.
    """
    # Clamp limit to a safe range (1 to 100)
    limit = max(1, min(limit, 100))
    conn = _get_db()
    try:
        date_filter, date_params = _build_date_filter(date_from, date_to)
        params = [user_id] + date_params
        params.append(limit)

        rows = conn.execute(
            "SELECT id, date, description, category, amount "
            "FROM expenses WHERE user_id = ?" + date_filter +
            " ORDER BY date DESC, id DESC LIMIT ?",
            params,
        ).fetchall()

        return [
            {
                "id": row["id"],
                "date": row["date"],
                "description": row["description"] or "",
                "category": row["category"],
                "amount": row["amount"],
            }
            for row in rows
        ]
    finally:
        conn.close()



def get_expense_by_id(expense_id, user_id):
    """
    Return a dict with 'id', 'user_id', 'amount', 'category', 'date',
    'description' for the given expense, but only if it is owned by user_id.

    Returns None if the expense does not exist OR is owned by a different
    user. The combined WHERE clause is the single ownership check — callers
    must not split the load from the ownership check.
    """
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "amount": row["amount"],
            "category": row["category"],
            "date": row["date"],
            "description": row["description"] or "",
        }
    finally:
        conn.close()


def update_expense(expense_id, user_id, amount, category, date, description):
    """
    Update the amount, category, date, and description of an expense row,
    but only if it is owned by user_id.

    Returns the number of rows affected (0 if the row does not exist or is
    owned by a different user; 1 on a successful update). The user_id and
    created_at columns are intentionally never overwritten.
    """
    conn = _get_db()
    try:
        cur = conn.execute(
            "UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? "
            "WHERE id = ? AND user_id = ?",
            (amount, category, date, description, expense_id, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_expense_row(expense_id, user_id):
    """
    Hard-delete the expense row identified by expense_id, but only if it is
    owned by user_id.

    Returns the number of rows affected:
      1  — row found and deleted
      0  — row did not exist OR is owned by a different user
    The combined WHERE clause prevents both "not found" and "wrong owner"
    from being distinguished by the caller, matching the security requirement.
    """
    conn = _get_db()
    try:
        cur = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_category_breakdown(user_id, date_from=None, date_to=None):
    """
    Return a list of dicts (ordered by amount desc), each with:
    'name', 'amount', 'pct'.
    'pct' values are integers that sum to exactly 100.
    When date_from and/or date_to are provided, expenses are filtered accordingly.
    Returns an empty list if the user has no expenses.
    """
    conn = _get_db()
    try:
        date_filter, date_params = _build_date_filter(date_from, date_to)
        params = [user_id] + date_params

        rows = conn.execute(
            "SELECT category AS name, SUM(amount) AS amount "
            "FROM expenses WHERE user_id = ?" + date_filter +
            " GROUP BY category ORDER BY amount DESC",
            params,
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
