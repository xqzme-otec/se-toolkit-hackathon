import os
import sqlite3
from datetime import datetime, date
from typing import Optional


class DatabaseSQLite:
    def __init__(self, db_path: str = "data/debtors.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS debtors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 0,
                    due_date TEXT,
                    UNIQUE(user_id, name)
                )
            """)
            # Migration: add due_date column if it doesn't exist
            try:
                conn.execute("ALTER TABLE debtors ADD COLUMN due_date TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    debtor_name TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debtors_user_id ON debtors(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debtors_due_date ON debtors(due_date)
            """)
            conn.commit()

    async def init(self) -> None:
        self._init_db()

    async def close(self) -> None:
        pass

    async def add_debt(
        self, user_id: int, name: str, amount: int, due_date: Optional[str] = None
    ) -> int:
        """Add debtor or increase debt. Returns new balance."""
        name = name.strip()
        with self._get_conn() as conn:
            if due_date:
                conn.execute(
                    """INSERT INTO debtors (user_id, name, amount, due_date) VALUES (?, ?, ?, ?)
                       ON CONFLICT(user_id, name)
                       DO UPDATE SET amount = amount + ?, due_date = COALESCE(excluded.due_date, debtors.due_date)""",
                    (user_id, name, amount, due_date, amount),
                )
            else:
                conn.execute(
                    """INSERT INTO debtors (user_id, name, amount) VALUES (?, ?, ?)
                       ON CONFLICT(user_id, name) DO UPDATE SET amount = amount + ?""",
                    (user_id, name, amount, amount),
                )
            conn.execute(
                "INSERT INTO transactions (user_id, debtor_name, amount, action) VALUES (?, ?, ?, 'add')",
                (user_id, name, amount),
            )
            row = conn.execute(
                "SELECT amount FROM debtors WHERE user_id = ? AND name = ?",
                (user_id, name),
            ).fetchone()
            return row["amount"]

    async def remove_debt(self, user_id: int, name: str, amount: int) -> Optional[int]:
        """Decrease debt. Returns new balance or None if debtor not found."""
        name = name.strip()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT amount FROM debtors WHERE user_id = ? AND name = ?",
                (user_id, name),
            ).fetchone()
            if row is None:
                return None
            new_amount = row["amount"] - amount
            if new_amount == 0:
                conn.execute(
                    "DELETE FROM debtors WHERE user_id = ? AND name = ?",
                    (user_id, name),
                )
            else:
                conn.execute(
                    "UPDATE debtors SET amount = ? WHERE user_id = ? AND name = ?",
                    (new_amount, user_id, name),
                )
            conn.execute(
                "INSERT INTO transactions (user_id, debtor_name, amount, action) VALUES (?, ?, ?, 'remove')",
                (user_id, name, amount),
            )
            return new_amount

    async def get_debtor(self, user_id: int, name: str) -> Optional[dict]:
        """Get debtor info: amount, due_date. Returns None if not found."""
        row = self._get_conn().execute(
            "SELECT amount, due_date FROM debtors WHERE user_id = ? AND name = ?",
            (user_id, name.strip()),
        ).fetchone()
        if row is None:
            return None
        return {"amount": row["amount"], "due_date": row["due_date"]}

    async def list_debtors(self, user_id: int) -> list[dict]:
        """List all debtors for user, sorted by amount descending."""
        rows = self._get_conn().execute(
            "SELECT name, amount, due_date FROM debtors WHERE user_id = ? ORDER BY amount DESC",
            (user_id,),
        ).fetchall()
        return [
            {"name": r["name"], "amount": r["amount"], "due_date": r["due_date"]}
            for r in rows
        ]

    async def clear_debtor(self, user_id: int, name: str) -> bool:
        """Remove debtor. Returns True if removed, False if not found."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM debtors WHERE user_id = ? AND name = ?",
                (user_id, name.strip()),
            )
            return cursor.rowcount > 0

    async def get_total_debt(self, user_id: int) -> int:
        """Get total debt amount for user."""
        row = self._get_conn().execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM debtors WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["total"]

    async def get_due_tomorrow(self, user_id: int) -> list[dict]:
        """Get debtors whose due_date is tomorrow."""
        tomorrow = date.today().strftime("%d.%m.%Y")
        rows = self._get_conn().execute(
            "SELECT name, amount, due_date FROM debtors WHERE user_id = ? AND due_date = ?",
            (user_id, tomorrow),
        ).fetchall()
        return [
            {"name": r["name"], "amount": r["amount"], "due_date": r["due_date"]}
            for r in rows
        ]

    async def get_all_due_tomorrow(self) -> list[tuple[int, str, int, str]]:
        """Get all users with debtors due tomorrow. For background reminders."""
        tomorrow = date.today().strftime("%d.%m.%Y")
        rows = self._get_conn().execute(
            "SELECT user_id, name, amount, due_date FROM debtors WHERE due_date = ?",
            (tomorrow,),
        ).fetchall()
        return [(r["user_id"], r["name"], r["amount"], r["due_date"]) for r in rows]
