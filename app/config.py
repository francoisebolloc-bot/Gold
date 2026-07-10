"""
Configuration centralisée. TOUT vient des variables d'environnement Railway.
Aucun secret n'est jamais écrit en dur ici.
"""
import os

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Secret dans l'URL du webhook TradingView -> /webhook/{secret}
# (conservé pour compatibilité si un jour un abonnement payant TradingView est ajouté,
# mais n'est plus la source de données principale — voir TWELVEDATA_API_KEY ci-dessous)
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# Source de données de marché gratuite (remplace TradingView, qui exige un plan payant
# pour les webhooks). Clé gratuite sans carte bancaire sur https://twelvedata.com
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY", "")

# Intervalle (secondes) entre 2 vérifications du prix en direct pour le suivi TP/SL
# d'un trade déjà actif (léger : un seul prix, pas d'indicateurs).
PRICE_TRACKING_INTERVAL_SECONDS = int(os.environ.get("PRICE_TRACKING_INTERVAL_SECONDS", "20"))

# Intervalle (secondes) entre 2 analyses complètes par les 9 agents quand aucun trade
# n'est actif (récupère l'historique de bougies + indicateurs, donc plus coûteux).
CANDLE_ANALYSIS_INTERVAL_SECONDS = int(os.environ.get("CANDLE_ANALYSIS_INTERVAL_SECONDS", "60"))

# Intervalle (secondes) entre 2 envois du graphique du marché aux abonnés,
# indépendamment de la détection d'un signal (suivi visuel continu).
CHART_BROADCAST_INTERVAL_SECONDS = int(os.environ.get("CHART_BROADCAST_INTERVAL_SECONDS", "900"))

# Fichier persistant (nécessite un Volume Railway monté sur /data)
SUBSCRIBERS_FILE = os.environ.get("SUBSCRIBERS_FILE", "/data/subscribers.json")
TRADES_FILE = os.environ.get("TRADES_FILE", "/data/trades.json")

# Symbole suivi (marché unique : Gold/XAUUSD)
SYMBOL = os.environ.get("SYMBOL", "XAUUSD")

# Nombre de votes directionnels minimum pour émettre un signal (sur 9, hors agent Risque)
MIN_CONSENSUS = int(os.environ.get("MIN_CONSENSUS", "6"))

# Intervalle minimum (secondes) entre 2 analyses complètes des agents sur la bougie en direct
# (évite d'appeler Gemini 9 fois à chaque tick, qui coûterait très cher et n'a pas de sens).
LIVE_ANALYSIS_INTERVAL_SECONDS = int(os.environ.get("LIVE_ANALYSIS_INTERVAL_SECONDS", "20"))

REQUIRED_VARS = [
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "TWELVEDATA_API_KEY",
]


def check_config():
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    return missing
