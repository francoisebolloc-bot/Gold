"""
Client centralisé pour tous les appels à l'IA — utilise Google Gemini (gratuit, sans carte).
Interface simple : ask_ai() et ask_ai_json().

Google retire/renomme régulièrement ses modèles, parfois sans préavis clair (ex.
gemini-2.5-flash-lite qui a renvoyé des 404 du jour au lendemain le 9 juillet 2026 alors
que sa date de retrait officielle était le 22 juillet 2026). Pour éviter que tout le bot
tombe en panne à chaque fois que Google change ses modèles, on essaie GEMINI_MODEL en
premier, puis une liste de secours dans l'ordre. Le premier qui répond avec succès (pas de
404) est utilisé pour l'appel.
"""
import logging
import json
import httpx
from app.config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger("gold-bot")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Modèles de secours essayés dans l'ordre si GEMINI_MODEL échoue avec un 404
# (modèle retiré/renommé côté Google). "gemini-flash-lite-latest" est un alias
# maintenu par Google qui pointe toujours vers un modèle Flash-Lite valide,
# donc il sert de filet de sécurité en dernier recours.
FALLBACK_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
]


async def ask_ai(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> str:
    """Appelle Gemini et retourne le texte brut de la réponse.

    Essaie GEMINI_MODEL, puis chaque modèle de FALLBACK_MODELS si le précédent
    renvoie 404 (modèle retiré/renommé), 429 (quota épuisé — les quotas gratuits
    Gemini sont appliqués par modèle, donc un autre modèle a de bonnes chances
    d'avoir encore du quota disponible) ou une erreur serveur 5xx. Seules les
    erreurs fatales et non liées au modèle (401/403 clé invalide, 400 requête
    malformée) sont relancées immédiatement sans tenter les fallbacks.
    """
    RETRYABLE_STATUS_CODES = {404, 429, 500, 502, 503, 504}

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY manquante dans les variables d'environnement")

    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
    }

    models_to_try = [GEMINI_MODEL] + [m for m in FALLBACK_MODELS if m != GEMINI_MODEL]
    last_error = None
    data = None

    async with httpx.AsyncClient(timeout=30) as client:
        for i, model in enumerate(models_to_try):
            url = GEMINI_URL.format(model=model)
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if i > 0:
                    logger.warning(
                        "gemini_client: modele '%s' indisponible, bascule reussie sur '%s'",
                        GEMINI_MODEL, model,
                    )
                break
            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code
                if status in RETRYABLE_STATUS_CODES and i < len(models_to_try) - 1:
                    logger.warning(
                        "gemini_client: modele '%s' indisponible (HTTP %s), "
                        "on essaie le suivant: '%s'", model, status, models_to_try[i + 1],
                    )
                    continue
                raise
        else:
            raise last_error

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


