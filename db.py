import asyncpg
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

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    # ─── CRUD ──────────────────────────────────────────────────────

    async def add_debt(self, user_id: int, name: str, amount: int) -> int:
        """Добавить должника или увеличить долг. Возвращает новый баланс."""
        name = name.strip()
        async with self._pool.acquire() as conn:
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
        """Уменьшить долг. Возвращает новый баланс или None если должник не найден."""
        name = name.strip()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT amount FROM debtors WHERE user_id = $1 AND name = $2",
                user_id, name,
            )
            if row is None:
                return None
            new_amount = row["amount"] - amount
            if new_amount <= 0:
                await conn.execute(
                    "DELETE FROM debtors WHERE user_id = $1 AND name = $2",
                    user_id, name,
                )
                new_amount = 0
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

    async def get_debtor(self, user_id: int, name: str) -> Optional[int]:
        """Вернуть долг конкретного человека или None."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT amount FROM debtors WHERE user_id = $1 AND name = $2",
                user_id, name.strip(),
            )
            return row["amount"] if row else None

    async def list_debtors(self, user_id: int) -> list[tuple[str, int]]:
        """Вернуть список должников пользователя, отсортированный по убыванию."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, amount FROM debtors WHERE user_id = $1 ORDER BY amount DESC",
                user_id,
            )
            return [(r["name"], r["amount"]) for r in rows]

    async def clear_debtor(self, user_id: int, name: str) -> bool:
        """Удалить должника. Возвращает True если удалён, False если не найден."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM debtors WHERE user_id = $1 AND name = $2",
                user_id, name.strip(),
            )
            return result.split()[-1] != "0"

    async def get_total_debt(self, user_id: int) -> int:
        """Вернуть общую сумму долгов пользователя."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(SUM(amount), 0) as total FROM debtors WHERE user_id = $1",
                user_id,
            )
            return row["total"]
