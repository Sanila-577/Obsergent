// Tokens over time, one coloured band per model. Hover = the tokens of each model in that slot; click = open that slot's questions.
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Usage } from "../api/types";
import { colorFor } from "../lib/colors";
import { formatTokens } from "../lib/format";

function label(ns: number, hours: number): string {
  const date = new Date(ns / 1e6);
  return hours <= 24 ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
    : date.toLocaleDateString([], { day: "numeric", month: "short" });
}

export function TokensChart({ series, models, hours, onSlot }: { series: Usage["series"]; models: string[]; hours: number; onSlot: (fromNs: number, toNs: number) => void }) {
  const width = series.length > 1 ? series[1].start_ns - series[0].start_ns : 3_600_000_000_000;
  const rows = series.map((slot) => ({ label: label(slot.start_ns, hours), start_ns: slot.start_ns, ...slot.by_model }));
  const animate = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  return (
    <div style={{ height: 240 }} role="img" aria-label="Tokens over time, coloured by model">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}
          onClick={(state) => { const index = state?.activeTooltipIndex; if (index !== undefined && index !== null && rows[Number(index)]) onSlot(rows[Number(index)].start_ns, rows[Number(index)].start_ns + width); }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="var(--muted)" fontSize={11} tickLine={false} minTickGap={24} />
          <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false} width={48} tickFormatter={formatTokens} />
          <Tooltip cursor={{ stroke: "var(--accent)", strokeDasharray: "4 4" }}
            contentStyle={{ background: "var(--glass-strong)", border: "1px solid var(--glass-border)", borderRadius: 12, color: "var(--text)" }}
            formatter={(value, name) => [`${formatTokens(Number(value))} tokens`, String(name)]} labelFormatter={(text) => `${text} · click to open`} />
          {models.map((model) => (
            <Area key={model} type="monotone" dataKey={model} stackId="tokens" stroke={colorFor(models, model)} fill={colorFor(models, model)} fillOpacity={0.25}
              strokeWidth={2} isAnimationActive={animate} cursor="pointer" />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
