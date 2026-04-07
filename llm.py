import json
import logging
import httpx
from typing import Optional

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an assistant for managing a debtor database.
The user writes in natural language. Your task is to understand the intent and extract name, amount, and due date.

Possible intents (intent):
- "add" — add a debtor or increase debt ("Sanya owes me 500", "add debt to Petya 300")
- "remove" — decrease debt ("Petya paid back 200", "Sasha returned 100")
- "check" — check a specific person's debt ("how much does Sanya owe?", "Petya's debt")
- "list" — show all debtors ("who owes me?", "list of debtors", "all debtors")
- "clear" — remove a debtor ("delete Sasha from the database", "clear Petya's debt")
- "unknown" — could not determine intent

Rules:
- Extract name, amount, and due_date when possible.
- For "list" or "unknown", name and amount may be null.
- amount — integer (can be negative if the user owes someone).
- due_date — date in DD.MM.YYYY format, or null if not specified.
- Phrases like "вернуть 15 мая", "deadline 20.12.2025", "к понедельнику" — extract as due_date.
- Reply ONLY with valid JSON, no explanations.

Response format (JSON):
{"intent": "add|remove|check|list|clear|unknown", "name": "Name" or null, "amount": number or null, "due_date": "DD.MM.YYYY" or null}
"""


class LLMParseError(Exception):
    pass


def _parse_json_response(content: str) -> dict:
    """Parse JSON response from LLM."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    result = json.loads(content)

    expected_keys = {"intent", "name", "amount"}
    if not expected_keys.issubset(result.keys()):
        raise LLMParseError(f"LLM returned JSON without required keys: {result}")

    valid_intents = {"add", "remove", "check", "list", "clear", "unknown"}
    if result["intent"] not in valid_intents:
        raise LLMParseError(f"Unknown intent: {result['intent']}")

    return result


async def _call_openai_compatible(
    messages: list[dict],
    model: str,
    base_url: str,
    api_key: Optional[str] = None,
    timeout: int = 30,
) -> str:
    """Call LLM via OpenAI-compatible API."""
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
    """Call local Ollama."""
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
    Parse user message via LLM.
    Returns dict with keys: intent, name, amount, due_date.
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
        raise LLMParseError(f"LLM request error ({provider}): {e}") from e

    try:
        result = _parse_json_response(content)
    except json.JSONDecodeError as e:
        raise LLMParseError(f"LLM returned invalid JSON: {content}") from e

    log.debug(
        "LLM result: provider=%s, user_id=%s, intent=%s, name=%s, amount=%s, due_date=%s",
        provider, user_id, result["intent"], result.get("name"),
        result.get("amount"), result.get("due_date"),
    )

    return result
