"""Draw docs/architecture.png: the AgentTrace flow in one picture. Regenerate with:

    uv run --with matplotlib python scripts/make_architecture.py
"""
from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture.png"
INK = "#26303B"

fig = Figure(figsize=(17, 8.6))
ax = fig.add_subplot()
ax.set_xlim(0, 200)
ax.set_ylim(0, 94)
ax.axis("off")


def box(x, y, w, h, title, subtitle, fill, edge, dashed=False):
    """One labelled box: a bold title and a short grey subtitle."""
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.5", fc=fill, ec=edge, lw=2.2,
                                ls="--" if dashed else "-"))
    ax.text(x + w / 2, y + h * 0.62, title, ha="center", va="center", fontsize=14.5, fontweight="bold", color=INK)
    ax.text(x + w / 2, y + h * 0.28, subtitle, ha="center", va="center", fontsize=11, color="#4B5563")


def arrow(start, end, both=False):
    style = "<|-|>" if both else "-|>"
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=22, lw=2.4, color=INK,
                                 shrinkA=0, shrinkB=0))


def step(x, y, number, label, dx=0.0, dy=-3.6):
    """A numbered circle sitting on an arrow, with a short label."""
    ax.add_patch(Circle((x, y), 1.9, fc=INK, ec="white", lw=1.5, zorder=5))
    ax.text(x, y - 0.05, str(number), ha="center", va="center", fontsize=12, color="white", fontweight="bold",
            zorder=6)
    ax.text(x + dx, y + dy, label, ha="center", va="center", fontsize=10.5, color=INK)


ax.text(100, 89, "AgentTrace: how a recording flows", ha="center", va="center", fontsize=21, fontweight="bold",
        color=INK)

# ---- top row: where the MCP traffic goes
box(4, 54, 38, 22, "Agent or app", "your agent, Claude Desktop", "#EEF4FF", "#3B6FD4")
box(54, 54, 38, 22, "AgentTrace proxy", "records every MCP message", "#F3EEFF", "#7B4FD4")
box(104, 54, 38, 22, "WSO2 MCP gateway", "optional: auth, scopes, limits", "#FFF1E6", "#EA7A1F", dashed=True)
box(154, 54, 38, 22, "MCP server", "unchanged", "#E9F7EF", "#2E8B57")
arrow((42, 65), (54, 65))
step(48, 65, 1, "request", dy=3.8)
arrow((92, 65), (104, 65), both=True)
step(98, 65, 2, "forward\nand reply", dy=-4.6)
arrow((142, 65), (154, 65), both=True)

# ---- bottom row: where the recording goes
box(4, 8, 108, 22, "AgentTrace server", "receive  →  parse  →  save", "#EEF4FF", "#3B6FD4")
box(126, 8, 32, 22, "SQLite", "one file", "#E4F5EA", "#2E8B57")
box(170, 8, 26, 22, "You", "Web UI · CLI · API", "#FFF6CC", "#C9A400")

# spans from the three recorders go down into the server
arrow((22, 54), (22, 30))
step(22, 42, 3, "SDK spans", dx=8, dy=0)
arrow((73, 54), (73, 30))
step(73, 42, 3, "proxy spans", dx=9, dy=0)
arrow((108, 54), (108, 30))
step(108, 42, 3, "gateway spans (OTLP gRPC)", dx=19, dy=0)

arrow((112, 19), (126, 19))
step(119, 19, 4, "save", dy=3.8)
arrow((170, 19), (158, 19))
step(164, 19, 5, "read", dy=3.8)

ax.text(100, 1.8, "Recorders send OpenTelemetry spans; the trace id travels with each request, so the proxy and "
        "the gateway join into ONE trace.", ha="center", va="center", fontsize=11.5, color="#4B5563")

OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white", pad_inches=0.3)
print("wrote", OUT)
