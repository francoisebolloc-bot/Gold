"""
Client centralisé pour tous les appels à Claude AI.
Chaque agent passe par ask_claude() avec son propre prompt système.
"""
import json
import httpx
from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


async def ask_claude(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str:
    """Appelle Claude et retourne le texte brut de la réponse."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY manquante dans les variables d'environnement")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(ANTHROPIC_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(parts).strip()


async def ask_claude_json(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> dict:
    """Variante qui force une réponse JSON stricte et la parse."""
    strict_system = (
        system_prompt
        + "\n\nIMPORTANT: réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, "
        "sans balises markdown, sans ```."
    )
    raw = await ask_claude(strict_system, user_prompt, max_tokens=max_tokens)
    cleaned = raw.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            return json.loads(cleaned[start:end + 1])
        raise
