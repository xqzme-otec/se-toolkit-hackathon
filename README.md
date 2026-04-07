# SE Toolkit Hackathon — Telegram Debtor Bot

A Telegram bot for tracking personal debts with natural language understanding powered by LLM.

## Features

- **Commands**: `/add`, `/remove`, `/list`, `/check`, `/clear`
- **Natural language**: "Sanya owes me 500", "Who owes me?", "Petya paid back 300"
- **Multi-user**: each Telegram user has their own isolated debtor list
- **Pagination**: automatic page splitting when the list exceeds 10 entries
- **Validation**: prevents zero or negative amounts
- **Transaction history**: every change is logged in the database
- **LLM providers**: OpenRouter API or local Ollama (switchable via `.env`)
- **SQLite / PostgreSQL**: SQLite by default, PostgreSQL available via Docker Compose

## Quick Start

### Local Run

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in BOT_TOKEN and OPENROUTER_API_KEY
python bot.py
```

### Docker Compose

```bash
cp .env.example .env   # fill in BOT_TOKEN and OPENROUTER_API_KEY
docker compose up -d --build
```

## Commands

| Command | Description | Example |
|---|---|---|
| `/add [name] [amount]` | Add a debtor or increase debt | `/add Sanya 500` |
| `/remove [name] [amount]` | Decrease debt | `/remove Sanya 200` |
| `/list` | Show all debtors (paginated) | `/list` |
| `/check [name]` | Check a specific person's debt | `/check Sanya` |
| `/clear [name]` | Remove a debtor | `/clear Sanya` |
| `/start`, `/help` | Help message | `/help` |

## Natural Language

The bot understands phrases like:

- "Sanya owes me 500 rubles" → adds debt
- "How much does Sanya owe?" → shows debt
- "Who owes me?" → lists all debtors
- "Petya paid back 300" → reduces debt

## LLM Providers

| Provider | Setup | Notes |
|---|---|---|
| **OpenRouter** | `LLM_PROVIDER=openrouter`, set `OPENROUTER_API_KEY` | Free models available, rate-limited |
| **Ollama** | `LLM_PROVIDER=ollama`, install Ollama locally | No rate limits, runs locally |

### Using Ollama

```bash
brew install ollama
ollama serve &
ollama pull qwen3:4b
```

Then set in `.env`:
```
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:4b
LLM_BASE_URL=http://localhost:11434
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BOT_TOKEN` | Telegram bot token (from @BotFather) | — |
| `OPENROUTER_API_KEY` | OpenRouter API key | — |
| `LLM_PROVIDER` | LLM backend: `openrouter` or `ollama` | `openrouter` |
| `LLM_MODEL` | Model name | `openai/gpt-oss-120b:free` |
| `LLM_BASE_URL` | LLM API base URL | OpenRouter URL |
| `USE_SQLITE` | Use SQLite instead of PostgreSQL | `1` |
| `POSTGRES_HOST` | PostgreSQL host | `localhost` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_DB` | Database name | `debtors` |
| `POSTGRES_USER` | Database user | `postgres` |
| `POSTGRES_PASSWORD` | Database password | `postgres` |

## Project Structure

```
├── bot.py              # aiogram bot with handlers
├── db.py               # asyncpg PostgreSQL driver
├── db_sqlite.py        # SQLite driver (default)
├── llm.py              # LLM intent parsing (OpenRouter + Ollama)
├── config.py           # environment variable loader
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker image
├── docker-compose.yml  # Docker Compose setup
├── .env.example        # environment template
└── README.md
```

## Deploy to VM

```bash
# Copy files to VM
scp -r ./* root@<VM_IP>:/opt/tgbot/
scp .env root@<VM_IP>:/opt/tgbot/.env

# Build and run on VM
ssh root@<VM_IP> "cd /opt/tgbot && docker compose up -d --build"
```

## License

MIT
