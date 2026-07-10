"""
Configuration centralisée. TOUT vient des variables d'environnement Railway.
Aucun secret n'est jamais écrit en dur ici.
"""
import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Secret dans l'URL du webhook TradingView -> /webhook/{secret}
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# Fichier persistant (nécessite un Volume Railway monté sur /data)
SUBSCRIBERS_FILE = os.environ.get("SUBSCRIBERS_FILE", "/data/subscribers.json")
TRADES_FILE = os.environ.get("TRADES_FILE", "/data/trades.json")

# Symbole suivi (marché unique : Gold/XAUUSD)
SYMBOL = os.environ.get("SYMBOL", "XAUUSD")

# Nombre de votes directionnels minimum pour émettre un signal (sur 9, hors agent Risque)
MIN_CONSENSUS = int(os.environ.get("MIN_CONSENSUS", "6"))

# Intervalle minimum (secondes) entre 2 analyses complètes des agents sur la bougie en direct
# (évite d'appeler Claude 9 fois à chaque tick, qui coûterait très cher et n'a pas de sens).
LIVE_ANALYSIS_INTERVAL_SECONDS = int(os.environ.get("LIVE_ANALYSIS_INTERVAL_SECONDS", "20"))

REQUIRED_VARS = [
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "WEBHOOK_SECRET",
    "TELEGRAM_WEBHOOK_SECRET",
]


def check_config():
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    return missing
