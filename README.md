# 📋 DebtorBot — Telegram-бот для учёта должников

Бот помогает отслеживать, кто вам должен. Каждый пользователь видит только своих должников.

## Возможности

- **Команды:** `/add`, `/remove`, `/list`, `/check`, `/clear`
- **Естественный язык:** «Саня должен 500», «Петя отдал 300», «Кто мне должен?»
- **Пагинация:** автоматическое разбиение списка при >10 записях
- **Валидация:** нельзя добавить долг ≤ 0
- **Изоляция:** каждый пользователь видит только свои данные
- **PostgreSQL:** надёжное хранение с историей транзакций

## Быстрый старт

### 1. Получи токены

- **BOT_TOKEN** — напиши [@BotFather](https://t.me/BotFather) в Telegram
- **OPENROUTER_API_KEY** — зарегистрируйся на [openrouter.ai/keys](https://openrouter.ai/keys)

### 2. Запуск локально

```bash
# Установи зависимости
pip install -r requirements.txt

# Создай .env файл
cp .env.example .env
# Заполни BOT_TOKEN и OPENROUTER_API_KEY

# Запусти бота
python bot.py
```

### 3. Запуск через Docker

```bash
cp .env.example .env
# Заполни BOT_TOKEN и OPENROUTER_API_KEY

docker compose up -d --build
```

## Команды

| Команда | Описание | Пример |
|---|---|---|
| `/add [имя] [сумма]` | Добавить должника или увеличить долг | `/add Саня 500` |
| `/remove [имя] [сумма]` | Уменьшить долг | `/remove Саня 200` |
| `/list` | Показать всех должников (с пагинацией) | `/list` |
| `/check [имя]` | Узнать долг конкретного человека | `/check Саня` |
| `/clear [имя]` | Удалить должника из базы | `/clear Саня` |
| `/start`, `/help` | Справка | `/help` |

## Естественный язык

Бот понимает фразы вроде:

- «Саня должен мне 500 рублей» → добавит долг
- «Сколько мне должен Саня?» → покажет долг
- «Кто мне должен?» → список всех должников
- «Петя отдал 300» → уменьшит долг

## Структура проекта

```
tgbot/
├── bot.py              # aiogram бот, хендлеры
├── db.py               # asyncpg, PostgreSQL
├── llm.py              # парсинг через OpenRouter API
├── config.py           # загрузка env-переменных
├── requirements.txt    # зависимости
├── Dockerfile          # образ бота
├── docker-compose.yml  # bot + postgres
├── .env.example        # шаблон переменных
└── .gitignore
```

## Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | Токен Telegram-бота | — |
| `OPENROUTER_API_KEY` | Ключ OpenRouter API | — |
| `POSTGRES_HOST` | Хост PostgreSQL | `localhost` |
| `POSTGRES_PORT` | Порт PostgreSQL | `5432` |
| `POSTGRES_DB` | Имя базы данных | `debtors` |
| `POSTGRES_USER` | Пользователь БД | `postgres` |
| `POSTGRES_PASSWORD` | Пароль БД | `postgres` |
| `LLM_MODEL` | Модель для парсинга | `qwen/qwen3-coder:free` |
