// Token trends of the models: a small sparkline for each model card, a full in/out chart for one model, and all models together.
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ModelEntry } from "../api/types";
import { colorFor } from "../lib/colors";
import { formatMoney, formatTokens } from "../lib/format";

type Slot = NonNullable<ModelEntry["series"]>[number];

function label(ns: number, hours: number): string {
  const date = new Date(ns / 1e6);
  return hours <= 24 ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
    : date.toLocaleDateString([], { day: "numeric", month: "short" });
}

const animate = () => !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** A tiny line of the model's tokens per time slot (no axes), for a card. */
export function Sparkline({ series }: { series: Slot[] }) {
  if (!series.length) return null;
  const rows = series.map((slot) => ({ total: slot.input + slot.output }));
  return (
    <div className="sparkline" role="img" aria-label="Tokens over time">
      <ResponsiveContainer width="100%" height={38}>
        <LineChart data={rows} margin={{ top: 4, right: 2, left: 2, bottom: 2 }}>
          <Line type="monotone" dataKey="total" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={animate()} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// The hover card of a slot: time, tokens in/out, calls and cost.
function SlotTip({ active, payload, title }: { active?: boolean; payload?: { payload: Slot & { label: string } }[]; title?: string }) {
  if (!active || !payload?.[0]) return null;
  const slot = payload[0].payload;
  return (
    <div className="peaks-tip"><div className="peaks-tip-time">{slot.label}{title ? ` · ${title}` : ""}</div>
      <div className="tip-grid"><span>Tokens in</span><span>{formatTokens(slot.input)}</span><span>Tokens out</span><span>{formatTokens(slot.output)}</span>
        {slot.cached > 0 && <><span>Cached</span><span>{formatTokens(slot.cached)}</span></>}
        <span>Calls</span><span>{slot.calls}</span><span>Cost</span><span>{formatMoney(slot.usd)}</span></div></div>
  );
}

/** One model: input and output tokens per time slot (cached as a dashed line when there is any). */
export function ModelTokensChart({ series, hours }: { series: Slot[]; hours: number }) {
  const rows = series.map((slot) => ({ ...slot, label: label(slot.start_ns, hours) }));
  const cached = series.some((slot) => slot.cached > 0);
  return (
    <div role="img" aria-label="Tokens in and out over time" className="model-chart">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="var(--muted)" fontSize={11} tickLine={false} minTickGap={24} />
          <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false} tickFormatter={formatTokens} width={48} />
          <Tooltip content={<SlotTip />} wrapperStyle={{ outline: "none" }} />
          <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
          <Line type="monotone" dataKey="input" name="tokens in" stroke="var(--agent)" strokeWidth={2.4} dot={false} activeDot={{ r: 5 }} isAnimationActive={animate()} />
          <Line type="monotone" dataKey="output" name="tokens out" stroke="var(--proxy)" strokeWidth={2.4} dot={false} activeDot={{ r: 5 }} isAnimationActive={animate()} />
          {cached && <Line type="monotone" dataKey="cached" name="cached" stroke="var(--accent-2)" strokeDasharray="5 4" dot={false} isAnimationActive={animate()} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** All models in one chart: one line per model (total tokens per time slot). */
export function CompareModelsChart({ models, hours }: { models: ModelEntry[]; hours: number }) {
  const names = models.map((m) => m.model);
  const first = models.find((m) => m.series?.length)?.series ?? [];
  const rows = first.map((slot, index) => ({
    label: label(slot.start_ns, hours),
    ...Object.fromEntries(models.map((m) => [m.model, (m.series?.[index]?.input ?? 0) + (m.series?.[index]?.output ?? 0)])),
  }));
  return (
    <div role="img" aria-label="Tokens of every model over time" className="model-chart">
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="var(--muted)" fontSize={11} tickLine={false} minTickGap={24} />
          <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false} tickFormatter={formatTokens} width={48} />
          <Tooltip formatter={(value, name) => [`${formatTokens(Number(value))} tokens`, String(name)]}
            contentStyle={{ background: "var(--glass-strong)", border: "1px solid var(--glass-border)", borderRadius: 12, color: "var(--text)" }} />
          <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
          {names.map((name) => <Line key={name} type="monotone" dataKey={name} stroke={colorFor(names, name)} strokeWidth={2.2} dot={false} activeDot={{ r: 5 }} isAnimationActive={animate()} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
