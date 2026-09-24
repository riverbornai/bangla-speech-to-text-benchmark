"""
Render the README charts from the published results CSVs.

Reads:  results/leaderboard_ci.csv, results/streaming_leaderboard_ci.csv,
        results/streaming_leaderboard.csv, results/by_domain.csv,
        results/streaming_by_domain.csv, results/cost.csv,
        results/streaming_cost.csv
Writes: results/plots/*.png

Usage:  python src/plot_results.py
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
PLOTS = os.path.join(RESULTS, "plots")

# Colours: each provider keeps one hue across every chart (batch and streaming
# alike), two fixed hues for the paired latency chart, and a warm light-to-dark
# ramp for the heatmaps (hotter = more errors).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
SEQ = ["#fff4d6", "#fed98e", "#fdb04f", "#f5813a", "#e3572b", "#b8321e", "#7f1d12"]

PROVIDER_COLOR = {
    "sarvam": "#eb6834",      # orange
    "soniox": "#4a3aa7",      # violet
    "deepgram": "#1baf7a",    # aqua
    "gemini": "#2a78d6",      # blue
    "elevenlabs": "#e87ba4",  # magenta
    "google": "#e34948",      # red
    "openai": "#008300",      # green
    "groq": "#eda100",        # yellow
}

NAMES = {
    "sarvam_saarika": "Sarvam\nsaarika:v2.5",
    "soniox": "Soniox\nstt-async-v5",
    "deepgram_nova3": "Deepgram\nnova-3",
    "gemini_25_flash": "Gemini\n2.5 Flash",
    "elevenlabs_scribe": "ElevenLabs\nScribe v1",
    "google_chirp2": "Google\nChirp 2",
    "openai_4o": "OpenAI\ngpt-4o-transcribe",
    "groq_whisper": "Groq\nWhisper large-v3",
    "soniox_rt_streaming": "Soniox\nstt-rt-v5",
    "sarvam_saaras_realtime_streaming": "Sarvam\nsaaras:v3-realtime",
    "deepgram_nova3_streaming": "Deepgram\nnova-3",
    "google_chirp2_streaming": "Google\nChirp 2",
    "openai_4o_streaming": "OpenAI\ngpt-4o-transcribe",
    "elevenlabs_scribe_streaming": "ElevenLabs\nScribe v2 Realtime",
    "gemini_25_flash_streaming": "Gemini 2.5 Flash\nLive",
}

DOMAINS = {
    "audio_books": "Audiobooks", "biography": "Biography",
    "celebrity_interview": "Celebrity interview", "class_lecture": "Class lecture",
    "documentary": "Documentary", "drama_series": "Drama series",
    "kid_cartoon": "Kids' cartoon", "kid_voice": "Kids' voices", "medicine": "Medicine",
    "parliament_speech": "Parliament", "political_talkshow": "Political talk show",
    "sports": "Sports", "television_news": "TV news",
}


# Label offsets (points) for scatter points whose default label would collide.
LABEL_OFFSET = {
    "gemini_25_flash": (8, -14),
    "gemini_25_flash_streaming": (-10, 8),
}


def label_at(ax, text, x, y, model):
    dx, dy = LABEL_OFFSET.get(model, (8, 4))
    ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", fontsize=9, color=INK,
                ha="right" if dx < 0 else "left")


def color(model: str) -> str:
    return PROVIDER_COLOR[model.split("_")[0]]


def short(model: str) -> str:
    return NAMES[model].split("\n")[0]


def style(ax, grid_axis="y"):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_2)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def figure(w, h):
    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    return fig, ax


def save(fig, name):
    os.makedirs(PLOTS, exist_ok=True)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, name), facecolor=SURFACE)
    plt.close(fig)
    print(f"wrote results/plots/{name}")


def pct(x, _=None):
    return f"{x:.0f}%"


def cer_bars(ci_csv, title, name):
    df = pd.read_csv(os.path.join(RESULTS, ci_csv)).sort_values("CER")
    x = np.arange(len(df))
    cer = df["CER"] * 100
    err = [cer - df["CER_ci_low"] * 100, df["CER_ci_high"] * 100 - cer]
    fig, ax = figure(12, 5)
    ax.bar(x, cer, width=0.55, color=[color(m) for m in df["model"]], zorder=2)
    ax.errorbar(x, cer, yerr=err, fmt="none", ecolor=INK_2, elinewidth=1.2, capsize=4, zorder=3)
    for i, (xi, v, hi) in enumerate(zip(x, cer, df["CER_ci_high"] * 100)):
        label = f"Best\n{v:.1f}%" if i == 0 else f"{v:.1f}%"
        ax.text(xi, hi + 0.8, label, ha="center", va="bottom", fontsize=9, color=INK,
                fontweight="bold" if i == 0 else "normal")
    ax.set_xticks(x, [NAMES[m] for m in df["model"]], fontsize=8)
    ax.yaxis.set_major_formatter(pct)
    ax.set_ylabel("Character error rate (lower is better)", color=INK_2, fontsize=10)
    ax.set_title(title, color=INK, fontsize=12, loc="left", pad=12)
    ax.set_ylim(0, (df["CER_ci_high"].max() * 100) * 1.15)
    style(ax)
    save(fig, name)


def cer_vs_cost(cost_csv, title, name):
    df = pd.read_csv(os.path.join(RESULTS, cost_csv))
    fig, ax = figure(9, 6)
    for _, r in df.iterrows():
        minimum = r["cost_type"] == "minimum"
        ax.scatter(r["list_usd_per_hour"], r["CER"] * 100, s=90, zorder=3,
                   facecolor=SURFACE if minimum else color(r["model"]), edgecolor=color(r["model"]),
                   linewidth=2)
        label = short(r["model"]) + (" (min. cost)" if minimum else "")
        label_at(ax, label, r["list_usd_per_hour"], r["CER"] * 100, r["model"])
    ax.set_xlabel("List price, USD per hour of audio (lower is better)", color=INK_2, fontsize=10)
    ax.set_ylabel("Character error rate (lower is better)", color=INK_2, fontsize=10)
    ax.yaxis.set_major_formatter(pct)
    ax.xaxis.set_major_formatter(lambda v, _: f"${v:.2f}")
    ax.set_xlim(0, df["list_usd_per_hour"].max() * 1.2)
    ax.set_ylim(0, df["CER"].max() * 100 * 1.12)
    ax.set_title(title + "\nBest value is bottom-left. Hollow marker = only a minimum cost is known.",
                 color=INK, fontsize=12, loc="left", pad=12)
    style(ax, grid_axis="both")
    save(fig, name)


def cer_vs_latency(name):
    lb = pd.read_csv(os.path.join(RESULTS, "streaming_leaderboard.csv"))
    fig, ax = figure(9, 6)
    ax.scatter(lb["finalization_p50_s"], lb["CER"] * 100, s=90, zorder=3,
               color=[color(m) for m in lb["model"]], edgecolor=SURFACE, linewidth=2)
    for _, r in lb.iterrows():
        label_at(ax, short(r["model"]), r["finalization_p50_s"], r["CER"] * 100, r["model"])
    ax.set_xlabel("Median time from end of speech to final transcript, seconds (lower is better)",
                  color=INK_2, fontsize=10)
    ax.set_ylabel("Character error rate (lower is better)", color=INK_2, fontsize=10)
    ax.yaxis.set_major_formatter(pct)
    ax.set_xlim(0, lb["finalization_p50_s"].max() * 1.15)
    ax.set_ylim(0, lb["CER"].max() * 100 * 1.12)
    ax.set_title("Streaming: accuracy vs. finalization delay\nBest is bottom-left.",
                 color=INK, fontsize=12, loc="left", pad=12)
    style(ax, grid_axis="both")
    save(fig, name)


def streaming_latency(name):
    lb = pd.read_csv(os.path.join(RESULTS, "streaming_leaderboard.csv")).sort_values("CER")
    x = np.arange(len(lb))
    w = 0.36
    fig, ax = figure(12, 5)
    fp = lb["first_partial_p50_s"]
    fin = lb["finalization_p50_s"]
    ax.bar(x - w / 2 - 0.01, fp.fillna(0), width=w, color=BLUE, label="First partial result (p50)", zorder=2)
    ax.bar(x + w / 2 + 0.01, fin, width=w, color=ORANGE, label="Final result after speech ends (p50)", zorder=2)
    for xi, a, b in zip(x, fp, fin):
        ax.text(xi - w / 2, (0 if pd.isna(a) else a) + 0.15, "n/a" if pd.isna(a) else f"{a:.1f}s",
                ha="center", va="bottom", fontsize=8, color=INK)
        ax.text(xi + w / 2, b + 0.15, f"{b:.1f}s", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(x, [NAMES[m] for m in lb["model"]], fontsize=8)
    ax.set_ylabel("Seconds (lower is better)", color=INK_2, fontsize=10)
    ax.set_title("Streaming latency (ordered by accuracy)", color=INK, fontsize=12, loc="left", pad=12)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    style(ax)
    save(fig, name)


def domain_heatmap(csv, title, name):
    df = pd.read_csv(os.path.join(RESULTS, csv)).set_index("model")
    df = df.loc[df.mean(axis=1).sort_values().index]
    data = df.to_numpy() * 100
    cmap = LinearSegmentedColormap.from_list("seq", SEQ)
    fig, ax = figure(12, 0.55 * len(df) + 2.6)
    im = ax.imshow(data, cmap=cmap, aspect="auto", vmin=0, vmax=min(80, np.nanmax(data)))
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data[i, j]
            dark_cell = v > (im.norm.vmax * 0.45)
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8,
                    color="#ffffff" if dark_cell else INK)
    ax.set_xticks(range(len(df.columns)), [DOMAINS[c] for c in df.columns], rotation=35,
                  ha="right", fontsize=9, color=INK_2)
    ax.set_yticks(range(len(df)), [NAMES[m].replace("\n", " ") for m in df.index], fontsize=9, color=INK_2)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cb.set_label("CER % (lower is better)", color=INK_2, fontsize=9)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=INK_2, labelsize=8)
    ax.set_title(title, color=INK, fontsize=12, loc="left", pad=12)
    save(fig, name)


def main():
    cer_bars("leaderboard_ci.csv", "Batch transcription: character error rate with 95% confidence intervals",
             "cer_batch.png")
    cer_bars("streaming_leaderboard_ci.csv", "Streaming transcription: character error rate with 95% confidence intervals",
             "cer_streaming.png")
    cer_vs_cost("cost.csv", "Batch: accuracy vs. price", "cer_vs_cost_batch.png")
    cer_vs_cost("streaming_cost.csv", "Streaming: accuracy vs. price", "cer_vs_cost_streaming.png")
    cer_vs_latency("cer_vs_latency_streaming.png")
    streaming_latency("latency_streaming.png")
    domain_heatmap("by_domain.csv", "Batch: character error rate (%) by domain", "cer_by_domain_batch.png")
    domain_heatmap("streaming_by_domain.csv", "Streaming: character error rate (%) by domain",
                   "cer_by_domain_streaming.png")


if __name__ == "__main__":
    main()
