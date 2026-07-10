"""
Gère le cycle de vie d'un trade Gold (XAUUSD) :

1. Un signal fort (consensus des 9 agents + validation Agent Risque) crée un trade "proposé".
2. Le message est diffusé à tous les abonnés avec un bouton "✅ Confirmer / Suivre ce trade".
3. Seuls les abonnés qui cliquent sont ajoutés à la liste de suivi de CE trade.
4. Le script Pine léger (live_price.pine) envoie le prix en direct toutes les X secondes
   à /webhook/live/{secret} tant qu'un trade est actif ; l'Agent Suivi (via Gemini) commente
   la progression et alerte en cas d'invalidation ou d'atteinte du take profit / stop loss.
"""
import json
import os
import time
import uuid
from app.config import TRADES_FILE
from app.gemini_client import ask_ai
from app.telegram_bot import send_message, broadcast, load_subscribers

STATUS_PROPOSED = "proposed"
STATUS_ACTIVE = "active"
STATUS_CLOSED = "closed"


def _ensure_dir():
    d = os.path.dirname(TRADES_FILE)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _load() -> dict:
    _ensure_dir()
    if not os.path.exists(TRADES_FILE):
        return {}
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save(trades: dict):
    _ensure_dir()
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)


def get_active_trade() -> dict | None:
    """Un seul trade actif à la fois sur le gold, pour garder le suivi simple et clair."""
    trades = _load()
    for t in trades.values():
        if t["status"] in (STATUS_PROPOSED, STATUS_ACTIVE):
            return t
    return None


async def synthesize_signal_message(direction: str, entry: float, stop_loss: float,
                                     take_profit: float, agent_results: list,
                                     risk_result: dict) -> str:
    """Fait rédiger par Gemini un message de signal clair pour Telegram."""
    votes_summary = "\n".join(
        f"- {r['agent_name']}: {r.get('vote')} ({r.get('confiance')}%) — {r.get('raison')}"
        for r in agent_results
    )
    prompt = f"""Rédige un message Telegram court, clair et professionnel (en français, avec emojis
sobres) annonçant un signal de trading sur l'OR (XAUUSD).

Direction : {direction}
Entrée : {entry}
Stop loss : {stop_loss}
Take profit : {take_profit}

Avis des agents :
{votes_summary}

Avis de l'agent risque : {risk_result.get('raison')} (ratio {risk_result.get('ratio_risque_rendement')})

Le message doit inclure : direction, niveaux (entrée/SL/TP), une synthèse en 2-3 phrases du
consensus des agents, et se terminer par une invitation à cliquer sur le bouton pour suivre le trade.
Pas de scoring/liste brute des 9 agents dans le message, juste une synthèse.
Précise que ce n'est pas un conseil financier et que chacun reste responsable de ses décisions."""
    return await ask_ai(
        "Tu rédiges des messages Telegram professionnels et concis pour un bot de signaux trading sur l'or.",
        prompt,
        max_tokens=500,
    )


async def create_trade(direction: str, entry: float, stop_loss: float, take_profit: float,
                        agent_results: list, risk_result: dict) -> dict:
    trade_id = str(uuid.uuid4())[:8]
    trade = {
        "id": trade_id,
        "symbol": "XAUUSD",
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "status": STATUS_PROPOSED,
        "created_at": time.time(),
        "followers": [],
        "last_update_ts": 0,
    }
    trades = _load()
    trades[trade_id] = trade
    _save(trades)

    message = await synthesize_signal_message(direction, entry, stop_loss, take_profit,
                                                agent_results, risk_result)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Confirmer / Suivre ce trade", "callback_data": f"confirm_trade:{trade_id}"}
        ]]
    }
    await broadcast(message, reply_markup=keyboard)
    return trade


async def confirm_trade(trade_id: str, chat_id: int):
    trades = _load()
    trade = trades.get(trade_id)
    if not trade:
        await send_message(chat_id, "Ce trade n'est plus disponible (déjà clôturé ou expiré).")
        return
    if chat_id not in trade["followers"]:
        trade["followers"].append(chat_id)
    trade["status"] = STATUS_ACTIVE
    _save(trades)
    await send_message(
        chat_id,
        f"📌 Trade #{trade_id} confirmé. Tu recevras désormais le suivi en direct "
        f"(prix, invalidation, TP/SL) jusqu'à sa clôture.",
    )


async def _write_followup(trade: dict, current_price: float, note: str) -> str:
    prompt = f"""Trade en cours sur l'or (XAUUSD) :
Direction: {trade['direction']}, Entrée: {trade['entry']}, SL: {trade['stop_loss']}, TP: {trade['take_profit']}
Prix actuel : {current_price}
Contexte : {note}

Rédige un point de suivi TRÈS court (1-2 phrases) en français pour Telegram, avec emoji, sur l'évolution du trade."""
    return await ask_ai(
        "Tu rédiges des points de suivi de trade ultra-courts pour Telegram.", prompt, max_tokens=150
    )


async def _write_close_message(trade: dict, exit_price: float, reason: str) -> str:
    pnl_pips = exit_price - trade["entry"] if trade["direction"] == "achat" else trade["entry"] - exit_price
    prompt = f"""Clôture d'un trade sur l'or (XAUUSD) :
Direction: {trade['direction']}, Entrée: {trade['entry']}, Sortie: {exit_price}, Raison: {reason}
Résultat approximatif en points : {round(pnl_pips, 2)}

Rédige un message de clôture court et honnête (en français, avec emoji adapté au résultat) pour Telegram."""
    return await ask_ai(
        "Tu rédiges des messages de clôture de trade honnêtes et concis pour Telegram.", prompt, max_tokens=200
    )


async def update_live_price(current_price: float):
    """Appelé à chaque tick reçu de live_price.pine. Gère l'invalidation, le TP/SL, et un point de suivi périodique."""
    trade = get_active_trade()
    if not trade or trade["status"] != STATUS_ACTIVE:
        return

    hit_tp = (
        (trade["direction"] == "achat" and current_price >= trade["take_profit"]) or
        (trade["direction"] == "vente" and current_price <= trade["take_profit"])
    )
    hit_sl = (
        (trade["direction"] == "achat" and current_price <= trade["stop_loss"]) or
        (trade["direction"] == "vente" and current_price >= trade["stop_loss"])
    )

    if hit_tp or hit_sl:
        reason = "Take profit atteint 🎯" if hit_tp else "Stop loss touché 🛑"
        message = await _write_close_message(trade, current_price, reason)
        for chat_id in trade["followers"]:
            await send_message(chat_id, message)
        trades = _load()
        trades[trade["id"]]["status"] = STATUS_CLOSED
        trades[trade["id"]]["closed_at"] = time.time()
        trades[trade["id"]]["exit_price"] = current_price
        _save(trades)
        return

    # Point de suivi périodique (max 1 toutes les 10 minutes pour ne pas spammer)
    now = time.time()
    if now - trade.get("last_update_ts", 0) > 600:
        note = "Suivi périodique, aucun niveau clé atteint pour le moment."
        message = await _write_followup(trade, current_price, note)
        for chat_id in trade["followers"]:
            await send_message(chat_id, message)
        trades = _load()
        trades[trade["id"]]["last_update_ts"] = now
        _save(trades)
