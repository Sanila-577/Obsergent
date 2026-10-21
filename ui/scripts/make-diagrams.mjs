// Draws the documentation diagrams into docs/diagrams/, in dark mode:
//   architecture.png   how Obsergent works, with the tech stack          (README)
//   closed-apps.png    recording Claude Desktop and other apps            (README, docs/closed-apps.md)
//   tokens-flow.png    where the token counts come from                   (docs/costs.md)
//   wso2-flow.png      Obsergent with the WSO2 API Platform gateway       (README, docs/wso2-integration.md)
// Run: cd ui && node scripts/make-diagrams.mjs   (or `make diagrams`). THEME=light draws light versions (name-light.png) instead.
// Icons are Lucide's (lucide-react, rendered to SVG); product logos are in docs/brand/partners and belong to their owners.
import { chromium } from "@playwright/test";
import * as Lucide from "lucide-react";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const docs = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs");
const out = join(docs, "diagrams");
const FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif";
const MONO = "ui-monospace, Menlo, Consolas, monospace";

// The two colour themes. Each card kind has an accent colour; fills are a light (or dark) tint of it.
const THEMES = {
  light: {
    bg: "#ffffff", ink: "#111827", muted: "#4b5563", faint: "#6b7280", line: "#334155", spans: "#2563eb", pill: "#ffffff",
    group: "#94a3b8", strip: "#f3f4f6",
    accents: { agent: "#2563eb", app: "#c2410c", model: "#0f766e", proxy: "#7c3aed", gateway: "#ea580c", mcp: "#15803d",
      server: "#0e7490", store: "#0f5f7a", ui: "#a16207" },
    tint: 0.09,
  },
  dark: {
    bg: "#0b1220", ink: "#eef2ff", muted: "#b6c2dd", faint: "#93a3c4", line: "#cbd5e1", spans: "#60a5fa", pill: "#111a2e",
    group: "#64748b", strip: "#121b2e",
    accents: { agent: "#60a5fa", app: "#fb923c", model: "#2dd4bf", proxy: "#a78bfa", gateway: "#fb923c", mcp: "#4ade80",
      server: "#22d3ee", store: "#38bdf8", ui: "#facc15" },
    tint: 0.14,
  },
};

// Product logos: Simple Icons have no colour of their own, so they get one per theme (dark brand colours turn light on dark).
const LOGOS = {
  python: ["partners/python.svg", "#3776AB", "#7fb2e5", 1],
  langchain: ["partners/langchain.svg", "#1C3C3C", "#d1fae5", 2.4],
  openai: ["partners/openai.svg", "#10A37F", "#34d399", 1],
  anthropic: ["partners/anthropic.svg", "#C15F3C", "#f0a080", 1],
  ollama: ["partners/ollama.svg", "#111111", "#f1f5f9", 0.8],
  claude: ["partners/claude.svg", "#D97757", "#f0a080", 1],
  mcp: ["partners/modelcontextprotocol.svg", "#111111", "#f1f5f9", 1],
  docker: ["partners/docker.svg", "#2496ED", "#5cb3f5", 1.2],
  fastapi: ["partners/fastapi.svg", "#009688", "#34d3c0", 1],
  otel: ["partners/opentelemetry.svg", "#425CC7", "#8fa2ff", 1],
  sqlite: ["partners/sqlite.svg", "#003B57", "#7cc4e8", 1],
  react: ["partners/react.svg", "#087EA4", "#61dafb", 1],
  vite: ["partners/vite.svg", "#646CFF", "#a5a9ff", 1],
  typescript: ["partners/typescript.svg", "#3178C6", "#7fb2ff", 1],
  wso2: ["partners/wso2-api-platform.svg", null, null, 4.15],
  obsergent: ["obsergent-mark.svg", null, null, 1],
};

function mix(hex, alpha, base) {
  // `hex` laid over `base` with the given opacity, as a solid colour (PNG viewers do not all blend transparent fills alike).
  const parse = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [a, b] = [parse(hex), parse(base)];
  return `#${a.map((v, i) => Math.round(v * alpha + b[i] * (1 - alpha)).toString(16).padStart(2, "0")).join("")}`;
}

function logoUri(name, theme) {
  const [file, light, dark] = LOGOS[name];
  let svg = readFileSync(join(docs, "brand", file), "utf8");
  const colour = theme === "dark" ? dark : light;
  if (colour) svg = svg.replace("<svg ", `<svg fill="${colour}" `);
  if (name === "wso2" && theme === "dark") svg = svg.replaceAll('fill="black"', 'fill="#f1f5f9"');
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}

function iconSvg(name, size, colour, x, y) {
  const markup = renderToStaticMarkup(createElement(Lucide[name], { size, color: colour, strokeWidth: 2 }));
  return markup.replace("<svg ", `<svg x="${x}" y="${y}" `);
}

const esc = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;");

// A drawing: collects SVG pieces, knows its theme.
function canvas(width, height, theme) {
  const t = THEMES[theme];
  const parts = [];
  const api = {
    t,
    // A card: icon tile on the left, title, subtitle, an optional caption (ports, numbers) and an optional row of product logos.
    card(x, y, w, h, { kind, icon, title, sub = "", caption = "", logos = [], dashed = false, badge = null }) {
      const accent = t.accents[kind];
      parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="20" fill="${mix(accent, t.tint, t.bg)}" stroke="${accent}" stroke-width="2.5" ${dashed ? 'stroke-dasharray="10 7"' : ""}/>`);
      const tile = 60;
      const ty = y + (h - tile) / 2;
      parts.push(`<rect x="${x + 18}" y="${ty}" width="${tile}" height="${tile}" rx="16" fill="${mix(accent, theme === "dark" ? 0.28 : 0.16, t.bg)}"/>`);
      parts.push(icon.startsWith("logo:")
        ? `<image href="${logoUri(icon.slice(5), theme)}" x="${x + 28}" y="${ty + 10}" width="40" height="40"/>`
        : iconSvg(icon, 34, accent, x + 18 + (tile - 34) / 2, ty + (tile - 34) / 2));
      const tx = x + 18 + tile + 16;
      // The text block (title, subtitle, caption, then a row of logos) is centred vertically in the card.
      const heights = [26, sub ? 27 : 0, caption ? 25 : 0, logos.length ? 38 : 0];
      let line = y + (h - heights.reduce((a, b) => a + b, 0)) / 2 + 20;
      parts.push(`<text x="${tx}" y="${line}" font-size="23" font-weight="700" fill="${t.ink}">${esc(title)}</text>`);
      if (sub) { line += 27; parts.push(`<text x="${tx}" y="${line}" font-size="17.5" fill="${t.muted}">${esc(sub)}</text>`); }
      if (caption) { line += 25; parts.push(`<text x="${tx}" y="${line}" font-size="15.5" fill="${t.faint}" font-family="${MONO}">${esc(caption)}</text>`); }
      let lx = tx;
      for (const name of logos) {
        const width = 24 * LOGOS[name][3];
        parts.push(`<image href="${logoUri(name, theme)}" x="${lx}" y="${line + 12}" width="${width}" height="24" preserveAspectRatio="xMinYMid meet"/>`);
        lx += width + 12;
      }
      if (badge !== null) {
        parts.push(`<circle cx="${x + w - 26}" cy="${y + h - 26}" r="15" fill="${accent}"/><text x="${x + w - 26}" y="${y + h - 20.5}" text-anchor="middle" font-size="16" font-weight="800" fill="${t.bg}">${badge}</text>`);
      }
    },
    // A straight (or elbowed) arrow through the given points, with an optional label next to its middle segment.
    arrow(points, { label = "", dashed = false, both = false, colour = t.line, labelAt = null, labelSide = "above" } = {}) {
      const d = points.map(([px, py], i) => `${i ? "L" : "M"}${px} ${py}`).join(" ");
      const id = colour.slice(1);
      parts.push(`<path d="${d}" fill="none" stroke="${colour}" stroke-width="3" stroke-linejoin="round" ${dashed ? 'stroke-dasharray="10 7"' : ""} marker-end="url(#h${id})" ${both ? `marker-start="url(#t${id})"` : ""}/>`);
      if (label) {
        const [[ax, ay], [bx, by]] = labelAt ?? [points[points.length - 2], points[points.length - 1]];
        const mx = (ax + bx) / 2;
        const my = (ay + by) / 2;
        const vertical = ax === bx;
        const width = label.length * 8.6 + 22;
        const lx = vertical ? mx + 14 : mx - width / 2;
        const ly = vertical ? my - 15 : labelSide === "above" ? my - 40 : my + 10;
        parts.push(`<rect x="${lx}" y="${ly}" width="${width}" height="30" rx="15" fill="${t.pill}" stroke="${mix(colour, 0.45, t.bg)}" stroke-width="1.5"/>`);
        parts.push(`<text x="${lx + width / 2}" y="${ly + 20.5}" text-anchor="middle" font-size="15.5" font-weight="600" fill="${t.ink}">${esc(label)}</text>`);
      }
    },
    // A dashed box with a small caption, to group things ("optional", "on your computer").
    group(x, y, w, h, caption) {
      parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="26" fill="none" stroke="${t.group}" stroke-width="2" stroke-dasharray="6 6"/>`);
      const width = caption.length * 8.4 + 24;
      parts.push(`<rect x="${x + 22}" y="${y - 14}" width="${width}" height="28" rx="14" fill="${t.bg}"/>`);
      parts.push(`<text x="${x + 22 + width / 2}" y="${y + 5}" text-anchor="middle" font-size="15" font-weight="700" fill="${t.faint}" letter-spacing=".04em">${esc(caption.toUpperCase())}</text>`);
    },
    text(x, y, content, { size = 18, weight = 400, colour = t.muted, anchor = "start" } = {}) {
      parts.push(`<text x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${colour}" text-anchor="${anchor}">${esc(content)}</text>`);
    },
    logo(name, x, y, height) {
      parts.push(`<image href="${logoUri(name, theme)}" x="${x}" y="${y}" width="${height * LOGOS[name][3]}" height="${height}"/>`);
    },
    raw(svg) { parts.push(svg); },
    svg() {
      const colours = [...new Set([t.line, t.spans])];
      const markers = colours.map((c) => `<marker id="h${c.slice(1)}" viewBox="0 0 10 10" refX="8.6" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="${c}"/></marker>`
        + `<marker id="t${c.slice(1)}" viewBox="0 0 10 10" refX="1.4" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${c}"/></marker>`).join("");
      return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-family="${FONT}"><defs>${markers}</defs><rect width="${width}" height="${height}" fill="${t.bg}"/>${parts.join("\n")}</svg>`;
    },
  };
  return api;
}

// ------------------------------------------------------------------------------------------------ the diagrams
function architecture(theme) {
  const W = 1700, H = 960;
  const c = canvas(W, H, theme);
  const { t } = c;
  c.logo("obsergent", 40, 30, 46);
  c.text(100, 66, "How Obsergent works", { size: 32, weight: 800, colour: t.ink });
  // Row 1: what you run.
  c.card(40, 120, 360, 140, { kind: "app", icon: "MessagesSquare", title: "Claude Desktop", sub: "Cursor and other apps", logos: ["claude"] });
  c.card(480, 120, 380, 140, { kind: "agent", icon: "Bot", title: "Your agent", sub: "LangGraph + obsergent.sdk", logos: ["python", "langchain"] });
  c.card(960, 120, 400, 140, { kind: "model", icon: "Sparkles", title: "AI models", sub: "Ollama · OpenAI · Anthropic …", logos: ["ollama", "openai", "anthropic"] });
  // Row 2: the MCP path.
  c.card(480, 350, 380, 140, { kind: "proxy", icon: "logo:obsergent", title: "Obsergent proxy", sub: "records every MCP call", caption: "stdio or HTTP :7319" });
  c.group(940, 326, 440, 188, "optional");
  c.card(960, 350, 400, 140, { kind: "gateway", icon: "ShieldCheck", title: "WSO2 gateway", sub: "login, scopes, rate limits", logos: ["wso2", "docker"] });
  c.card(1460, 350, 200, 140, { kind: "mcp", icon: "logo:mcp", title: "MCP", sub: "servers" });
  // Row 3: Obsergent itself.
  c.card(480, 590, 880, 150, { kind: "server", icon: "Activity", title: "Obsergent server", sub: "receives what was recorded · REST API · prices · web UI", caption: ":7318 OTLP/HTTP · :4317 OTLP/gRPC", logos: ["fastapi", "otel"] });
  c.card(40, 590, 360, 150, { kind: "ui", icon: "LayoutDashboard", title: "Web UI · CLI", sub: "http://127.0.0.1:7318", logos: ["react"] });
  c.card(1440, 590, 220, 150, { kind: "store", icon: "logo:sqlite", title: "SQLite", sub: "one file" });
  // The arrows: MCP traffic (solid) and recordings (dashed blue).
  c.arrow([[220, 260], [220, 420], [480, 420]], { label: "MCP", labelAt: [[220, 420], [480, 420]] });
  c.arrow([[670, 260], [670, 350]], { label: "MCP" });
  c.arrow([[860, 190], [960, 190]], { label: "prompts", both: true });
  c.arrow([[860, 420], [960, 420]]);
  c.arrow([[1360, 420], [1460, 420]]);
  c.arrow([[670, 490], [670, 590]], { label: "spans from the agent and the proxy", dashed: true, colour: t.spans });
  c.arrow([[1160, 490], [1160, 590]], { label: "gateway spans", dashed: true, colour: t.spans });
  c.arrow([[1360, 665], [1440, 665]], { both: true });
  c.arrow([[480, 665], [400, 665]]);
  // The tech stack.
  c.raw(`<rect x="40" y="790" width="${W - 80}" height="120" rx="20" fill="${t.strip}"/>`);
  c.text(70, 840, "Built with", { size: 19, weight: 800, colour: t.ink });
  const stack = [["python", "Python"], ["fastapi", "FastAPI"], ["otel", "OpenTelemetry"], ["sqlite", "SQLite"], ["react", "React"],
    ["typescript", "TypeScript"], ["vite", "Vite"], ["langchain", "LangGraph"], ["mcp", "MCP"], ["docker", "Docker"], ["wso2", "WSO2"]];
  let x = 200;
  for (const [name, label] of stack) {
    const width = name === "wso2" ? 120 : 34 * LOGOS[name][3];
    c.logo(name, x + (110 - width) / 2, 812, name === "wso2" ? 29 : 34);
    c.text(x + 55, 884, label, { size: 15.5, weight: 600, colour: t.muted, anchor: "middle" });
    x += 132;
  }
  c.text(40, 942, "Solid arrows: MCP calls of your agents and apps. Dashed: what is recorded, sent to Obsergent (OpenTelemetry spans).", { size: 15.5, colour: t.faint });
  return c.svg();
}

function closedApps(theme) {
  const W = 1340, H = 470;
  const c = canvas(W, H, theme);
  const { t } = c;
  c.card(40, 50, 360, 120, { kind: "app", icon: "logo:claude", title: "Claude Desktop", sub: "Cursor, MCP Inspector …" });
  c.card(490, 50, 360, 120, { kind: "proxy", icon: "logo:obsergent", title: "obsergent proxy", sub: "records every call", caption: "started by the app" });
  c.card(940, 50, 360, 120, { kind: "mcp", icon: "logo:mcp", title: "Your MCP server", sub: "unchanged" });
  c.card(490, 290, 360, 130, { kind: "server", icon: "Activity", title: "obsergent up", sub: "server + web UI", caption: "http://127.0.0.1:7318" });
  c.card(940, 290, 360, 130, { kind: "store", icon: "logo:sqlite", title: "SQLite", sub: "~/.obsergent/obsergent.db" });
  c.arrow([[400, 110], [490, 110]], { label: "MCP", both: true });
  c.arrow([[850, 110], [940, 110]], { label: "MCP", both: true });
  c.arrow([[670, 170], [670, 290]], { label: "spans", dashed: true, colour: t.spans });
  c.arrow([[850, 355], [940, 355]], { both: true });
  return c.svg();
}

function tokensFlow(theme) {
  const W = 1420, H = 520;
  const c = canvas(W, H, theme);
  const { t } = c;
  // Row 1, left to right: the counts are made and recorded. Row 2, right to left: stored and shown.
  const [a, b, d] = [40, 530, 1020];
  c.card(a, 50, 360, 130, { kind: "agent", icon: "Bot", title: "Your agent", sub: "asks the model", caption: "LangChain", badge: 1 });
  c.card(b, 50, 360, 130, { kind: "model", icon: "logo:ollama", title: "The model", sub: "answers, counts tokens", caption: "332 in · 27 out", badge: 2 });
  c.card(d, 50, 360, 130, { kind: "proxy", icon: "logo:obsergent", title: "obsergent.sdk", sub: "writes them on a span", caption: "llm.token_count.*", badge: 3 });
  c.card(d, 320, 360, 130, { kind: "server", icon: "Activity", title: "Obsergent server", sub: "receives every second", caption: ":7318/v1/traces", badge: 4 });
  c.card(b, 320, 360, 130, { kind: "store", icon: "logo:sqlite", title: "SQLite", sub: "stores the span", caption: "spans table", badge: 5 });
  c.card(a, 320, 360, 130, { kind: "ui", icon: "LayoutDashboard", title: "Web UI", sub: "adds them up", caption: "359 tokens", badge: 6 });
  c.arrow([[a + 360, 115], [b, 115]], { label: "question" });
  c.arrow([[b + 360, 115], [d, 115]], { label: "counts" });
  c.arrow([[d + 180, 180], [d + 180, 320]], { label: "OpenTelemetry", dashed: true, colour: t.spans });
  c.arrow([[d, 385], [b + 360, 385]]);
  c.arrow([[b, 385], [a + 360, 385]]);
  return c.svg();
}

function wso2Flow(theme) {
  const W = 1620, H = 540;
  const c = canvas(W, H, theme);
  const { t } = c;
  c.card(40, 50, 330, 150, { kind: "agent", icon: "Bot", title: "Agent or app", sub: "your agent, Claude …", logos: ["python"] });
  c.card(450, 50, 340, 150, { kind: "proxy", icon: "logo:obsergent", title: "Obsergent proxy", sub: "records each call", caption: "http://127.0.0.1:7319" });
  c.card(870, 50, 400, 150, { kind: "gateway", icon: "ShieldCheck", title: "WSO2 gateway", sub: "Docker: router + controller", caption: "router :8080", logos: ["wso2", "docker"] });
  c.card(1350, 50, 230, 150, { kind: "mcp", icon: "logo:mcp", title: "MCP server", caption: ":9100" });
  c.card(450, 350, 820, 150, { kind: "server", icon: "Activity", title: "Obsergent server + web UI", sub: "both sides of every call, joined in one trace", caption: ":7318 (HTTP) · :4317 (gRPC)", logos: ["otel"] });
  c.arrow([[370, 125], [450, 125]], { both: true });
  c.arrow([[790, 125], [870, 125]], { both: true });
  c.arrow([[1270, 125], [1350, 125]], { both: true });
  c.arrow([[620, 200], [620, 350]], { label: "spans · OTLP/HTTP", dashed: true, colour: t.spans });
  c.arrow([[1070, 200], [1070, 350]], { label: "spans · OTLP/gRPC", dashed: true, colour: t.spans });
  return c.svg();
}

const DIAGRAMS = { architecture, "closed-apps": closedApps, "tokens-flow": tokensFlow, "wso2-flow": wso2Flow };

const theme = process.env.THEME === "light" ? "light" : "dark";
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
for (const [name, draw] of Object.entries(DIAGRAMS)) {
  const svg = draw(theme);
  const [, width, height] = svg.match(/viewBox="0 0 (\d+) (\d+)"/).map(Number);
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2 });
  await page.setContent(`<body style="margin:0">${svg}</body>`);
  writeFileSync(join(out, `${name}${theme === "light" ? "-light" : ""}.png`), await page.screenshot());
  await page.close();
}
await browser.close();
console.log(`wrote ${Object.keys(DIAGRAMS).length} diagrams in docs/diagrams/`);
