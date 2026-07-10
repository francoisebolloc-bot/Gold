"""
Client centralisé pour tous les appels à l'IA — utilise Google Gemini (gratuit, sans carte).
Interface simple : ask_ai() et ask_ai_json().
n'aient pas besoin d'être réécrits : ask_ai() et ask_ai_json().
"""
import json
import httpx
from app.config import GEMINI_API_KEY, GEMINI_MODEL

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{{model}}:generateContent"


async def ask_ai(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str:
    """Appelle Gemini et retourne le texte brut de la réponse."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY manquante dans les variables d'environnement")

    url = GEMINI_URL.format(model=GEMINI_MODEL)
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    try:
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        return ""


async def ask_ai_json(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> dict:
    """Variante qui force une réponse JSON stricte et la parse."""
    strict_system = (
        system_prompt
        + "\n\nIMPORTANT: réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, "
        "sans balises markdown, sans ```."
    )
    raw = await ask_ai(strict_system, user_prompt, max_tokens=max_tokens)
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


