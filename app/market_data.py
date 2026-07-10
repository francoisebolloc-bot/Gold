"""
Source de données de marché gratuite et sans clé API : Yahoo Finance (ticker
GC=F, futures Gold COMEX), via son endpoint "chart" non-officiel mais public
et largement utilisé.

Architecture en 2 vitesses pour suivre le marché au plus près sans rien payer :
- Une boucle légère (_market_data_refresh_loop) rafraîchit un buffer en mémoire
  toutes les MARKET_DATA_REFRESH_INTERVAL_SECONDS (quelques secondes) : c'est
  un simple appel HTTP, ça ne coûte rien et peut tourner très fréquemment.
- Les agents (Gemini) restent throttlés à un intervalle plus large côté
  main.py, car CE sont les appels IA qui coûtent cher (quota), pas la lecture
  du prix. Résultat : à chaque fois que les agents analysent, ils lisent
  toujours la donnée la plus fraîche possible dans le buffer, sans attendre
  un nouvel appel réseau.
"""
import time
import asyncio
import logging
import httpx
from app.config import MARKET_DATA_REFRESH_INTERVAL_SECONDS

logger = logging.getLogger("gold-bot")

YF_SYMBOL = "GC=F"  # Gold futures COMEX, suivi de très près XAUUSD
YF_URL = f"https://query1.finance.yahoo.com/v8/finance/chart/{YF_SYMBOL}"
YF_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; gold-bot/1.0)"}

_cache_candles: list[dict] = []
_cache_updated_at: float = 0.0
_cache_lock = asyncio.Lock()


async def _fetch_yahoo_candles(interval: str = "1m", range_: str = "1d") -> list[dict]:
    """Interroge Yahoo Finance directement (sans passer par le cache).
    Retourne les bougies {open, high, low, close}, de la plus ancienne à la
    plus récente."""
    params = {"interval": interval, "range": range_}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(YF_URL, params=params, headers=YF_HEADERS)
        resp.raise_for_status()
        data = resp.json()

    result = (data.get("chart") or {}).get("result")
    if not result:
        raise RuntimeError("Yahoo Finance: aucune donnée retournée pour GC=F")

    result = result[0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]

    candles = []
    for i in range(len(timestamps)):
        o, h, l, c = quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i]
        if None in (o, h, l, c):
            continue  # bougie incomplète (marché fermé / donnée manquante)
        candles.append({"open": float(o), "high": float(h), "low": float(l), "close": float(c)})
    return candles


async def _refresh_cache():
    global _cache_candles, _cache_updated_at
    candles = await _fetch_yahoo_candles()
    if len(candles) >= 15:
        async with _cache_lock:
            _cache_candles = candles
            _cache_updated_at = time.monotonic()


async def market_data_refresh_loop():
    """Boucle de fond : garde le buffer de bougies à jour en continu, pour
    que les agents lisent toujours une donnée fraîche sans latence d'appel
    réseau au moment de l'analyse."""
    while True:
        try:
            await _refresh_cache()
        except Exception:
            logger.exception("market_data_refresh_loop: échec du rafraîchissement Yahoo Finance")
        await asyncio.sleep(MARKET_DATA_REFRESH_INTERVAL_SECONDS)


async def _get_cached_candles(min_needed: int = 15) -> list[dict]:
    """Retourne le buffer s'il est suffisant, sinon fait un fetch direct de
    secours (ex: tout premier appel, avant que la boucle de fond ait tourné)."""
    async with _cache_lock:
        candles = list(_cache_candles)
    if len(candles) >= min_needed:
        return candles
    # Filet de sécurité : pas encore de cache exploitable, on interroge directement.
    candles = await _fetch_yahoo_candles()
    if len(candles) < min_needed:
        raise RuntimeError("Pas assez de bougies renvoyées par Yahoo Finance pour calculer les indicateurs")
    return candles


async def fetch_recent_candles(interval: str = "1min", outputsize: int = 30) -> list[dict]:
    """Retourne les dernières bougies (depuis le buffer en mémoire), de la
    plus ancienne à la plus récente."""
    candles = await _get_cached_candles(min_needed=15)
    return candles[-outputsize:]


async def fetch_current_price() -> float:
    """Dernier prix connu (depuis le buffer, léger et instantané)."""
    candles = await _get_cached_candles(min_needed=1)
    return candles[-1]["close"]


def compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """RSI classique (moyenne mobile simple des gains/pertes)."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[-i] - closes[-i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_atr(candles: list[dict], period: int = 14) -> float | None:
    """Average True Range, sur les 'period' dernières bougies."""
    if len(candles) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(candles)):
        high, low = candles[i]["high"], candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    return round(sum(true_ranges[-period:]) / period, 4)


async def build_market_snapshot(interval: str = "1min", outputsize: int = 30) -> dict:
    """Construit un snapshot à partir du buffer en mémoire (donc quasi
    instantané, pas d'appel réseau bloquant dans le chemin critique) :
    open/high/low/close de la dernière bougie + rsi + atr + closes récents."""
    candles = await _get_cached_candles(min_needed=15)
    candles = candles[-outputsize:]

    last = candles[-1]
    closes = [c["close"] for c in candles]
    snapshot = dict(last)
    snapshot["rsi"] = compute_rsi(closes)
    snapshot["atr"] = compute_atr(candles)
    snapshot["recent_closes"] = closes[-11:-1]
    return snapshot
