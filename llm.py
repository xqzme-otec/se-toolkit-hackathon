import json
import logging
import httpx
from typing import Optional

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Ты — ассистент для управления базой должников.
Пользователь пишет сообщение на естественном языке. Твоя задача — понять намерение и извлечь имя и сумму.

Возможные намерения (intent):
- "add" — добавить должника или увеличить долг ("Саня должен 500", "добавь долг Пете 300")
- "remove" — уменьшить долг ("Петя отдал 200", "Саша вернул 100")
- "check" — узнать долг конкретного человека ("сколько должен Саня?", "долг Пети")
- "list" — показать всех должников ("кто мне должен?", "список должников", "все должники")
- "clear" — удалить должника ("удали Сашу из базы", "очисти долг Пети")
- "unknown" — не удалось определить намерение

Правила:
- Извлекай имя (name) и сумму (amount) когда это возможно.
- Если действие "list" или "unknown", name и amount могут быть null.
- amount — целое число.
- Отвечай ТОЛЬКО валидным JSON без пояснений.

Формат ответа (JSON):
{"intent": "add|remove|check|list|clear|unknown", "name": "Имя" или null, "amount": число или null}
"""


class LLMParseError(Exception):
    pass


def _parse_json_response(content: str) -> dict:
    """Распарить JSON-ответ от LLM."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    result = json.loads(content)

    expected_keys = {"intent", "name", "amount"}
    if not expected_keys.issubset(result.keys()):
        raise LLMParseError(f"LLM вернул JSON без нужных ключей: {result}")

    valid_intents = {"add", "remove", "check", "list", "clear", "unknown"}
    if result["intent"] not in valid_intents:
        raise LLMParseError(f"Неизвестное намерение: {result['intent']}")

    return result


async def _call_openai_compatible(
    messages: list[dict],
    model: str,
    base_url: str,
    api_key: Optional[str] = None,
    timeout: int = 30,
) -> str:
    """Вызов LLM через OpenAI-совместимый API."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            base_url,
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": 0,
                "max_tokens": 128,
            },
        )
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"].strip()


async def _call_ollama(
    messages: list[dict],
    model: str,
    base_url: str = "http://localhost:11434",
    timeout: int = 60,
) -> str:
    """Вызов локальной Ollama."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_predict": 128,
                },
            },
        )
        response.raise_for_status()
        data = response.json()

    return data["message"]["content"].strip()


async def parse_intent(
    user_message: str,
    provider: str = "openrouter",
    api_key: Optional[str] = None,
    model: str = "qwen/qwen3-coder:free",
    base_url: str = "https://openrouter.ai/api/v1/chat/completions",
    user_id: Optional[int] = None,
) -> dict:
    """
    Распарить сообщение пользователя через LLM.
    Возвращает dict с ключами: intent, name, amount.
    """
    log.debug("LLM parse_intent: provider=%s, user_id=%s, message=%r",
              provider, user_id, user_message)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        if provider == "ollama":
            content = await _call_ollama(messages, model, base_url)
        else:
            content = await _call_openai_compatible(
                messages, model, base_url, api_key
            )
    except httpx.HTTPError as e:
        raise LLMParseError(f"Ошибка запроса к LLM ({provider}): {e}") from e

    try:
        result = _parse_json_response(content)
    except json.JSONDecodeError as e:
        raise LLMParseError(f"LLM вернул невалидный JSON: {content}") from e

    log.debug(
        "LLM result: provider=%s, user_id=%s, intent=%s, name=%s, amount=%s",
        provider, user_id, result["intent"], result.get("name"), result.get("amount"),
    )

    return result
