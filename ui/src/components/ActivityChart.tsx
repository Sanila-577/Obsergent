// Tool calls over time, with the failing ones drawn on top in red.
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Overview } from "../api/types";

export function ActivityChart({ data, hours }: { data: Overview["activity"]; hours: number }) {
  const rows = data.map((bucket) => {
    const date = new Date(bucket.start_ns / 1e6);
    const label = hours <= 24 ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
      : date.toLocaleDateString([], { day: "numeric", month: "short" });
    return { label, ok: bucket.calls - bucket.errors, errors: bucket.errors };
  });
  return (
    <div style={{ height: 210 }} role="img" aria-label="Tool calls over time">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="var(--muted)" fontSize={11} tickLine={false} minTickGap={24} />
          <YAxis stroke="var(--muted)" fontSize={11} allowDecimals={false} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)" }} />
          <Area type="monotone" dataKey="ok" name="successful calls" stackId="1" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.25} isAnimationActive={false} />
          <Area type="monotone" dataKey="errors" name="failed calls" stackId="1" stroke="var(--bad)" fill="var(--bad)" fillOpacity={0.5} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
