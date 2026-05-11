import sqlite3
from werkzeug.security import generate_password_hash


def get_db():
    conn = sqlite3.connect("spendly.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
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
    conn.close()


def seed_db():
    conn = get_db()
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
        conn.close()
        return

    hashed = generate_password_hash("demo123")
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", hashed),
    )
    user_id = cur.lastrowid

    import datetime
    today = datetime.date.today()
    year = today.year
    month = today.month

    expenses = [
        (user_id, 450.0, "Food", f"{year}-{month:02d}-05", "Lunch at restaurant"),
        (user_id, 120.0, "Transport", f"{year}-{month:02d}-08", "Uber to office"),
        (user_id, 2500.0, "Bills", f"{year}-{month:02d}-10", "Electricity bill"),
        (user_id, 800.0, "Health", f"{year}-{month:02d}-12", "Pharmacy"),
        (user_id, 600.0, "Entertainment", f"{year}-{month:02d}-15", "Movie tickets"),
        (user_id, 1500.0, "Shopping", f"{year}-{month:02d}-18", "New headphones"),
        (user_id, 320.0, "Food", f"{year}-{month:02d}-20", "Grocery shopping"),
        (user_id, 200.0, "Other", f"{year}-{month:02d}-22", "Miscellaneous expense"),
    ]

    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    conn.commit()
    conn.close()
