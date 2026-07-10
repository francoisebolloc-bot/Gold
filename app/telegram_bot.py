"""
Gestion des abonnés Telegram et des envois.
Multi-utilisateurs : chaque personne qui fait /start est ajoutée, /stop la retire.
Stockage persistant dans un fichier JSON (nécessite un Volume Railway sur /data).
"""
import json
import os
import httpx
from app.config import TELEGRAM_BOT_TOKEN, SUBSCRIBERS_FILE

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _ensure_dir():
    d = os.path.dirname(SUBSCRIBERS_FILE)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def load_subscribers() -> set:
    _ensure_dir()
    if not os.path.exists(SUBSCRIBERS_FILE):
        return set()
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, FileNotFoundError):
        return set()


def save_subscribers(subs: set):
    _ensure_dir()
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subs), f)


def add_subscriber(chat_id: int):
    subs = load_subscribers()
    subs.add(chat_id)
    save_subscribers(subs)


def remove_subscriber(chat_id: int):
    subs = load_subscribers()
    subs.discard(chat_id)
    save_subscribers(subs)


async def send_message(chat_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        return resp.json()


async def broadcast(text: str, reply_markup: dict = None):
    """Envoie un message à tous les abonnés. Retire automatiquement ceux qui ont bloqué le bot."""
    subs = load_subscribers()
    dead = []
    for chat_id in subs:
        try:
            result = await send_message(chat_id, text, reply_markup)
            if not result.get("ok") and result.get("error_code") in (403, 400):
                dead.append(chat_id)
        except Exception:
            continue
    if dead:
        for chat_id in dead:
            subs.discard(chat_id)
        save_subscribers(subs)


async def handle_update(update: dict):
    """Traite une mise à jour Telegram (message entrant)."""
    message = update.get("message") or update.get("callback_query", {}).get("message")
    if not message:
        return
    chat_id = message["chat"]["id"]

    if "callback_query" in update:
        await handle_callback(update["callback_query"])
        return

    text = (update.get("message", {}).get("text") or "").strip()

    if text == "/start":
        add_subscriber(chat_id)
        await send_message(
            chat_id,
            "✅ <b>Inscription confirmée.</b>\n\n"
            "Tu recevras désormais les signaux de trading sur l'or (XAUUSD) générés par "
            "nos 9 agents d'analyse + agent risque, propulsés par Gemini AI (gratuit) et TradingView.\n\n"
            "Commandes disponibles :\n"
            "/stop — se désabonner\n"
            "/status — voir ton statut d'abonnement",
        )
    elif text == "/stop":
        remove_subscriber(chat_id)
        await send_message(chat_id, "🛑 Tu es désabonné. Envoie /start pour te réinscrire à tout moment.")
    elif text == "/status":
        subs = load_subscribers()
        state = "abonné ✅" if chat_id in subs else "non abonné ❌"
        await send_message(chat_id, f"Statut : {state}")
    else:
        await send_message(chat_id, "Commandes disponibles : /start, /stop, /status")


async def handle_callback(callback_query: dict):
    """Gère les clics sur les boutons inline (ex: confirmer un trade)."""
    from app.trade_manager import confirm_trade  # import local pour éviter la boucle d'import

    chat_id = callback_query["message"]["chat"]["id"]
    data = callback_query.get("data", "")
    callback_id = callback_query["id"]

    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_id})

    if data.startswith("confirm_trade:"):
        trade_id = data.split(":", 1)[1]
        await confirm_trade(trade_id, chat_id)
