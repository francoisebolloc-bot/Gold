# Gold Signals Bot

Bot de trading sur l'or (XAUUSD) : TradingView → 9 agents d'analyse Gemini AI (gratuit) + 1 agent Risque
+ 2 agents de sécurité → Telegram (multi-abonnés, confirmation et suivi live du trade).

## Architecture

```
TradingView (alerte bougie CLÔTURÉE)
   -> POST /webhook/{WEBHOOK_SECRET}
      -> Agent Anti-Manipulation (vérifie la cohérence des données)
      -> 9 agents directionnels (Gemini AI, en parallèle)
      -> Agent Risque (Gemini AI, peut bloquer le signal)
      -> Création du trade + diffusion Telegram à tous les abonnés

TradingView (bougie EN FORMATION, en continu)
   -> POST /webhook/live/{WEBHOOK_SECRET}
      -> Si un trade est actif  : suivi live (prix, invalidation, TP/SL, points d'étape)
      -> Si aucun trade actif   : les 9 agents + agent risque analysent la bougie en
                                   train de se former, pour détecter un setup fort en
                                   avance sans attendre la clôture (throttlé par
                                   LIVE_ANALYSIS_INTERVAL_SECONDS pour maîtriser le
                                   coût des appels API)

Abonné clique "Confirmer" sur Telegram
   -> POST /telegram/{TELEGRAM_WEBHOOK_SECRET}
      -> Ajouté à la liste de suivi de ce trade
```

Agent Anti-Abus : rate limiting local sur les 3 endpoints, sans appel IA.

## 1. Prérequis

- Un compte Railway avec un abonnement actif (déjà fait)
- Un bot Telegram créé via [@BotFather](https://t.me/BotFather) → tu récupères un `TELEGRAM_BOT_TOKEN`
- Une clé API Google Gemini gratuite (`GEMINI_API_KEY`)
- Ce repo poussé sur GitHub (privé) et connecté à ton projet Railway

## 2. Variables d'environnement (Railway → Settings → Variables)

**Ne mets jamais ces valeurs dans le code ou dans GitHub.** Uniquement dans Railway :

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Ta clé API Gemini |
| `TELEGRAM_BOT_TOKEN` | Le token donné par BotFather |
| `WEBHOOK_SECRET` | Chaîne aléatoire que tu inventes (ex: généré avec `openssl rand -hex 16`) |
| `TELEGRAM_WEBHOOK_SECRET` | Une **autre** chaîne aléatoire, différente de la précédente |
| `SUBSCRIBERS_FILE` | `/data/subscribers.json` |
| `TRADES_FILE` | `/data/trades.json` |
| `MIN_CONSENSUS` | `6` (nombre d'agents minimum d'accord sur 9 pour émettre un signal) |
| `LIVE_ANALYSIS_INTERVAL_SECONDS` | `20` (intervalle mini entre 2 analyses complètes sur bougie en direct — protège ton usage gratuit Gemini) |

## 3. Volume Railway (obligatoire)

Dans Railway → ton service → **Volumes** → ajoute un volume monté sur `/data`.
Sans ça, la liste des abonnés et les trades en cours sont perdus à chaque redéploiement.

## 4. Connecter Telegram à ton app (à faire toi-même, une seule fois)

Une fois le service Railway déployé, tu as une URL du type `https://ton-app.up.railway.app`.
Lance cette commande **toi-même**, dans un terminal, avec ton vrai token (jamais donné à Claude) :

```bash
curl -F "url=https://ton-app.up.railway.app/telegram/TON_TELEGRAM_WEBHOOK_SECRET" \
     "https://api.telegram.org/botTON_TELEGRAM_BOT_TOKEN/setWebhook"
```

Remplace `TON_TELEGRAM_WEBHOOK_SECRET` par la valeur exacte que tu as mise dans la variable
Railway `TELEGRAM_WEBHOOK_SECRET`, et `TON_TELEGRAM_BOT_TOKEN` par ton vrai token.

Vérifie ensuite avec :
```bash
curl "https://api.telegram.org/botTON_TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

## 5. Configurer TradingView

**Script 1 — bougie clôturée (`pinescript/alert.pine`)** : ouvre le code dans Pine Editor, ajoute-le
au graphique XAUUSD, puis crée une alerte :
- Déclenchement : **Once Per Bar Close**
- Webhook URL : `https://ton-app.up.railway.app/webhook/TON_WEBHOOK_SECRET`

**Script 2 — bougie en formation (`pinescript/live_price.pine`)** : ajoute-le aussi au graphique
XAUUSD (unité de temps courte, ex: 1 min), puis crée une 2e alerte :
- Déclenchement : **Once Per Bar** (surtout PAS "Once Per Bar Close" — c'est tout l'intérêt : suivre
  la bougie pendant qu'elle se forme)
- Webhook URL : `https://ton-app.up.railway.app/webhook/live/TON_WEBHOOK_SECRET`

Ce 2e script sert à deux choses selon le contexte : le suivi en direct d'un trade déjà actif, ET
la détection anticipée d'un signal par les 9 agents quand aucun trade n'est en cours — sans attendre
la clôture de bougie. Le serveur limite automatiquement la fréquence de ces analyses (variable
`LIVE_ANALYSIS_INTERVAL_SECONDS`) pour ne pas multiplier les appels Gemini à chaque tick.

## 6. Utilisation

- Quand quelqu'un envoie `/start` au bot Telegram, il reçoit dans l'ordre : un message de
  bienvenue, un aperçu du contexte du marché de l'or de la semaine, puis la confirmation
  qu'il est bien abonné.
- Ce même aperçu hebdomadaire est renvoyé automatiquement à **tous** les abonnés chaque
  lundi matin (à partir de 8h UTC) — un rappel de contexte avant les signaux de la semaine.
- Quand un signal fort est validé par les 9 agents + l'agent risque, un message est diffusé
  avec un bouton "✅ Confirmer / Suivre ce trade".
- Seuls ceux qui cliquent reçoivent le suivi en direct (progression, invalidation, clôture TP/SL).
- `/stop` désabonne, `/status` indique l'état actuel.

## 7. Vérification

`GET /health` indique si des variables d'environnement obligatoires sont manquantes.

## Avertissement

Ce bot fournit des signaux générés automatiquement à titre informatif. Ce n'est pas un conseil
financier. Chaque utilisateur reste responsable de ses décisions de trading.
