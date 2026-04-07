import os
import sqlite3
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
                    UNIQUE(user_id, name)
                )
            """)
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
            conn.commit()

    async def init(self) -> None:
        self._init_db()

    async def close(self) -> None:
        pass

    async def add_debt(self, user_id: int, name: str, amount: int) -> int:
        name = name.strip()
        with self._get_conn() as conn:
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
        name = name.strip()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT amount FROM debtors WHERE user_id = ? AND name = ?",
                (user_id, name),
            ).fetchone()
            if row is None:
                return None
            new_amount = row["amount"] - amount
            if new_amount <= 0:
                conn.execute(
                    "DELETE FROM debtors WHERE user_id = ? AND name = ?",
                    (user_id, name),
                )
                new_amount = 0
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

    async def get_debtor(self, user_id: int, name: str) -> Optional[int]:
        row = self._get_conn().execute(
            "SELECT amount FROM debtors WHERE user_id = ? AND name = ?",
            (user_id, name.strip()),
        ).fetchone()
        return row["amount"] if row else None

    async def list_debtors(self, user_id: int) -> list[tuple[str, int]]:
        rows = self._get_conn().execute(
            "SELECT name, amount FROM debtors WHERE user_id = ? ORDER BY amount DESC",
            (user_id,),
        ).fetchall()
        return [(r["name"], r["amount"]) for r in rows]

    async def clear_debtor(self, user_id: int, name: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM debtors WHERE user_id = ? AND name = ?",
                (user_id, name.strip()),
            )
            return cursor.rowcount > 0

    async def get_total_debt(self, user_id: int) -> int:
        row = self._get_conn().execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM debtors WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["total"]
