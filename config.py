import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

    # LLM
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openrouter").lower()
    LLM_MODEL: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b:free")
    LLM_BASE_URL: str = os.getenv(
        "LLM_BASE_URL", "http://localhost:11434"
    )
    OPENROUTER_BASE_URL: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"
    )

    # PostgreSQL
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "debtors")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")

    @classmethod
    def database_url(cls) -> str:
        return (
            f"postgresql://{cls.POSTGRES_USER}:{cls.POSTGRES_PASSWORD}"
            f"@{cls.POSTGRES_HOST}:{cls.POSTGRES_PORT}/{cls.POSTGRES_DB}"
        )

    @classmethod
    def use_sqlite(cls) -> bool:
        return os.getenv("USE_SQLITE", "").lower() in ("1", "true", "yes")

    @classmethod
    def validate(cls) -> None:
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN is not set")
        if cls.LLM_PROVIDER == "openrouter" and not cls.OPENROUTER_API_KEY:
            errors.append("OPENROUTER_API_KEY is not set (for openrouter)")
        if errors:
            raise ValueError("Configuration errors:\n" + "\n".join(f"  • {e}" for e in errors))
