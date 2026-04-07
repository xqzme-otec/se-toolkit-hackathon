import asyncpg
from datetime import date
from typing import Optional


class Database:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def init(self) -> None:
        self._pool = await asyncpg.create_pool(dsn=self._dsn)
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS debtors (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    name TEXT NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 0,
                    due_date DATE,
                    UNIQUE(user_id, name)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    debtor_name TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debtors_user_id ON debtors(user_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debtors_due_date ON debtors(due_date)
            """)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def add_debt(
        self, user_id: int, name: str, amount: int, due_date: Optional[str] = None
    ) -> int:
        """Add debtor or increase debt. Returns new balance."""
        name = name.strip()
        async with self._pool.acquire() as conn:
            if due_date:
                await conn.execute(
                    """INSERT INTO debtors (user_id, name, amount, due_date) VALUES ($1, $2, $3, $4)
                       ON CONFLICT(user_id, name)
                       DO UPDATE SET amount = debtors.amount + $3,
                                     due_date = COALESCE(excluded.due_date, debtors.due_date)""",
                    user_id, name, amount, due_date,
                )
            else:
                await conn.execute(
                    """INSERT INTO debtors (user_id, name, amount) VALUES ($1, $2, $3)
                       ON CONFLICT(user_id, name)
                       DO UPDATE SET amount = debtors.amount + $3""",
                    user_id, name, amount,
                )
            await conn.execute(
                "INSERT INTO transactions (user_id, debtor_name, amount, action) VALUES ($1, $2, $3, 'add')",
                user_id, name, amount,
            )
            row = await conn.fetchrow(
                "SELECT amount FROM debtors WHERE user_id = $1 AND name = $2",
                user_id, name,
            )
            return row["amount"]

    async def remove_debt(self, user_id: int, name: str, amount: int) -> Optional[int]:
        """Decrease debt. Returns new balance or None if debtor not found."""
        name = name.strip()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT amount FROM debtors WHERE user_id = $1 AND name = $2",
                user_id, name,
            )
            if row is None:
                return None
            new_amount = row["amount"] - amount
            if new_amount == 0:
                await conn.execute(
                    "DELETE FROM debtors WHERE user_id = $1 AND name = $2",
                    user_id, name,
                )
            else:
                await conn.execute(
                    "UPDATE debtors SET amount = $1 WHERE user_id = $2 AND name = $3",
                    new_amount, user_id, name,
                )
            await conn.execute(
                "INSERT INTO transactions (user_id, debtor_name, amount, action) VALUES ($1, $2, $3, 'remove')",
                user_id, name, amount,
            )
            return new_amount

    async def get_debtor(self, user_id: int, name: str) -> Optional[dict]:
        """Get debtor info: amount, due_date. Returns None if not found."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT amount, due_date FROM debtors WHERE user_id = $1 AND name = $2",
                user_id, name.strip(),
            )
            if row is None:
                return None
            dd = row["due_date"]
            return {
                "amount": row["amount"],
                "due_date": dd.strftime("%d.%m.%Y") if dd else None,
            }

    async def list_debtors(self, user_id: int) -> list[dict]:
        """List all debtors for user, sorted by amount descending."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, amount, due_date FROM debtors WHERE user_id = $1 ORDER BY amount DESC",
                user_id,
            )
            result = []
            for r in rows:
                dd = r["due_date"]
                result.append({
                    "name": r["name"],
                    "amount": r["amount"],
                    "due_date": dd.strftime("%d.%m.%Y") if dd else None,
                })
            return result

    async def clear_debtor(self, user_id: int, name: str) -> bool:
        """Remove debtor. Returns True if removed, False if not found."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM debtors WHERE user_id = $1 AND name = $2",
                user_id, name.strip(),
            )
            return result.split()[-1] != "0"

    async def get_total_debt(self, user_id: int) -> int:
        """Get total debt amount for user."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(amount), 0) as total FROM debtors WHERE user_id = $1",
                user_id,
            )
            return row["total"]

    async def get_all_due_tomorrow(self) -> list[tuple[int, str, int, str]]:
        """Get all users with debtors due tomorrow. For background reminders."""
        tomorrow = date.today().strftime("%d.%m.%Y")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT user_id, name, amount, due_date
                   FROM debtors
                   WHERE to_char(due_date, 'DD.MM.YYYY') = $1""",
                tomorrow,
            )
            return [
                (r["user_id"], r["name"], r["amount"], r["due_date"].strftime("%d.%m.%Y"))
                for r in rows
            ]
