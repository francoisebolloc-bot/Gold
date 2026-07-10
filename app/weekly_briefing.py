"""
Génère un aperçu hebdomadaire du marché de l'or (XAUUSD), envoyé :
1. Juste après qu'un nouvel abonné fasse /start (mise en contexte immédiate)
2. Automatiquement chaque semaine à tous les abonnés (voir scheduler dans main.py)
"""
import json
import os
import time
from app.gemini_client import ask_ai
from app.config import TRADES_FILE

WEEKLY_STATE_FILE = os.path.join(os.path.dirname(TRADES_FILE) or "/data", "weekly_briefing_state.json")

BRIEFING_SYSTEM = """Tu es un analyste senior spécialisé sur l'or (XAUUSD). Tu rédiges un aperçu
hebdomadaire court et professionnel pour les abonnés d'un bot Telegram de signaux de trading.

Structure attendue (en français, avec emojis sobres, 150-200 mots maximum) :
- Contexte macro général qui influence l'or actuellement (taux, dollar, tensions, inflation — de façon
  générale et prudente, sans invenir de chiffres précis que tu ne connais pas avec certitude)
- Ce à quoi les traders sur l'or doivent faire attention cette semaine (niveaux clés à surveiller,
  volatilité attendue autour d'annonces économiques majeures type Fed, emploi US, inflation)
- Un ton posé, pédagogique, jamais promotionnel ni alarmiste

Termine TOUJOURS par : "Rappel : ceci est une analyse générale, pas un conseil financier personnalisé."
Ne donne AUCUN prix cible précis ni recommandation d'achat/vente ferme dans ce message — c'est un
contexte général, pas un signal (les signaux de trade arrivent séparément, avec confirmation)."""


async def generate_weekly_outlook() -> str:
    prompt = "Rédige l'aperçu hebdomadaire du marché de l'or (XAUUSD) pour cette semaine."
    return await ask_ai(BRIEFING_SYSTEM, prompt, max_tokens=400)


def _load_state() -> dict:
    if not os.path.exists(WEEKLY_STATE_FILE):
        return {}
    try:
        with open(WEEKLY_STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save_state(state: dict):
    d = os.path.dirname(WEEKLY_STATE_FILE)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    with open(WEEKLY_STATE_FILE, "w") as f:
        json.dump(state, f)


def current_iso_week() -> str:
    t = time.gmtime()
    return time.strftime("%G-W%V", t)


def already_sent_this_week() -> bool:
    state = _load_state()
    return state.get("last_week_sent") == current_iso_week()


def mark_sent_this_week():
    _save_state({"last_week_sent": current_iso_week()})
