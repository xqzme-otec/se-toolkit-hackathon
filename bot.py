import asyncio
import logging
import math

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from config import Config
from llm import parse_intent, LLMParseError

# ─── Настройка логирования ───────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Инициализация ───────────────────────────────────────────────────
Config.validate()

if Config.use_sqlite():
    from db_sqlite import DatabaseSQLite
    db = DatabaseSQLite()
    log.info("Используется SQLite (debtors.db)")
else:
    from db import Database
    db = Database(dsn=Config.database_url())
    log.info("Используется PostgreSQL")

bot = Bot(token=Config.BOT_TOKEN)
dp = Dispatcher()

# ─── Константы ───────────────────────────────────────────────────────
LIST_PAGE_SIZE = 10

# ─── Вспомогательные функции ─────────────────────────────────────────

def _format_amount(amount: int) -> str:
    """Склонение слова «рубль»."""
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
    """Парсит аргументы команды: имя и сумму."""
    parts = text.strip().split()
    if len(parts) < 2:
        return None, None
    name = parts[0]
    try:
        amount = int(parts[1])
    except ValueError:
        return name, None
    return name, amount


def _validate_amount(amount: int) -> bool:
    """Проверяет, что сумма положительная."""
    if amount <= 0:
        return False
    return True


def _build_list_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Создаёт inline-клавиатуру с кнопками навигации по страницам."""
    buttons = []
    row = []
    if page > 1:
        row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"list:{page - 1}"))
    if page < total_pages:
        row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"list:{page + 1}"))
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Команды ─────────────────────────────────────────────────────────

@dp.message(Command("start", "help"))
async def cmd_help(message: Message):
    help_text = (
        "📋 *Бот для учёта должников*\n\n"
        "*Команды:*\n"
        "/add [имя] [сумма] — добавить должника или увеличить долг\n"
        "/remove [имя] [сумма] — уменьшить долг\n"
        "/list — показать всех должников\n"
        "/check [имя] — узнать долг конкретного человека\n"
        "/clear [имя] — удалить должника из базы\n\n"
        "💬 Можно писать простым языком:\n"
        "• _Саня должен мне 500 рублей_\n"
        "• _Сколько мне должен Саня?_\n"
        "• _Кто мне должен?_\n"
        "• _Петя отдал 300_"
    )
    await message.answer(help_text, parse_mode="Markdown")


@dp.message(Command("add"))
async def cmd_add(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    name, amount = _parse_command_args(args[1]) if len(args) > 1 else (None, None)
    if not name or not amount:
        await message.answer("❌ Использование: /add [имя] [сумма]\nПример: /add Саня 500")
        return
    if not _validate_amount(amount):
        await message.answer("❌ Сумма должна быть положительным числом")
        return
    new_amount = await db.add_debt(user_id, name, amount)
    await message.answer(
        f"✅ Долг {name} увеличен на {_format_amount(amount)}. Теперь: {_format_amount(new_amount)}"
    )


@dp.message(Command("remove"))
async def cmd_remove(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    name, amount = _parse_command_args(args[1]) if len(args) > 1 else (None, None)
    if not name or not amount:
        await message.answer("❌ Использование: /remove [имя] [сумма]\nПример: /remove Саня 200")
        return
    result = await db.remove_debt(user_id, name, amount)
    if result is None:
        await message.answer(f"❌ {name} не найден в вашей базе должников")
        return
    if result == 0:
        await message.answer(f"✅ Долг {name} полностью погашен и удалён из базы")
    else:
        await message.answer(
            f"✅ Долг {name} уменьшен на {_format_amount(amount)}. Остаток: {_format_amount(result)}"
        )


@dp.message(Command("list"))
async def cmd_list(message: Message):
    user_id = message.from_user.id
    await _send_list_page(message, user_id, page=1)


async def _send_list_page(message: Message, user_id: int, page: int):
    """Отправить одну страницу списка должников."""
    all_debtors = await db.list_debtors(user_id)
    if not all_debtors:
        await message.answer("📭 Список должников пуст")
        return

    total = await db.get_total_debt(user_id)
    total_pages = math.ceil(len(all_debtors) / LIST_PAGE_SIZE)

    start = (page - 1) * LIST_PAGE_SIZE
    end = start + LIST_PAGE_SIZE
    page_debtors = all_debtors[start:end]

    lines = [f"• {name}: {_format_amount(amount)}" for name, amount in page_debtors]
    header = f"📋 *Должники (стр. {page}/{total_pages}):*"
    text = header + "\n" + "\n".join(lines) + f"\n\n💰 *Итого:* {_format_amount(total)}"

    keyboard = _build_list_keyboard(page, total_pages) if total_pages > 1 else None
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data and c.data.startswith("list:"))
async def cb_list_page(callback):
    """Обработка нажатий кнопок пагинации /list."""
    user_id = callback.from_user.id
    page = int(callback.data.split(":")[1])
    await _send_list_page(callback.message, user_id, page)
    await callback.answer()


@dp.message(Command("check"))
async def cmd_check(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /check [имя]\nПример: /check Саня")
        return
    name = args[1].strip()
    amount = await db.get_debtor(user_id, name)
    if amount is None:
        await message.answer(f"📭 {name} нет в вашей базе должников")
        return
    await message.answer(f"💰 {name} должен {_format_amount(amount)}")


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /clear [имя]\nПример: /clear Саня")
        return
    name = args[1].strip()
    if await db.clear_debtor(user_id, name):
        await message.answer(f"🗑 {name} удалён из вашей базы должников")
    else:
        await message.answer(f"❌ {name} не найден в вашей базе")


# ─── Обработка естественного языка (LLM) ─────────────────────────────

@dp.message()
async def handle_natural_language(message: Message):
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
        log.exception("Ошибка при запросе к LLM")
        await message.answer(
            "⚠️ Ошибка при обработке запроса. Попробуйте позже или используйте команды."
        )
        return

    intent = result["intent"]
    name = result.get("name")
    amount = result.get("amount")

    if intent == "unknown" or (intent not in ("list",) and not name):
        await message.answer(
            "🤔 Не удалось понять, что вы хотите. Попробуйте переформулировать "
            "или используйте команды:\n/add, /remove, /list, /check, /clear"
        )
        return

    if intent == "add":
        if not amount or not _validate_amount(amount):
            await message.answer("❌ Укажите положительную сумму. Пример: /add Саня 500")
            return
        new_amount = await db.add_debt(user_id, name, amount)
        await message.answer(
            f"✅ Долг {name}: {_format_amount(amount)}. Теперь: {_format_amount(new_amount)}"
        )

    elif intent == "remove":
        if not amount or amount <= 0:
            await message.answer("❌ Укажите сумму. Пример: /remove Саня 200")
            return
        res = await db.remove_debt(user_id, name, amount)
        if res is None:
            await message.answer(f"❌ {name} не найден в вашей базе")
            return
        if res == 0:
            await message.answer(f"✅ Долг {name} полностью погашен")
        else:
            await message.answer(
                f"✅ Долг {name} уменьшен на {_format_amount(amount)}. Остаток: {_format_amount(res)}"
            )

    elif intent == "check":
        debt = await db.get_debtor(user_id, name)
        if debt is None:
            await message.answer(f"📭 {name} нет в вашей базе должников")
        else:
            await message.answer(f"💰 {name} должен {_format_amount(debt)}")

    elif intent == "list":
        all_debtors = await db.list_debtors(user_id)
        if not all_debtors:
            await message.answer("📭 Список должников пуст")
            return
        total = await db.get_total_debt(user_id)
        total_pages = math.ceil(len(all_debtors) / LIST_PAGE_SIZE)
        page_debtors = all_debtors[:LIST_PAGE_SIZE]
        lines = [f"• {n}: {_format_amount(a)}" for n, a in page_debtors]
        header = f"📋 *Должники (стр. 1/{total_pages}):*"
        text = header + "\n" + "\n".join(lines) + f"\n\n💰 *Итого:* {_format_amount(total)}"
        keyboard = _build_list_keyboard(1, total_pages) if total_pages > 1 else None
        await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

    elif intent == "clear":
        if await db.clear_debtor(user_id, name):
            await message.answer(f"🗑 {name} удалён из базы")
        else:
            await message.answer(f"❌ {name} не найден в вашей базе")


# ─── Запуск ──────────────────────────────────────────────────────────

async def main():
    log.info("Инициализация базы данных...")
    await db.init()
    log.info("Запуск бота...")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
