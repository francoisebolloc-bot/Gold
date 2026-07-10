"""
Source de données de marché gratuite, en remplacement de TradingView (dont les
webhooks nécessitent un abonnement payant).

Utilise l'API gratuite Twelve Data (https://twelvedata.com, clé gratuite sans
carte bancaire, 800 requêtes/jour, 8/minute sur le plan free) pour récupérer
les bougies XAU/USD et calcule localement les indicateurs (RSI, ATR) que les
agents Gemini attendent — exactement le même format que produisait le script
Pine côté TradingView.
"""
import httpx
from app.config import TWELVEDATA_API_KEY

BASE_URL = "https://api.twelvedata.com"
TD_SYMBOL = "XAU/USD"


async def fetch_recent_candles(interval: str = "1min", outputsize: int = 30) -> list[dict]:
    """Retourne les dernières bougies, de la plus ancienne à la plus récente.
    Chaque bougie : {"open", "high", "low", "close"} (floats)."""
    params = {
        "symbol": TD_SYMBOL,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/time_series", params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data: {data.get('message', 'erreur inconnue')}")

    values = data.get("values", [])
    candles = [
        {
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
        }
        for v in reversed(values)  # Twelve Data renvoie du plus récent au plus ancien
    ]
    return candles


async def fetch_current_price() -> float:
    """Récupère uniquement le dernier prix (léger, pour le suivi TP/SL d'un trade actif)."""
    params = {"symbol": TD_SYMBOL, "apikey": TWELVEDATA_API_KEY}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/price", params=params)
        resp.raise_for_status()
        data = resp.json()
    if "price" not in data:
        raise RuntimeError(f"Twelve Data: {data.get('message', 'prix indisponible')}")
    return float(data["price"])


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
    """Construit un dict au même format que celui qu'envoyait TradingView :
    open/high/low/close de la dernière bougie + rsi + atr calculés sur l'historique."""
    candles = await fetch_recent_candles(interval=interval, outputsize=outputsize)
    if len(candles) < 15:
        raise RuntimeError("Pas assez de bougies renvoyées par Twelve Data pour calculer les indicateurs")

    last = candles[-1]
    closes = [c["close"] for c in candles]
    snapshot = dict(last)
    snapshot["rsi"] = compute_rsi(closes)
    snapshot["atr"] = compute_atr(candles)
    return snapshot
