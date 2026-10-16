"""Draw docs/architecture.png: the AgentTrace flow in one picture. Regenerate with:

    uv run --with matplotlib python scripts/make_architecture.py
"""
from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture.png"
INK = "#26303B"

fig = Figure(figsize=(16, 8.4))
ax = fig.add_subplot()
ax.set_xlim(0, 180)
ax.set_ylim(0, 94)
ax.axis("off")


def box(x, y, w, h, title, subtitle, fill, edge):
    """One labelled box: a bold title and a short grey subtitle."""
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.5", fc=fill, ec=edge, lw=2.2))
    ax.text(x + w / 2, y + h * 0.62, title, ha="center", va="center", fontsize=15, fontweight="bold", color=INK)
    ax.text(x + w / 2, y + h * 0.28, subtitle, ha="center", va="center", fontsize=11.5, color="#4B5563")


def arrow(start, end, both=False):
    style = "<|-|>" if both else "-|>"
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=22, lw=2.4, color=INK,
                                 shrinkA=0, shrinkB=0))


def step(x, y, number, label, label_dx=0.0, label_dy=-3.6):
    """A numbered circle sitting on an arrow, with a short label."""
    ax.add_patch(Circle((x, y), 1.9, fc=INK, ec="white", lw=1.5, zorder=5))
    ax.text(x, y - 0.05, str(number), ha="center", va="center", fontsize=12, color="white", fontweight="bold", zorder=6)
    ax.text(x + label_dx, y + label_dy, label, ha="center", va="center", fontsize=11, color=INK)


ax.text(90, 89, "AgentTrace: how a recording flows", ha="center", va="center", fontsize=21,
        fontweight="bold", color=INK)

# ---- top row: where the MCP traffic goes
box(6, 54, 44, 22, "Agent or app", "LangGraph agent, Claude Desktop", "#EEF4FF", "#3B6FD4")
box(68, 54, 44, 22, "Proxy", "records every MCP message", "#F3EEFF", "#7B4FD4")
box(130, 54, 44, 22, "MCP server", "unchanged", "#E9F7EF", "#2E8B57")
arrow((50, 65), (68, 65))
step(59, 65, 1, "request", label_dy=3.8)
arrow((112, 65), (130, 65), both=True)
step(121, 65, 2, "forward\nand reply", label_dy=-4.6)

# ---- bottom row: where the recording goes
box(6, 8, 94, 22, "AgentTrace server", "receive  →  parse  →  save", "#EEF4FF", "#3B6FD4")
box(116, 8, 28, 22, "SQLite", "one file", "#E4F5EA", "#2E8B57")
box(154, 8, 22, 22, "You", "CLI or API", "#FFF6CC", "#C9A400")

# spans from the agent's SDK and from the proxy go down into the server
arrow((18, 54), (18, 30))
step(18, 42, 3, "SDK spans", label_dx=8, label_dy=0)
arrow((90, 54), (90, 30))
step(90, 42, 3, "proxy spans", label_dx=9, label_dy=0)

arrow((100, 19), (116, 19))
step(108, 19, 4, "save", label_dy=3.8)
arrow((154, 19), (144, 19))
step(149, 19, 5, "read", label_dy=3.8)

ax.text(90, 1.8, "Both recorders send OpenTelemetry spans; the trace id travels with each request, "
        "so they join into ONE trace.", ha="center", va="center", fontsize=11.5, color="#4B5563")

OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white", pad_inches=0.3)
print("wrote", OUT)
