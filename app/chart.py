"""
Génère un graphique en chandelles (candlestick) du marché XAUUSD à partir de
l'historique de bougies, pour donner un suivi visuel sur Telegram même quand
aucun signal fort n'est déclenché.
"""
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render_candlestick_chart(candles: list[dict], title: str = "XAUUSD") -> bytes:
    """candles : liste de dicts {open, high, low, close}, du plus ancien au plus
    récent. Retourne les octets PNG du graphique."""
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    width = 0.6

    for i, c in enumerate(candles):
        up = c["close"] >= c["open"]
        color = "#1D9E75" if up else "#E24B4A"
        ax.plot([i, i], [c["low"], c["high"]], color=color, linewidth=1)
        lower = min(c["open"], c["close"])
        height = abs(c["close"] - c["open"]) or 0.0001
        ax.add_patch(plt.Rectangle((i - width / 2, lower), width, height, color=color))

    ax.set_title(title, fontsize=12)
    ax.set_xlim(-1, len(candles))
    ax.set_xticks([])
    ax.grid(True, axis="y", alpha=0.2)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
