# ruff: noqa: E501  (drawing script: long label strings are easier to read on one line)
"""Draw docs/architecture.png (the whole flow + code structure). Regenerate with:

    uv run --with matplotlib python scripts/make_architecture.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture.png"
INK = "#26303B"

fig, ax = plt.subplots(figsize=(20, 11.8))
ax.set_xlim(0, 200)
ax.set_ylim(-14, 112)
ax.axis("off")


def box(x, y, w, h, fc="white", ec=INK, lw=1.4, r=0.8, z=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, zorder=z))


def text(x, y, t, fs=9, bold=False, color=INK, ha="left", mono=False, z=6):
    ax.text(x, y, t, fontsize=fs, ha=ha, va="center", color=color, zorder=z, linespacing=1.5,
            fontweight="bold" if bold else "normal", family="monospace" if mono else None)


def arrow(p, q, style="-|>", lw=1.7, z=4):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=15, lw=lw, color=INK, zorder=z,
                                 shrinkA=0, shrinkB=0))


def line(xs, ys, lw=1.7):
    ax.plot(xs, ys, color=INK, lw=lw, zorder=4, solid_capstyle="round")


def num(x, y, n):
    ax.add_patch(Circle((x, y), 1.3, fc="#1F2937", ec="white", lw=1, zorder=8))
    ax.text(x, y - 0.05, str(n), ha="center", va="center", fontsize=9, color="white", fontweight="bold", zorder=9)


def label(x, y, t, fs=8.5):
    ax.text(x, y, t, ha="center", va="center", fontsize=fs, color=INK, zorder=7, linespacing=1.4,
            bbox=dict(fc="white", ec="none", pad=1.2))


ax.text(80, 109.5, "AgentTrace – backend architecture (flow and structure)", ha="center", va="center",
        fontsize=18, fontweight="bold", color=INK)

# ------------------------------------------------------------------ clients (left column)
text(6, 104.5, "WHO TALKS MCP", 9.5, True, "#4B5563")
box(6, 88, 42, 13, "#EEF4FF", "#3B6FD4", 1.8)
text(8, 98.2, "Your LangGraph agent", 10, True)
text(8, 93.6, "SDK:  init()  ·  proxy_server()\ntrace_tool_calls()", 8.6)
box(6, 70, 42, 14, "#F3F4F6", "#6B7280", 1.8)
text(8, 81.3, "Closed apps (no code change)", 10, True)
text(8, 75.8, "Claude Desktop · Cursor\nMCP Inspector", 8.8)
box(6, 48, 42, 14, "#F3F4F6", "#6B7280", 1.8)
text(8, 59.3, "Clients of a remote server", 10, True)
text(8, 53.8, "any app using an MCP URL\n(Streamable HTTP)", 8.8)

# ------------------------------------------------------------------ proxies (middle column)
text(58, 104.5, "RECORDERS", 9.5, True, "#4B5563")
box(58, 70, 56, 31, "#F3EEFF", "#7B4FD4", 2)
text(60, 98.3, "STDIO PROXY", 10.5, True, "#5B34B0")
text(60, 94.3, "agenttrace proxy --name X -- <server cmd>", 8.4, mono=True)
box(60.5, 72, 51, 19, "white", "#7B4FD4", 1.4)
num(63.2, 88.4, 2)
text(65.5, 88.4, "Recorder  (proxy/recorder.py)", 9, True)
text(62, 80.6, "request → open a span (parent from _meta)\nresponse → record result, close span\nsecrets hidden · tools/list captured\nsession id on every span", 8.3)
box(58, 46, 56, 18, "#F3EEFF", "#7B4FD4", 2)
text(60, 61, "HTTP PROXY", 10.5, True, "#5B34B0")
text(60, 57.3, "agenttrace proxy-http  (:7319/mcp/<name>)", 8.4, mono=True)
text(60, 51.6, "same Recorder · forwards JSON and SSE replies\nAuthorization forwarded, never recorded", 8.3)

# ------------------------------------------------------------------ real servers (right column)
text(124, 104.5, "REAL MCP SERVERS", 9.5, True, "#4B5563")
box(124, 78, 32, 17, "#E9F7EF", "#2E8B57", 1.8)
text(126, 92, "stdio servers", 10, True)
text(126, 85.6, "any language\nbookshop · filesystem\nGitHub · ...", 8.6)
box(124, 48, 32, 14, "#E9F7EF", "#2E8B57", 1.8)
text(126, 59, "remote server", 10, True)
text(126, 53.2, "reached by URL\n(code unchanged)", 8.6)

# arrows clients -> proxies -> servers
arrow((48, 94.5), (58, 94.5))
arrow((48, 77), (58, 77))
num(53, 96.2, 1)
label(53, 90.8, "starts the\nproxy", 8)
arrow((48, 55), (58, 55))
arrow((114, 86.5), (124, 86.5), "<|-|>")
arrow((114, 55), (124, 55), "<|-|>")
label(119, 89.6, "stdio", 8)
label(119, 58, "HTTP", 8)

# ------------------------------------------------------------------ AgentTrace server (bottom)
box(6, 2, 112, 38, "#EEF4FF", "#3B6FD4", 2.2, r=1.5, z=1)
text(8, 37, "AGENTTRACE SERVER", 10.5, True, "#2A55A8")
text(116, 37, "agenttrace up   \u00b7   http://127.0.0.1:7318", 9.2, True, "#2A55A8", ha="right")
# step boxes
box(9, 19, 27, 14, "white", "#3B6FD4")
text(10.5, 30.2, "POST /v1/traces", 9.2, True)
text(10.5, 24.2, "OTLP: protobuf, JSON\nor gzip  (server/app.py)", 8.2)
box(40, 19, 33, 14, "white", "#3B6FD4")
num(42.6, 30.5, 4)
text(45, 30.5, "ingest/otlp.py", 9.2, True)
text(41.5, 24, "OTLP → Span objects\nkeeps server + session attrs", 8.2)
box(77, 19, 38, 14, "white", "#3B6FD4")
num(79.6, 30.5, 5)
text(82, 30.5, "ingest/pipeline.py", 9.2, True)
text(78.5, 24, "save spans · save a snapshot\nof every new tools/list", 8.2)
arrow((36, 26), (40, 26))
arrow((73, 26), (77, 26))
box(9, 5, 106, 10, "white", "#3B6FD4")
num(11.6, 12.2, 6)
text(14, 12.2, "REST API  (server/app.py)  +  analysis  (analysis/)", 9.2, True)
text(11, 7.6, "/api/traces · /api/traces/<id> (+smells) · /api/sessions · /api/servers/<name>/snapshots "
              "(+drift) · /health", 8.0)

# SQLite
box(124, 2, 32, 38, "#E4F5EA", "#2E8B57", 2.2, r=1.5)
text(126, 37, "SQLite  (storage/)", 10, True, "#1F6B40")
text(126, 33.4, "~/.agenttrace/agenttrace.db", 7.6, mono=True)
text(126, 26.6, "spans            (table)\ntraces           (view)\nsessions         (view)\ntool_snapshots   (table)", 8.0, mono=True)
text(126, 14, "WAL mode: many writers,\nschema versioned", 8.2)
arrow((115, 26), (124, 26))
arrow((115, 10), (124, 10), "<|-|>")

# spans flow into the server
# proxies -> server (OTLP/HTTP)
line([114, 118.8, 118.8], [84, 84, 41.5])  # placeholder removed below
ax.lines[-1].remove()
arrow((84, 46), (84, 40.2))
num(84, 43.1, 3)
label(96.5, 43.1, "spans (OTLP/HTTP)", 8.2)
line([58, 52, 52], [72.4, 72.4, 36.5])
arrow((52, 36.5), (52, 33.2))
num(52, 66.5, 3)
label(52, 62.2, "spans\n(OTLP)", 8.2)
# SDK spans (left lane)
line([6, 3, 3], [94.5, 94.5, 26])
arrow((3, 26), (9, 26))
label(3, 62, "SDK\nspans", 8)

# ------------------------------------------------------------------ CLI + legend (bottom strip)
box(124, -13, 32, 8.5, "#FFF6CC", "#C9A400", 1.8)
text(126, -8.6, "CLI   agenttrace traces | show\nsessions | drift", 8.4, True)
arrow((140, -4.5), (140, 2), "<|-|>")
label(132, -1.6, "reads the file directly", 7.8)
legend = ["1  an app or the agent starts the proxy        2  the Recorder turns each request into a span",
          "3  spans are sent as OTLP to /v1/traces        4  parsed into Span objects",
          "5  spans and tool snapshots saved to SQLite        6  read back through the REST API or the CLI",
          "The SDK sends the agent's own spans straight to the server; the proxies send the MCP traffic. One trace."]
for i, line_text in enumerate(legend):
    text(6, -3.2 - 3.2 * i, line_text, 8.8, color="#4B5563" if i == 3 else INK)

# ------------------------------------------------------------------ code structure panel (right)
box(160, -12, 39, 114, "#FAFAFA", "#9CA3AF", 1.4, r=1.2, z=1)
text(162, 99, "CODE STRUCTURE", 10.5, True)
text(162, 95.4, "src/agenttrace/", 8.6, True, mono=True)
tree = """\
config.py     env settings
models.py     the Span shape
cli.py        up|proxy|traces
              show|sessions|drift
__main__.py   python -m agenttrace
proxy/
  recorder.py   MCP msg -> span
  stdio.py      stdio proxy
  http.py       HTTP proxy
  sessions.py   session id
  redact.py     hide secrets
ingest/
  otlp.py       OTLP -> Span
  pipeline.py   save + snapshots
storage/
  base.py       interfaces
  sqlite.py     the database
analysis/
  smells.py     loops, errors
  diff.py       run vs run
  safety.py     drift, injection
server/
  app.py        FastAPI: OTLP + API
sdk/
  setup.py      init(), proxy_server
                trace_tool_calls
examples/bookshop/   demo agent
tests/               35 tests
scripts/             bench, demos
docs/                this diagram
"""
ax.text(162, 93, tree, fontsize=7.9, family="monospace", va="top", ha="left", color=INK, linespacing=1.55, zorder=6)
text(162, -9.2, "no __init__.py files: namespace\npackages, explicit module imports", 7.6, color="#4B5563")

OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=160, bbox_inches="tight", facecolor="white", pad_inches=0.25)
print("wrote", OUT)
