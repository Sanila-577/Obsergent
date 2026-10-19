// Spending over time: one stacked bar per time slot, one colour per model. Hover = a plain sentence, click = open exactly that slot.
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Spending } from "../api/types";
import { formatMoney } from "../lib/format";
import { colorFor } from "../lib/colors";

interface Props {
  series: Spending["series"];
  models: string[];
  hours: number;
  onSlot: (fromNs: number, toNs: number, model?: string) => void;
}

function label(ns: number, hours: number): string {
  const date = new Date(ns / 1e6);
  return hours <= 24 ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
    : date.toLocaleDateString([], { day: "numeric", month: "short" });
}

export function SpendChart({ series, models, hours, onSlot }: Props) {
  const slot = series.length > 1 ? series[1].start_ns - series[0].start_ns : 3_600_000_000_000;
  const rows = series.map((bucket) => ({ label: label(bucket.start_ns, hours), start_ns: bucket.start_ns, total: bucket.usd, ...bucket.by_model }));
  return (
    <div style={{ height: 240 }} role="img" aria-label="Spending over time, one bar per time slot, coloured by model">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="var(--muted)" fontSize={11} tickLine={false} minTickGap={24} />
          <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false} width={52} tickFormatter={(value: number) => formatMoney(value)} />
          <Tooltip
            cursor={{ fill: "var(--hover)" }}
            contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)" }}
            formatter={(value, name) => [formatMoney(Number(value)), String(name)]}
            labelFormatter={(text) => `Around ${text}: click to see these conversations`}
          />
          {models.map((model) => (
            <Bar key={model} dataKey={model} stackId="spend" fill={colorFor(models, model)} isAnimationActive={false} cursor="pointer"
              onClick={(bar) => onSlot(Number((bar as unknown as { payload: { start_ns: number } }).payload.start_ns), Number((bar as unknown as { payload: { start_ns: number } }).payload.start_ns) + slot, model)} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
