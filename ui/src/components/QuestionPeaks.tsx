// The "peaks" chart: one peak per question over time. Hover shows the question; click opens it in Conversations.
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { QueryTimeline } from "../api/types";
import { formatMoney, formatMs, formatTime } from "../lib/format";

export type PeakMeasure = "exchanges" | "cost" | "time";

interface Row {
  key: string;
  traceId: string;
  startNs: number;
  endNs?: number;
  label: string;
  value: number;
  question: string;
  exchanges: number;
  modelCalls: number;
  toolCalls: number;
  cost: number | null;
  durationMs: number;
  count: number;
  problem: boolean;
  questions: string[];
}

// The numbers behind each peak, in the unit the person chose.
export function peakRows(timeline: QueryTimeline, measure: PeakMeasure): Row[] {
  return timeline.points.map((point) => {
    const date = new Date(point.start_ns / 1e6);
    const count = point.count ?? 1;
    const base: Omit<Row, "value"> = {
      key: `${point.trace_id}-${point.start_ns}`, traceId: point.trace_id, startNs: point.start_ns, endNs: point.end_ns,
      label: date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }), question: point.question,
      exchanges: point.exchanges, modelCalls: point.model_calls ?? 0, toolCalls: point.tool_calls ?? 0, cost: point.cost_usd ?? null,
      durationMs: point.duration_ms ?? 0, count, problem: point.status === "problem", questions: point.questions ?? [point.question],
    };
    const value = measure === "cost" ? (point.cost_usd ?? 0) : measure === "time" ? (point.duration_ms ?? 0) / 1000 : point.exchanges;
    return { ...base, value };
  });
}

function Tip({ row }: { row: Row }) {
  const many = row.count > 1;
  return (
    <div className="peaks-tip" role="tooltip">
      <div className="peaks-tip-time">{formatTime(row.startNs)}</div>
      {many ? <strong>{row.count} questions in this time slot</strong> : <strong>{row.question || "(no question text)"}</strong>}
      {many && <ul>{row.questions.slice(0, 3).map((q, i) => <li key={i}>{q}</li>)}</ul>}
      <div className="muted">{row.exchanges} exchanges{!many && ` (${row.modelCalls} model call${row.modelCalls === 1 ? "" : "s"}, ${row.toolCalls} tool use${row.toolCalls === 1 ? "" : "s"})`}</div>
      {!many && <div className="muted">{formatMs(row.durationMs)}{row.cost !== null ? ` · ${formatMoney(row.cost)}` : ""}</div>}
      <div className="peaks-tip-hint">Click to open {many ? "the slot" : "this question"}</div>
    </div>
  );
}

export function QuestionPeaks({ timeline, onOpen }: { timeline: QueryTimeline; onOpen: (row: Row) => void }) {
  const [measure, setMeasure] = useState<PeakMeasure>("exchanges");
  const rows = useMemo(() => peakRows(timeline, measure), [timeline, measure]);
  const unit = measure === "cost" ? "dollars" : measure === "time" ? "seconds" : "exchanges";
  return (
    <div>
      <div className="row spread" style={{ marginBottom: 6 }}>
        <span className="muted" style={{ fontSize: 12.5 }}>Each peak is a question. Hover to read it, click to open it.</span>
        <div className="seg" role="group" aria-label="What the height of a peak means">
          {([["exchanges", "Exchanges"], ["cost", "Cost"], ["time", "Time"]] as const).map(([id, label]) => (
            <button key={id} className={measure === id ? "on" : ""} aria-pressed={measure === id} onClick={() => setMeasure(id)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="peaks" role="img" aria-label="Questions over time. Each peak is one question; click a peak to open it.">
        <ResponsiveContainer width="100%" height={230}>
          <BarChart data={rows} margin={{ top: 8, right: 8, left: -10, bottom: 0 }} barCategoryGap="22%">
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" stroke="var(--muted)" fontSize={11} tickLine={false} minTickGap={22} />
            <YAxis stroke="var(--muted)" fontSize={11} allowDecimals={measure !== "exchanges"} tickLine={false} axisLine={false}
              tickFormatter={(v: number) => (measure === "cost" ? formatMoney(v) : String(v))} />
            <Tooltip cursor={{ fill: "var(--hover)" }} wrapperStyle={{ zIndex: 20, outline: "none" }}
              content={({ active, payload }) => (active && payload?.[0] ? <Tip row={payload[0].payload as Row} /> : null)} />
            <Bar dataKey="value" name={unit} radius={[6, 6, 0, 0]} isAnimationActive={false} cursor="pointer"
              onClick={(_: unknown, index: number) => onOpen(rows[index])} minPointSize={3}>
              {rows.map((row) => <Cell key={row.key} fill={row.problem ? "var(--bad)" : "var(--accent)"} fillOpacity={0.8} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
