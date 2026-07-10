"""
10 agents directionnels + 1 agent Risque (indépendant, peut bloquer un signal).
Chaque agent directionnel reçoit le même contexte de marché, dont l'analyse
des mèches (wicks) des 3 dernières bougies, pour mieux juger le timing
d'entrée (rejet de prix = mèche longue, continuation = mèche courte).
"""
import asyncio
from app.claude_client import ask_claude_json

WICK_CONTEXT_INSTRUCTION = """
Analyse aussi les mèches (wicks) des 3 dernières bougies fournies dans candles :
- Une longue mèche haute (upper_wick grand vs body) = rejet du haut, pression vendeuse, signal
  potentiel de retournement baissier ou d'épuisement haussier.
- Une longue mèche basse (lower_wick grand vs body) = rejet du bas, pression acheteuse, signal
  potentiel de retournement haussier ou d'épuisement baissier.
- Des mèches courtes des deux côtés avec un grand corps = mouvement directionnel fort, continuation probable.
- Compare la mèche de la bougie la plus récente à celle des 2 précédentes pour juger si le mouvement
  s'essouffle (mèches qui s'allongent contre la tendance) ou s'accélère (corps qui grossit, mèches courtes).
Utilise cette lecture pour affiner ton TIMING d'entrée, pas seulement la direction.
"""

RESPONSE_FORMAT = """
Réponds en JSON strict avec ces clés :
{
  "vote": "achat" | "vente" | "neutre",
  "confiance": 0-100,
  "raison": "1-2 phrases concises en français",
  "lecture_meches": "1 phrase sur ce que montrent les mèches récentes"
}
"""

AGENTS = [
    {
        "id": "tendance",
        "name": "Agent Tendance",
        "system": "Tu es un analyste spécialisé dans la tendance générale (moyennes mobiles, structure de marché, higher highs/lows) sur l'or (XAUUSD)."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
    {
        "id": "rsi",
        "name": "Agent RSI",
        "system": "Tu es un analyste spécialisé dans le RSI (surachat/survente, divergences) sur l'or (XAUUSD)."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
    {
        "id": "macd",
        "name": "Agent MACD",
        "system": "Tu es un analyste spécialisé dans le MACD (croisements, histogramme, momentum) sur l'or (XAUUSD)."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
    {
        "id": "support_resistance",
        "name": "Agent Support/Résistance",
        "system": "Tu es un analyste spécialisé dans les niveaux de support/résistance et les zones de liquidité sur l'or (XAUUSD)."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
    {
        "id": "price_action",
        "name": "Agent Price Action",
        "system": "Tu es un analyste spécialisé en price action pur (structure de bougies, patterns d'engulfing, pin bars, rejets de mèche) sur l'or (XAUUSD). C'est TOI le spécialiste principal des mèches."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
    {
        "id": "volatilite",
        "name": "Agent Volatilité (ATR/Bandes de Bollinger)",
        "system": "Tu es un analyste spécialisé dans la volatilité (ATR, largeur des bandes de Bollinger, squeeze) sur l'or (XAUUSD)."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
    {
        "id": "volume",
        "name": "Agent Volume",
        "system": "Tu es un analyste spécialisé dans le volume (pics de volume, volume vs prix, absorption) sur l'or (XAUUSD)."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
    {
        "id": "fibonacci",
        "name": "Agent Fibonacci",
        "system": "Tu es un analyste spécialisé dans les retracements et extensions de Fibonacci sur l'or (XAUUSD)."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
    {
        "id": "sentiment_macro",
        "name": "Agent Sentiment Macro",
        "system": "Tu es un analyste spécialisé dans le contexte macro qui influence l'or (DXY, taux, risk-on/risk-off) déduit des mouvements de prix fournis, sur l'or (XAUUSD)."
        + WICK_CONTEXT_INSTRUCTION + RESPONSE_FORMAT,
    },
]

RISK_AGENT = {
    "id": "risque",
    "name": "Agent Risque",
    "system": """Tu es le gardien du risque. Tu ne votes PAS sur la direction du marché.
Ton rôle : évaluer si le ratio risque/rendement du trade proposé (entrée, stop loss, take profit)
est sain, en tenant compte de la volatilité récente (ATR, taille des mèches) sur l'or (XAUUSD).
Réponds en JSON strict :
{
  "approuve": true | false,
  "ratio_risque_rendement": nombre,
  "raison": "1-2 phrases concises en français"
}""",
}


def _build_user_prompt(market_data: dict) -> str:
    return f"""Données de marché XAUUSD (or) reçues de TradingView :
{market_data}

Analyse et donne ton vote selon ton domaine d'expertise."""


async def run_agent(agent: dict, market_data: dict) -> dict:
    try:
        result = await ask_claude_json(agent["system"], _build_user_prompt(market_data))
        result["agent_id"] = agent["id"]
        result["agent_name"] = agent["name"]
        return result
    except Exception as e:
        return {
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "vote": "neutre",
            "confiance": 0,
            "raison": f"Erreur agent : {e}",
            "lecture_meches": "",
        }


async def run_risk_agent(market_data: dict, proposed_trade: dict) -> dict:
    prompt = f"""Données de marché XAUUSD :
{market_data}

Trade proposé :
{proposed_trade}

Évalue le ratio risque/rendement."""
    try:
        result = await ask_claude_json(RISK_AGENT["system"], prompt)
        result["agent_id"] = "risque"
        result["agent_name"] = RISK_AGENT["name"]
        return result
    except Exception as e:
        return {
            "agent_id": "risque",
            "agent_name": RISK_AGENT["name"],
            "approuve": False,
            "ratio_risque_rendement": 0,
            "raison": f"Erreur agent risque : {e}",
        }


async def run_all_agents(market_data: dict) -> list:
    """Lance les 9 agents directionnels en parallèle."""
    tasks = [run_agent(agent, market_data) for agent in AGENTS]
    return await asyncio.gather(*tasks)


def aggregate_votes(agent_results: list) -> dict:
    achat = sum(1 for r in agent_results if r.get("vote") == "achat")
    vente = sum(1 for r in agent_results if r.get("vote") == "vente")
    neutre = sum(1 for r in agent_results if r.get("vote") == "neutre")
    total = len(agent_results)

    direction = "neutre"
    if achat > vente and achat >= vente + 2:
        direction = "achat"
    elif vente > achat and vente >= achat + 2:
        direction = "vente"

    avg_confidence = 0
    matching = [r for r in agent_results if r.get("vote") == direction]
    if matching:
        avg_confidence = sum(r.get("confiance", 0) for r in matching) / len(matching)

    return {
        "direction": direction,
        "achat": achat,
        "vente": vente,
        "neutre": neutre,
        "total": total,
        "confiance_moyenne": round(avg_confidence, 1),
    }
