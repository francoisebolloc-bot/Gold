"""
Serveur principal FastAPI.

Routes :
- POST /webhook/{secret}          <- TradingView (alerte de clôture de bougie, XAUUSD)
- POST /webhook/live/{secret}     <- TradingView (prix en direct, script léger)
- POST /telegram/{secret}         <- Telegram (webhook des messages/commandes)
- GET  /health                    <- vérification Railway
"""
from fastapi import FastAPI, Request, HTTPException
import asyncio
from app.config import (
    WEBHOOK_SECRET, TELEGRAM_WEBHOOK_SECRET, MIN_CONSENSUS, check_config,
    PRICE_TRACKING_INTERVAL_SECONDS, CANDLE_ANALYSIS_INTERVAL_SECONDS,
    CHART_BROADCAST_INTERVAL_SECONDS,
)
from app.security import (
    check_data_integrity,
    sanity_check_fields,
    webhook_limiter,
    live_analysis_limiter,
    telegram_webhook_limiter,
)
from app.agents import run_all_agents, aggregate_votes, run_risk_agent
from app.trade_manager import create_trade, get_active_trade, update_live_price
from app.telegram_bot import handle_update, broadcast, broadcast_photo
from app.weekly_briefing import generate_weekly_outlook, already_sent_this_week, mark_sent_this_week
from app.market_data import build_market_snapshot, fetch_current_price, fetch_recent_candles
from app.chart import render_candlestick_chart

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gold-bot")

app = FastAPI(title="Gold Signals Bot")


async def _weekly_briefing_loop():
    """Vérifie chaque heure si c'est le moment d'envoyer le briefing hebdomadaire
    (une fois par semaine ISO, le lundi à partir de 8h UTC) à tous les abonnés."""
    while True:
        try:
            now = __import__("time").gmtime()
            is_monday_morning = now.tm_wday == 0 and now.tm_hour >= 8
            if is_monday_morning and not already_sent_this_week():
                outlook = await generate_weekly_outlook()
                await broadcast(f"📊 <b>Contexte de la semaine sur l'or</b>\n\n{outlook}")
                mark_sent_this_week()
        except Exception:
            pass  # Ne jamais casser le serveur pour un échec de briefing
        await asyncio.sleep(3600)


async def _price_tracking_loop():
    """Toutes les PRICE_TRACKING_INTERVAL_SECONDS : si un trade est actif, va chercher
    juste le dernier prix (léger) pour le suivi TP/SL en direct."""
    while True:
        try:
            if get_active_trade():
                price = await fetch_current_price()
                await update_live_price(price)
        except Exception:
            pass  # Un raté ponctuel de l'API ne doit jamais faire planter le bot
        await asyncio.sleep(PRICE_TRACKING_INTERVAL_SECONDS)


async def _candle_analysis_loop():
    """Toutes les CANDLE_ANALYSIS_INTERVAL_SECONDS : si aucun trade n'est actif, va
    chercher l'historique de bougies + indicateurs et fait voter les 9 agents,
    exactement comme le faisait auparavant le webhook TradingView."""
    while True:
        try:
            if not get_active_trade():
                logger.info("candle_analysis_loop: fetching market snapshot...")
                snapshot = await build_market_snapshot()
                logger.info("candle_analysis_loop: snapshot=%s", snapshot)
                result = await analyze_market_and_maybe_signal(snapshot)
                logger.info("candle_analysis_loop: result=%s", result)
        except Exception:
            logger.exception("candle_analysis_loop: échec du cycle d'analyse")
        await asyncio.sleep(CANDLE_ANALYSIS_INTERVAL_SECONDS)


async def _chart_broadcast_loop():
    """Toutes les CHART_BROADCAST_INTERVAL_SECONDS : envoie un graphique du marché
    aux abonnés, qu'un signal ait été détecté ou non — pour un suivi visuel continu
    même quand les agents ne trouvent pas de setup assez fort."""
    while True:
        try:
            candles = await fetch_recent_candles(outputsize=40)
            if candles:
                last = candles[-1]
                active = get_active_trade()
                if active:
                    statut = f"Trade en cours : {active['direction']} (entrée {active['entry']})"
                else:
                    statut = "Aucun signal fort actuellement, le bot continue de surveiller."
                caption = f"📈 <b>XAUUSD</b> — {last['close']:.2f}\n{statut}"
                png = render_candlestick_chart(candles, title="XAUUSD - 40 dernières bougies (1min)")
                await broadcast_photo(png, caption)
        except Exception:
            logger.exception("chart_broadcast_loop: échec de l'envoi du graphique")
        await asyncio.sleep(CHART_BROADCAST_INTERVAL_SECONDS)


@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(_weekly_briefing_loop())
    asyncio.create_task(_price_tracking_loop())
    asyncio.create_task(_candle_analysis_loop())
    asyncio.create_task(_chart_broadcast_loop())


@app.get("/health")
async def health():
    missing = check_config()
    return {"status": "ok" if not missing else "misconfigured", "missing_env_vars": missing}


async def analyze_market_and_maybe_signal(market_data: dict) -> dict:
    """Logique d'analyse partagée entre la bougie clôturée et la bougie en direct :
    vérifie l'intégrité des données, fait voter les 9 agents, fait valider le risque,
    et crée + diffuse un trade si le consensus est suffisant."""
    ok, reason = sanity_check_fields(market_data)
    if not ok:
        return {"status": "rejected", "reason": reason}

    integrity = await check_data_integrity(market_data)
    if not integrity.get("coherent", False):
        return {"status": "rejected", "reason": integrity.get("raison")}

    if get_active_trade():
        return {"status": "skipped", "reason": "Un trade est déjà actif sur XAUUSD"}

    agent_results = await run_all_agents(market_data)
    consensus = aggregate_votes(agent_results)

    if consensus["direction"] == "neutre" or max(consensus["achat"], consensus["vente"]) < MIN_CONSENSUS:
        return {"status": "no_signal", "consensus": consensus}

    entry = float(market_data.get("close", 0))
    atr = float(market_data.get("atr", entry * 0.003)) or entry * 0.003
    if consensus["direction"] == "achat":
        stop_loss = round(entry - 1.5 * atr, 2)
        take_profit = round(entry + 3 * atr, 2)
    else:
        stop_loss = round(entry + 1.5 * atr, 2)
        take_profit = round(entry - 3 * atr, 2)

    proposed_trade = {"direction": consensus["direction"], "entry": entry,
                       "stop_loss": stop_loss, "take_profit": take_profit}

    risk_result = await run_risk_agent(market_data, proposed_trade)
    if not risk_result.get("approuve", False):
        return {"status": "blocked_by_risk", "consensus": consensus, "risk": risk_result}

    trade = await create_trade(consensus["direction"], entry, stop_loss, take_profit,
                                agent_results, risk_result)
    return {"status": "signal_sent", "trade_id": trade["id"], "consensus": consensus}


@app.post("/webhook/{secret}")
async def tradingview_webhook(secret: str, request: Request):
    """Bougie CLÔTURÉE (alert.pine) : analyse complète systématique, toujours déclenchée."""
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Secret invalide")

    if not webhook_limiter.allow(secret):
        raise HTTPException(status_code=429, detail="Trop de requêtes")

    market_data = await request.json()
    return await analyze_market_and_maybe_signal(market_data)


@app.post("/webhook/live/{secret}")
async def tradingview_live_webhook(secret: str, request: Request):
    """Bougie EN FORMATION (live_price.pine), envoyée en continu.

    - Si un trade est actif : sert au suivi live (prix, TP/SL, points d'étape).
    - Si aucun trade n'est actif : les 9 agents + agent risque analysent la bougie en
      train de se former (via Gemini AI) pour détecter un setup fort en avance, sans
      attendre la clôture — mais throttlé (LIVE_ANALYSIS_INTERVAL_SECONDS) pour ne pas
      multiplier les appels Gemini à chaque tick.
    """
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Secret invalide")

    data = await request.json()

    active_trade = get_active_trade()
    if active_trade:
        try:
            price = float(data.get("close", data.get("price")))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Prix manquant ou invalide")
        await update_live_price(price)
        return {"status": "live_tracking_updated"}

    # Pas de trade actif : tentative d'analyse anticipée sur la bougie en formation
    if not live_analysis_limiter.allow(WEBHOOK_SECRET):
        return {"status": "throttled"}

    if "rsi" not in data and "macd" not in data:
        # Le tick ne contient que le prix (script minimal) : pas assez de données pour les agents
        return {"status": "insufficient_data_for_live_analysis"}

    result = await analyze_market_and_maybe_signal(data)
    result["source"] = "live_candle"
    return result


@app.post("/telegram/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if not TELEGRAM_WEBHOOK_SECRET or secret != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Secret invalide")

    if not telegram_webhook_limiter.allow("global"):
        raise HTTPException(status_code=429, detail="Trop de requêtes")

    update = await request.json()
    await handle_update(update)
    return {"status": "ok"}
