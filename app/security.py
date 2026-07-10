"""
2 agents de sécurité, indépendants des agents de trading :

1. Agent Anti-Manipulation (via Gemini) : vérifie que les données reçues du
   webhook TradingView sont cohérentes (pas de valeurs aberrantes, pas de prix
   qui saute anormalement), pour éviter qu'une donnée corrompue ou une fausse
   alerte ne déclenche un signal envoyé à tous les abonnés.

2. Agent Anti-Abus (local, sans IA) : protège les endpoints publics
   (webhook TradingView, webhook Telegram, /start) contre le spam et le
   brute-force, avec rate limiting simple par clé/IP/chat_id en mémoire.
"""
import time
from collections import defaultdict, deque
from app.gemini_client import ask_ai_json

# ---------------------------------------------------------------------------
# Agent 1 : Anti-Manipulation (cohérence des données de marché)
# ---------------------------------------------------------------------------

ANTI_MANIPULATION_SYSTEM = """Tu es un agent de sécurité pour un bot de trading sur l'or (XAUUSD).
Ton unique rôle : détecter si les données de marché reçues semblent incohérentes, corrompues,
ou manipulées (ex: prix aberrant par rapport à la volatilité normale de l'or, valeurs négatives,
RSI hors de 0-100, incohérence entre high/low/open/close, saut de prix irréaliste entre 2 bougies).
Tu ne juges PAS la direction du marché, seulement la cohérence technique des données.
Réponds en JSON strict :
{
  "coherent": true | false,
  "raison": "1 phrase en français expliquant pourquoi"
}"""


async def check_data_integrity(market_data: dict) -> dict:
    prompt = f"Données reçues du webhook TradingView à vérifier :\n{market_data}"
    try:
        result = await ask_ai_json(ANTI_MANIPULATION_SYSTEM, prompt, max_tokens=200)
        return result
    except Exception as e:
        # En cas d'échec de l'agent de sécurité lui-même, on bloque par prudence
        return {"coherent": False, "raison": f"Agent anti-manipulation indisponible : {e}"}


def sanity_check_fields(market_data: dict) -> tuple[bool, str]:
    """Vérification locale rapide, avant même d'appeler Gemini (coûte 0 appel API)."""
    try:
        high = float(market_data.get("high", 0))
        low = float(market_data.get("low", 0))
        open_ = float(market_data.get("open", 0))
        close = float(market_data.get("close", 0))
    except (TypeError, ValueError):
        return False, "Champs de prix manquants ou non numériques"

    if high < low:
        return False, "high < low, données incohérentes"
    if not (low <= open_ <= high and low <= close <= high):
        return False, "open/close hors de la fourchette high/low"
    if low <= 0 or high <= 0:
        return False, "Prix négatif ou nul"

    rsi = market_data.get("rsi")
    if rsi is not None:
        try:
            rsi_v = float(rsi)
            if not (0 <= rsi_v <= 100):
                return False, "RSI hors de la plage 0-100"
        except (TypeError, ValueError):
            return False, "RSI non numérique"

    return True, "ok"


# ---------------------------------------------------------------------------
# Agent 2 : Anti-Abus / Rate limiting (local, sans appel IA)
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            return False
        q.append(now)
        return True


# Webhook TradingView : max 1 alerte toutes les 5 secondes par secret (anti-flood)
webhook_limiter = RateLimiter(max_calls=1, window_seconds=5)

# Analyse complète des 9 agents sur bougie en direct (non close) : throttlée, coûte cher en appels Gemini
from app.config import LIVE_ANALYSIS_INTERVAL_SECONDS
live_analysis_limiter = RateLimiter(max_calls=1, window_seconds=LIVE_ANALYSIS_INTERVAL_SECONDS)

# Telegram : un utilisateur ne peut pas spammer /start plus de 5 fois / minute
telegram_limiter = RateLimiter(max_calls=5, window_seconds=60)

# Webhook Telegram global : anti-flood brut
telegram_webhook_limiter = RateLimiter(max_calls=20, window_seconds=10)
