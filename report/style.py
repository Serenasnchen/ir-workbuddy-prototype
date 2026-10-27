"""Shared visual identity for report figures (kept in sync with the war-room HTML)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
font_manager.fontManager.addfont(FONT_PATH)
font_manager.fontManager.addfont(FONT_BOLD)
FAMILY = font_manager.FontProperties(fname=FONT_PATH).get_name()

# Palette: ink navy for structure, one blue accent for "our" choice, amber for attention,
# brick red for failures/mismatches, and a cool grey ramp for everything else.
INK = "#1B2433"
BLUE = "#2459D6"
BLUE_SOFT = "#DCE5FA"
AMBER = "#C98A1B"
RED = "#B8432F"
GREEN = "#2F7D5B"
GREY_1 = "#4A5568"
GREY_2 = "#8A94A6"
GREY_3 = "#C9D0DB"
GREY_4 = "#EEF1F5"
PAPER = "#FFFFFF"


def setup():
    plt.rcParams.update({
        "font.family": FAMILY,
        "font.size": 10,
        "axes.unicode_minus": False,
        "axes.edgecolor": GREY_3,
        "axes.labelcolor": GREY_1,
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "axes.titlecolor": INK,
        "xtick.color": GREY_1,
        "ytick.color": GREY_1,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.dpi": 220,
        "savefig.bbox": "tight",
    })


def source_note(fig, text, y=-0.02):
    fig.text(0.01, y, text, fontsize=7.5, color=GREY_2, ha="left", va="top")
