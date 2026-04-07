import asyncio
import logging
import math
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from config import Config
from llm import parse_intent, LLMParseError

# ─── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Init ────────────────────────────────────────────────────────────
Config.validate()

if Config.use_sqlite():
    from db_sqlite import DatabaseSQLite
    db = DatabaseSQLite()
    log.info("Using SQLite (data/debtors.db)")
else:
    from db import Database
    db = Database(dsn=Config.database_url())
    log.info("Using PostgreSQL")

bot = Bot(token=Config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── Constants ───────────────────────────────────────────────────────
LIST_PAGE_SIZE = 10
REMINDER_INTERVAL = 3600  # check reminders every hour

# ─── FSM States ──────────────────────────────────────────────────────
class AddDebtState:
    waiting_name = "add:waiting_name"
    waiting_amount = "add:waiting_amount"
    waiting_date = "add:waiting_date"

# ─── Helpers ─────────────────────────────────────────────────────────

def _format_amount(amount: int) -> str:
    """Format amount with ruble pluralization."""
    n = abs(amount) % 100
    last_digit = n % 10
    if 11 <= n <= 19:
        return f"{amount} рублей"
    if last_digit == 1:
        return f"{amount} рубль"
    if 2 <= last_digit <= 4:
        return f"{amount} рубля"
    return f"{amount} рублей"


def _parse_command_args(text: str) -> tuple[str | None, int | None]:
    """Parse command arguments: name and amount."""
    parts = text.strip().split()
    if len(parts) < 2:
        return None, None
    name = parts[0]
    try:
        amount = int(parts[1])
    except ValueError:
        return name, None
    return name, amount


def _parse_date(text: str) -> str | None:
    """Try to extract DD.MM.YYYY from text."""
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
    return m.group(1) if m else None


def _build_main_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить долг"), KeyboardButton(text="➖ Уменьшить долг")],
            [KeyboardButton(text="📋 Список должников"), KeyboardButton(text="🔍 Проверить долг")],
            [KeyboardButton(text="🗑 Удалить должника")],
        ],
        resize_keyboard=True,
    )


def _build_list_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Pagination keyboard for /list."""
    buttons = []
    row = []
    if page > 1:
        row.append(InlineKeyboardButton(text="⬅️ Back", callback_data=f"list:{page - 1}"))
    if page < total_pages:
        row.append(InlineKeyboardButton(text="Forward ➡️", callback_data=f"list:{page + 1}"))
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Commands ────────────────────────────────────────────────────────

@dp.message(Command("start", "help"))
async def cmd_help(message: Message):
    help_text = (
        "📋 *Debtor Tracking Bot*\n\n"
        "*Commands:*\n"
        "/add [name] [amount] — add debtor or increase debt\n"
        "/remove [name] [amount] — decrease debt\n"
        "/list — show all debtors\n"
        "/check [name] — check specific person's debt\n"
        "/clear [name] — remove debtor from database\n\n"
        "💬 You can also use natural language:\n"
        "• _Sanya owes me 500 rubles_\n"
        "• _How much does Sanya owe?_\n"
        "• _Who owes me?_\n"
        "• _Petya paid back 300_\n\n"
        "Or use the buttons below 👇"
    )
    await message.answer(help_text, parse_mode="Markdown", reply_markup=_build_main_keyboard())


@dp.message(Command("add"))
async def cmd_add(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    name, amount = _parse_command_args(args[1]) if len(args) > 1 else (None, None)
    if not name or not amount:
        await message.answer(
            "❌ Usage: /add [name] [amount]\nExample: /add Sanya 500\n\n"
            "Or just press ➕ Add debt button below."
        )
        return
    due_date = _parse_date(args[1]) if len(args) > 1 else None
    new_amount = await db.add_debt(user_id, name, amount, due_date)
    date_msg = f"\n📅 Return by: {due_date}" if due_date else ""
    await message.answer(
        f"✅ {name}'s debt increased by {_format_amount(amount)}. Now: {_format_amount(new_amount)}{date_msg}"
    )


@dp.message(Command("remove"))
async def cmd_remove(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    name, amount = _parse_command_args(args[1]) if len(args) > 1 else (None, None)
    if not name or not amount:
        await message.answer("❌ Usage: /remove [name] [amount]\nExample: /remove Sanya 200")
        return
    result = await db.remove_debt(user_id, name, amount)
    if result is None:
        await message.answer(f"❌ {name} not found in your debtor database")
        return
    if result == 0:
        await message.answer(f"✅ {name}'s debt is fully paid and removed from database")
    else:
        await message.answer(
            f"✅ {name}'s debt decreased by {_format_amount(amount)}. Remaining: {_format_amount(result)}"
        )


@dp.message(Command("list"))
async def cmd_list(message: Message):
    user_id = message.from_user.id
    await _send_list_page(message, user_id, page=1)


async def _send_list_page(message: Message, user_id: int, page: int):
    """Send one page of debtors list."""
    all_debtors = await db.list_debtors(user_id)
    if not all_debtors:
        await message.answer("📭 Debtor list is empty")
        return

    total = await db.get_total_debt(user_id)
    total_pages = math.ceil(len(all_debtors) / LIST_PAGE_SIZE)

    start = (page - 1) * LIST_PAGE_SIZE
    end = start + LIST_PAGE_SIZE
    page_debtors = all_debtors[start:end]

    lines = []
    for d in page_debtors:
        line = f"• {d['name']}: {_format_amount(d['amount'])}"
        if d["due_date"]:
            line += f" (📅 {d['due_date']})"
        lines.append(line)

    header = f"📋 *Debtors (page {page}/{total_pages}):*"
    text = header + "\n" + "\n".join(lines) + f"\n\n💰 *Total:* {_format_amount(total)}"

    keyboard = _build_list_keyboard(page, total_pages) if total_pages > 1 else None
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data and c.data.startswith("list:"))
async def cb_list_page(callback: CallbackQuery):
    """Handle /list pagination button presses."""
    user_id = callback.from_user.id
    page = int(callback.data.split(":")[1])
    await _send_list_page(callback.message, user_id, page)
    await callback.answer()


@dp.message(Command("check"))
async def cmd_check(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Usage: /check [name]\nExample: /check Sanya")
        return
    name = args[1].strip()
    info = await db.get_debtor(user_id, name)
    if info is None:
        await message.answer(f"📭 {name} not in your debtor database")
        return
    amount = info["amount"]
    due = info["due_date"]
    if amount > 0:
        text = f"💰 {name} owes you {_format_amount(amount)}"
    elif amount < 0:
        text = f"💸 You owe {name} {_format_amount(abs(amount))}"
    else:
        text = f"📭 {name} has no debt"
    if due:
        text += f"\n📅 Return by: {due}"
    await message.answer(text)


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Usage: /clear [name]\nExample: /clear Sanya")
        return
    name = args[1].strip()
    if await db.clear_debtor(user_id, name):
        await message.answer(f"🗑 {name} removed from your debtor database")
    else:
        await message.answer(f"❌ {name} not found in your database")


# ─── Button handlers (main menu) ─────────────────────────────────────

@dp.message(F.text == "➕ Добавить долг")
async def btn_add_start(message: Message, state: FSMContext):
    await state.set_state(AddDebtState.waiting_name)
    await message.answer("📝 Введите имя должника:")


@dp.message(AddDebtState.waiting_name)
async def btn_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddDebtState.waiting_amount)
    await message.answer("💰 Введите сумму (можно с минусом, если должны вы):\n\n"
                         "Пример: 500 или -200")


@dp.message(AddDebtState.waiting_amount)
async def btn_add_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите целое число. Пример: 500 или -200")
        return
    await state.update_data(amount=amount)
    await state.set_state(AddDebtState.waiting_date)
    await message.answer(
        "📅 Введите дату возврата в формате ДД.ММ.ГГГГ (или /skip если не нужно):\n\n"
        "Пример: 15.05.2026",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="/skip")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@dp.message(AddDebtState.waiting_date, Command("skip"))
@dp.message(AddDebtState.waiting_date, F.text == "/skip")
async def btn_add_skip_date(message: Message, state: FSMContext):
    await _finish_add(message, state, due_date=None)


@dp.message(AddDebtState.waiting_date)
async def btn_add_date(message: Message, state: FSMContext):
    due_date = _parse_date(message.text)
    if not due_date:
        await message.answer("❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ\nПример: 15.05.2026")
        return
    await _finish_add(message, state, due_date=due_date)


async def _finish_add(message: Message, state: FSMContext, due_date: str | None):
    data = await state.get_data()
    name = data["name"]
    amount = data["amount"]
    user_id = message.from_user.id
    new_amount = await db.add_debt(user_id, name, amount, due_date)
    date_msg = f"\n📅 Return by: {due_date}" if due_date else ""
    await message.answer(
        f"✅ {name}: {_format_amount(amount)}. Now: {_format_amount(new_amount)}{date_msg}",
        reply_markup=_build_main_keyboard(),
    )
    await state.clear()


@dp.message(F.text == "➖ Уменьшить долг")
async def btn_remove(message: Message):
    await message.answer(
        "Используйте команду:\n/remove [имя] [сумма]\n\n"
        "Пример: /remove Саня 200"
    )


@dp.message(F.text == "📋 Список должников")
async def btn_list(message: Message):
    user_id = message.from_user.id
    await _send_list_page(message, user_id, page=1)


@dp.message(F.text == "🔍 Проверить долг")
async def btn_check(message: Message):
    await message.answer(
        "Используйте команду:\n/check [имя]\n\n"
        "Пример: /check Саня"
    )


@dp.message(F.text == "🗑 Удалить должника")
async def btn_clear(message: Message):
    await message.answer(
        "Используйте команду:\n/clear [имя]\n\n"
        "Пример: /clear Саня"
    )


# ─── Natural language (LLM) ──────────────────────────────────────────

@dp.message()
async def handle_natural_language(message: Message, state: FSMContext):
    # Skip if in FSM state
    current_state = await state.get_state()
    if current_state:
        return

    user_id = message.from_user.id
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        result = await parse_intent(
            message.text,
            provider=Config.LLM_PROVIDER,
            api_key=Config.OPENROUTER_API_KEY,
            model=Config.LLM_MODEL,
            base_url=Config.LLM_BASE_URL if Config.LLM_PROVIDER == "ollama" else Config.OPENROUTER_BASE_URL,
            user_id=user_id,
        )
    except Exception as e:
        log.exception("LLM request error")
        await message.answer(
            "⚠️ Error processing request. Try again later or use commands."
        )
        return

    intent = result["intent"]
    name = result.get("name")
    amount = result.get("amount")
    due_date = result.get("due_date")

    if intent == "unknown" or (intent not in ("list",) and not name):
        await message.answer(
            "🤔 Couldn't understand. Try rephrasing or use commands:\n"
            "/add, /remove, /list, /check, /clear"
        )
        return

    if intent == "add":
        if not amount:
            await message.answer("❌ Specify an amount. Example: /add Sanya 500")
            return
        new_amount = await db.add_debt(user_id, name, amount, due_date)
        date_msg = f"\n📅 Return by: {due_date}" if due_date else ""
        if new_amount > 0:
            await message.answer(
                f"✅ {name} owes {_format_amount(new_amount)}{date_msg}"
            )
        elif new_amount < 0:
            await message.answer(
                f"✅ You owe {name} {_format_amount(abs(new_amount))}{date_msg}"
            )
        else:
            await message.answer(f"✅ {name} has no debt now{date_msg}")

    elif intent == "remove":
        if not amount:
            await message.answer("❌ Specify an amount. Example: /remove Sanya 200")
            return
        res = await db.remove_debt(user_id, name, amount)
        if res is None:
            await message.answer(f"❌ {name} not found in your database")
            return
        if res == 0:
            await message.answer(f"✅ {name}'s debt is fully paid")
        else:
            await message.answer(
                f"✅ {name}'s debt decreased by {_format_amount(amount)}. Remaining: {_format_amount(res)}"
            )

    elif intent == "check":
        info = await db.get_debtor(user_id, name)
        if info is None:
            await message.answer(f"📭 {name} not in your database")
            return
        a = info["amount"]
        if a > 0:
            text = f"💰 {name} owes you {_format_amount(a)}"
        elif a < 0:
            text = f"💸 You owe {name} {_format_amount(abs(a))}"
        else:
            text = f"📭 {name} has no debt"
        if info["due_date"]:
            text += f"\n📅 Return by: {info['due_date']}"
        await message.answer(text)

    elif intent == "list":
        all_debtors = await db.list_debtors(user_id)
        if not all_debtors:
            await message.answer("📭 Debtor list is empty")
            return
        total = await db.get_total_debt(user_id)
        total_pages = math.ceil(len(all_debtors) / LIST_PAGE_SIZE)
        page_debtors = all_debtors[:LIST_PAGE_SIZE]
        lines = []
        for d in page_debtors:
            line = f"• {d['name']}: {_format_amount(d['amount'])}"
            if d["due_date"]:
                line += f" (📅 {d['due_date']})"
            lines.append(line)
        header = f"📋 *Debtors (page 1/{total_pages}):*"
        text = header + "\n" + "\n".join(lines) + f"\n\n💰 *Total:* {_format_amount(total)}"
        keyboard = _build_list_keyboard(1, total_pages) if total_pages > 1 else None
        await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

    elif intent == "clear":
        if await db.clear_debtor(user_id, name):
            await message.answer(f"🗑 {name} removed from database")
        else:
            await message.answer(f"❌ {name} not found in database")


# ─── Reminder background task ────────────────────────────────────────

async def reminder_task():
    """Check every REMINDER_INTERVAL and notify users about debtors due tomorrow."""
    log.info("Reminder task started")
    while True:
        try:
            due_tomorrow = await db.get_all_due_tomorrow()
            if due_tomorrow:
                # Group by user_id
                users: dict[int, list] = {}
                for uid, name, amount, dd in due_tomorrow:
                    users.setdefault(uid, []).append((name, amount, dd))

                for uid, debtors in users.items():
                    lines = [
                        f"• {n} — {_format_amount(a)}" for n, a, _ in debtors
                    ]
                    text = "⏰ *Reminder — tomorrow these debtors should pay you back:*\n" + "\n".join(lines)
                    try:
                        await bot.send_message(uid, text, parse_mode="Markdown")
                    except Exception as e:
                        log.warning("Failed to send reminder to user %s: %s", uid, e)

            log.debug("Reminder check done, %d debtors due tomorrow", len(due_tomorrow))
        except Exception as e:
            log.exception("Error in reminder task")

        await asyncio.sleep(REMINDER_INTERVAL)


# ─── Start ───────────────────────────────────────────────────────────

async def main():
    log.info("Initializing database...")
    await db.init()
    log.info("Starting bot...")

    # Start reminder background task
    asyncio.create_task(reminder_task())

    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
