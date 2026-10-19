// Draws docs/architecture.svg and docs/architecture.png: how a recording flows, with the real logos and every path labelled.
//   cd ui && node scripts/make-architecture.mjs
// The logos are in docs/brand/partners (WSO2's from the WSO2 API Platform, the others from the Simple Icons set); they belong to their
// owners and are used only to name the products Obsergent works with.
import { chromium } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const docs = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs");
const W = 1650;
const INK = "#1f2937";
const MUTED = "#4b5563";
const FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif";
const MONO = "ui-monospace, Menlo, Consolas, monospace";

// A logo as a data URI. Simple Icons have no colour of their own, so one is given.
function logo(file, colour) {
  let svg = readFileSync(join(docs, "brand", file), "utf8");
  if (colour) svg = svg.replace("<svg ", `<svg fill="${colour}" `);
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}
const LOGOS = {
  python: [logo("partners/python.svg", "#3776AB"), 1],
  langchain: [logo("partners/langchain.svg", "#1C3C3C"), 2.4],
  openai: [logo("partners/openai.svg", "#10A37F"), 1],
  anthropic: [logo("partners/anthropic.svg", "#C15F3C"), 1],
  ollama: [logo("partners/ollama.svg", "#111111"), 0.8],
  claude: [logo("partners/claude.svg", "#D97757"), 1],
  mcp: [logo("partners/modelcontextprotocol.svg", "#111111"), 1],
  docker: [logo("partners/docker.svg", "#2496ED"), 1.2],
  fastapi: [logo("partners/fastapi.svg", "#009688"), 1],
  otel: [logo("partners/opentelemetry.svg", "#425CC7"), 1],
  sqlite: [logo("partners/sqlite.svg", "#003B57"), 1],
  react: [logo("partners/react.svg", "#087EA4"), 1],
  wso2: [logo("partners/wso2-api-platform.svg", null), 4.15],
  obsergent: [logo("obsergent-mark.svg", null), 1],
};

const out = [];
const esc = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;");

// One box: logos along the top, a bold title, up to three grey lines.
function card(x, y, w, h, { title, lines = [], logos = [], fill, edge, dashed = false }) {
  out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="18" fill="${fill}" stroke="${edge}" stroke-width="3" ${dashed ? 'stroke-dasharray="10 7"' : ""}/>`);
  let cursor = x + 18;
  const size = h > 160 ? 40 : 36;
  for (const name of logos) {
    const [href, aspect] = LOGOS[name];
    out.push(`<image href="${href}" x="${cursor}" y="${y + 14}" width="${size * aspect}" height="${size}" preserveAspectRatio="xMidYMid meet"/>`);
    cursor += size * aspect + 14;
  }
  const top = y + 14 + size + 30;
  out.push(`<text x="${x + 18}" y="${top}" font-size="24" font-weight="700" fill="${INK}">${esc(title)}</text>`);
  lines.forEach((line, i) => out.push(`<text x="${x + 18}" y="${top + 28 + i * 24}" font-size="18" fill="${MUTED}">${esc(line)}</text>`));
}

// A line with an arrow head at one or both ends, drawn through the given points (straight segments).
function path(points, { colour = INK, dashed = false, both = false }) {
  const d = points.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join(" ");
  out.push(`<path d="${d}" fill="none" stroke="${colour}" stroke-width="3.4" stroke-linejoin="round" ${dashed ? 'stroke-dasharray="11 8"' : ""} marker-end="url(#head-${colour.slice(1)})" ${both ? `marker-start="url(#tail-${colour.slice(1)})"` : ""}/>`);
}

// The number of a path with its short name, sitting on the line.
function pill(cx, cy, number, text1, text2 = "", colour = INK) {
  const width = Math.max(text1.length, text2.length) * 9.4 + 58;
  const height = text2 ? 56 : 38;
  out.push(`<rect x="${cx - width / 2}" y="${cy - height / 2}" width="${width}" height="${height}" rx="${height / 2}" fill="#ffffff" stroke="${colour}" stroke-width="2.4"/>`);
  out.push(`<circle cx="${cx - width / 2 + 22}" cy="${cy}" r="14" fill="${colour}"/><text x="${cx - width / 2 + 22}" y="${cy + 6}" text-anchor="middle" font-size="17" font-weight="700" fill="#fff">${number}</text>`);
  out.push(`<text x="${cx - width / 2 + 44}" y="${cy + (text2 ? -4 : 6)}" font-size="16.5" font-weight="600" fill="${INK}" font-family="${MONO}">${esc(text1)}</text>`);
  if (text2) out.push(`<text x="${cx - width / 2 + 44}" y="${cy + 17}" font-size="16.5" fill="${MUTED}" font-family="${MONO}">${esc(text2)}</text>`);
}

const BLUE = "#2f5fb8", PURPLE = "#7048c9", ORANGE = "#e8731a", GREEN = "#2a7d4f", TEAL = "#0e7490", GOLD = "#b58900", GREY = "#6b7280";
const CW = 270;
const [C0, C1, C2, C3] = [30, 470, 910, 1350];

// ------------------------------------------------------------------ title
out.push(`<image href="${LOGOS.obsergent[0]}" x="30" y="24" width="64" height="64"/>`);
out.push(`<text x="112" y="62" font-size="38" font-weight="800" fill="${INK}">Obsergent: how a recording flows</text>`);
out.push(`<text x="112" y="96" font-size="20" fill="${MUTED}">Every numbered path is explained in the table below with its protocol, port and what travels on it.</text>`);

// ------------------------------------------------------------------ row A: agent, model providers, legend
card(C0, 140, CW, 150, { title: "Your agent", lines: ["LangGraph + Obsergent SDK", "examples/bookshop/agent.py"], logos: ["python", "langchain"], fill: "#eef4ff", edge: BLUE });
card(C1, 140, CW, 150, { title: "AI model providers", lines: ["OpenAI · Anthropic · Ollama", "chosen in your .env"], logos: ["openai", "anthropic", "ollama"], fill: "#f4f4f5", edge: GREY });
out.push(`<rect x="${C2}" y="140" width="${C3 + CW - C2}" height="150" rx="18" fill="#ffffff" stroke="#d1d5db" stroke-width="2"/>`);
out.push(`<text x="${C2 + 20}" y="176" font-size="21" font-weight="700" fill="${INK}">How to read the lines</text>`);
out.push(`<path d="M${C2 + 20} 204 H${C2 + 90}" stroke="${INK}" stroke-width="3.4" marker-end="url(#head-1f2937)"/><text x="${C2 + 106}" y="210" font-size="18" fill="${INK}">MCP traffic: your agent using its tools</text>`);
out.push(`<path d="M${C2 + 20} 238 H${C2 + 90}" stroke="${BLUE}" stroke-width="3.4" stroke-dasharray="11 8" marker-end="url(#head-2f5fb8)"/><text x="${C2 + 106}" y="244" font-size="18" fill="${INK}">Recording: spans sent to Obsergent (OpenTelemetry)</text>`);
out.push(`<rect x="${C2 + 20}" y="258" width="70" height="20" rx="6" fill="#fff1e6" stroke="${ORANGE}" stroke-width="2.4" stroke-dasharray="7 5"/><text x="${C2 + 106}" y="274" font-size="18" fill="${INK}">Optional: works with or without the gateway</text>`);

// ------------------------------------------------------------------ row B: closed apps, proxy, gateway, MCP server
card(C0, 380, CW, 180, { title: "Closed apps", lines: ["Claude Desktop · Cursor", "no code change needed"], logos: ["claude"], fill: "#fff7ed", edge: "#c2410c" });
card(C1, 380, CW, 180, { title: "Obsergent proxy", lines: ["records every MCP message", "http :7319 · stdio"], logos: ["obsergent"], fill: "#f3eeff", edge: PURPLE });
card(C2, 380, CW, 180, { title: "WSO2 API Platform", lines: ["gateway · router :8080", "controller :9090 · Docker"], logos: ["wso2", "docker"], fill: "#fff1e6", edge: ORANGE, dashed: true });
card(C3, 380, CW, 180, { title: "MCP server", lines: ["bookshop_http.py :9100", "bookshop_server.py (stdio)"], logos: ["mcp"], fill: "#e9f7ef", edge: GREEN });

// ------------------------------------------------------------------ row C: Obsergent server and its store
card(C1, 700, C2 + CW - C1, 180, { title: "Obsergent server", lines: ["FastAPI :7318 · UI, REST /api, OTLP/HTTP", "OTLP/gRPC receiver :4317 (--grpc)"], logos: ["obsergent", "fastapi", "otel"], fill: "#e6f6fb", edge: TEAL });
card(C3, 700, CW, 180, { title: "SQLite", lines: ["~/.obsergent/obsergent.db", "one file, on your machine"], logos: ["sqlite"], fill: "#e4f0f5", edge: "#0f5f7a" });
card(C1, 960, CW, 150, { title: "You", lines: ["Web UI · CLI · REST API", "http://127.0.0.1:7318"], logos: ["react"], fill: "#fff9db", edge: GOLD });
card(C2, 960, CW, 150, { title: "Public price lists", lines: ["models.dev · OpenRouter", "Hugging Face · LiteLLM"], logos: [], fill: "#f4f4f5", edge: GREY });

// ------------------------------------------------------------------ the paths
const mcp = INK, rec = BLUE;
path([[C0 + CW, 190], [C1, 190]], { colour: mcp, both: true });                     // 2 agent -> model providers
pill((C0 + CW + C1) / 2, 190, 2, "HTTPS", "model calls");
path([[C0 + CW, 262], [380, 262], [380, 430], [C1, 430]], { colour: mcp, both: true });   // 1 agent -> proxy (HTTP)
pill(380, 346, 1, "HTTP :7319", "MCP");
path([[C0 + CW, 510], [C1, 510]], { colour: mcp, both: true });                      // 3 closed app -> proxy (stdio)
pill((C0 + CW + C1) / 2, 510, 3, "stdio", "MCP");
path([[C1 + CW, 430], [C2, 430]], { colour: mcp, both: true });                      // 4 proxy -> gateway
pill((C1 + CW + C2) / 2, 430, 4, "HTTP :8080", "MCP");
path([[C2 + CW, 430], [C3, 430]], { colour: mcp, both: true });                      // 5 gateway -> MCP server
pill((C2 + CW + C3) / 2, 430, 5, "HTTP :9100", "MCP");
path([[C1 + 190, 380], [C1 + 190, 332], [C3 + 125, 332], [C3 + 125, 380]], { colour: mcp, both: true, dashed: false }); // 6 direct
pill(1080, 332, 6, "direct, no gateway");
path([[C0, 215], [12, 215], [12, 790], [C1, 790]], { colour: rec, dashed: true });             // 7 SDK spans
pill(215, 790, 7, "OTLP/HTTP :7318");
path([[C1 + 125, 560], [C1 + 125, 700]], { colour: rec, dashed: true });                    // 8 proxy spans
pill(C1 + 125, 630, 8, "OTLP/HTTP", ":7318/v1/traces", rec);
path([[C2 + 125, 560], [C2 + 125, 700]], { colour: rec, dashed: true });                    // 9 gateway spans
pill(C2 + 125, 630, 9, "OTLP/gRPC", ":4317", rec);
path([[C2 + CW, 790], [C3, 790]], { colour: INK, both: true }); // 10 server <-> sqlite
pill((C2 + CW + C3) / 2, 790, 10, "file");
path([[C1 + 125, 880], [C1 + 125, 960]], { colour: INK });                                  // 11 server -> you
pill(C1 + 125, 920, 11, "HTTP :7318");
path([[C2 + 125, 880], [C2 + 125, 960]], { colour: INK });                                  // 12 server -> price lists
pill(C2 + 125, 920, 12, "HTTPS GET");

// ------------------------------------------------------------------ the table of paths
const rows = [
  ["1", "Agent ⇄ Obsergent proxy", "MCP over HTTP · 127.0.0.1:7319/mcp/wso2", "tools/list, tools/call; the trace id travels (traceparent)"],
  ["2", "Agent ⇄ AI model provider", "HTTPS (Ollama: localhost:11434)", "the prompt and the answer; the SDK records tokens and cost"],
  ["3", "Closed app ⇄ Obsergent proxy", "MCP over stdio · obsergent proxy -- <cmd>", "the app starts the proxy, the proxy starts the real server"],
  ["4", "Proxy ⇄ WSO2 gateway", "MCP over HTTP · router :8080/bookshop/mcp", "the same request, checked by the gateway (login, scopes)"],
  ["5", "WSO2 gateway ⇄ MCP server", "MCP over HTTP · :9100", "the request the gateway let through, and the reply"],
  ["6", "Proxy ⇄ MCP server (no gateway)", "stdio, or HTTP :9100", "the direct path when no gateway is in front"],
  ["7", "Agent SDK → Obsergent server", "OTLP/HTTP · POST :7318/v1/traces", "LangGraph steps, model calls and tool steps (spans)"],
  ["8", "Proxy → Obsergent server", "OTLP/HTTP · POST :7318/v1/traces", "one span per MCP message; secrets replaced by ***"],
  ["9", "WSO2 gateway → Obsergent server", "OTLP/gRPC · host.docker.internal:4317", "gateway decision and where it spent its time"],
  ["10", "Obsergent server ⇄ SQLite", "file · ~/.obsergent/obsergent.db", "spans, tool lists, price lists and their history"],
  ["11", "Obsergent server → You", "HTTP · 127.0.0.1:7318 (web UI, /api)", "conversations, agents, MCPs, models, spending"],
  ["12", "Obsergent server → price lists", "HTTPS GET (the only outbound call)", "public model prices; nothing of yours is sent"],
];
const tableTop = 1170;
out.push(`<text x="30" y="${tableTop}" font-size="26" font-weight="800" fill="${INK}">The paths, one by one</text>`);
out.push(`<rect x="30" y="${tableTop + 18}" width="${W - 60}" height="40" rx="8" fill="#e5e7eb"/>`);
for (const [x, label] of [[46, "#"], [96, "From → to"], [440, "Protocol · port"], [940, "What travels"]]) out.push(`<text x="${x}" y="${tableTop + 45}" font-size="18" font-weight="700" fill="${INK}">${label}</text>`);
rows.forEach(([n, route, protocol, what], i) => {
  const y = tableTop + 92 + i * 46;
  if (i % 2 === 0) out.push(`<rect x="30" y="${y - 28}" width="${W - 60}" height="46" fill="#f9fafb"/>`);
  out.push(`<circle cx="62" cy="${y - 5}" r="14" fill="${i === 6 || i === 7 || i === 8 ? rec : INK}"/><text x="62" y="${y + 1}" text-anchor="middle" font-size="16" font-weight="700" fill="#fff">${n}</text>`);
  out.push(`<text x="96" y="${y}" font-size="17.5" font-weight="600" fill="${INK}">${esc(route)}</text>`);
  out.push(`<text x="440" y="${y}" font-size="16" fill="${INK}" font-family="${MONO}">${esc(protocol)}</text>`);
  out.push(`<text x="940" y="${y}" font-size="16.5" fill="${MUTED}">${esc(what)}</text>`);
});
const H = tableTop + 92 + rows.length * 46 + 50;
out.push(`<text x="30" y="${H - 22}" font-size="17" fill="${MUTED}">Logos belong to their owners and name the products Obsergent works with. Everything stays on your machine except path 12.</text>`);

const heads = [INK, BLUE].map((c) => `<marker id="head-${c.slice(1)}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="${c}"/></marker>
<marker id="tail-${c.slice(1)}" viewBox="0 0 10 10" refX="1.5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${c}"/></marker>`).join("");
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family="${FONT}"><defs>${heads}</defs><rect width="${W}" height="${H}" fill="#ffffff"/>${out.join("\n")}</svg>`;
writeFileSync(join(docs, "architecture.svg"), svg);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 2 });
await page.setContent(`<body style="margin:0">${svg}</body>`);
writeFileSync(join(docs, "architecture.png"), await page.screenshot());
await browser.close();
console.log("wrote docs/architecture.svg and docs/architecture.png", W, "x", H);
