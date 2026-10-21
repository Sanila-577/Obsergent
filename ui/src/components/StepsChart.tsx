// The Overview's line chart: one point per question over time (steps by default; tokens, cost or time on request).
// Hover shows the question with its steps, tokens and cost; a click (or Enter on the focused point) opens it.
import { useEffect, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { QueryTimeline } from "../api/types";
import { formatMoney, formatMs, formatTime, formatTokens } from "../lib/format";
import { SideCounts } from "./Sides";

export type Measure = "steps" | "tokens" | "cost" | "time";

export interface ChartRow {
  key: string;
  traceId: string;
  startNs: number;
  endNs?: number;
  label: string;
  value: number;
  question: string;
  steps: number;
  human: number;
  ai: number;
  modelCalls: number;
  toolCalls: number;
  tokensIn: number;
  tokensOut: number;
  cost: number | null;
  durationMs: number;
  models: string[];
  tools: string[];
  count: number;
  problem: boolean;
  questions: string[];
}

/** The rows behind the chart, in the unit the person chose. */
export function chartRows(timeline: QueryTimeline, measure: Measure): ChartRow[] {
  return timeline.points.map((point) => {
    const tokens = point.tokens ?? { input: 0, output: 0, total: 0 };
    const value = measure === "tokens" ? tokens.total : measure === "cost" ? point.cost_usd ?? 0
      : measure === "time" ? point.duration_ms / 1000 : point.steps;
    return {
      key: `${point.trace_id}-${point.start_ns}`, traceId: point.trace_id, startNs: point.start_ns, endNs: point.end_ns,
      label: new Date(point.start_ns / 1e6).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }),
      value, question: point.question, steps: point.steps, human: point.human_messages, ai: point.ai_messages,
      modelCalls: point.model_calls, toolCalls: point.tool_calls, tokensIn: tokens.input, tokensOut: tokens.output,
      cost: point.cost_usd, durationMs: point.duration_ms, models: point.models ?? [], tools: point.tools ?? [],
      count: point.count ?? 1, problem: point.status === "problem", questions: point.questions ?? [point.question],
    };
  });
}

// What a value looks like on the axis and in words.
const FORMAT: Record<Measure, (n: number) => string> = {
  steps: (n) => String(Math.round(n)), tokens: formatTokens, cost: formatMoney, time: (n) => `${n.toFixed(n < 10 ? 1 : 0)} s`,
};

export function PointCard({ row }: { row: ChartRow }) {
  const many = row.count > 1;
  return (
    <div className="peaks-tip" role="tooltip">
      <div className="peaks-tip-time">{formatTime(row.startNs)}{many ? ` · ${row.count} questions` : ""}</div>
      <strong>{many ? row.questions.slice(0, 2).join(" · ") : row.question || "(no question text)"}</strong>
      <div className="tip-grid">
        <span>Steps</span><span><SideCounts human={row.human} ai={row.ai} /></span>
        <span>Tokens</span><span>{formatTokens(row.tokensIn + row.tokensOut)} <span className="muted">({formatTokens(row.tokensIn)} in · {formatTokens(row.tokensOut)} out)</span></span>
        <span>Cost</span><span>{row.cost === null ? "-" : formatMoney(row.cost)}</span>
        <span>Took</span><span>{formatMs(row.durationMs)}</span>
        {!many && row.models.length > 0 && <><span>Model</span><span>{row.models.join(", ")}</span></>}
        {!many && row.tools.length > 0 && <><span>Tools</span><span>{row.tools.join(", ")}</span></>}
      </div>
      <div className="peaks-tip-hint">{row.problem ? "Had a problem · " : ""}Click to open</div>
    </div>
  );
}

/** One point of the drawn trend: the line rests at zero and rises to a rounded peak around each question. */
export interface TrendPoint {
  t: number;
  value: number;
  /** The question whose peak this point is part of, so hovering anywhere on a peak shows that question. */
  owner: ChartRow | null;
  /** True for the top of a peak (the moment the question was asked). */
  spike: boolean;
}

// How wide a peak is at most (each side, as a share of the axis), how much of the gap to a neighbour it may use, and how many
// points draw one side of a peak.
const MAX_HALF_WIDTH = 1 / 28;
const GAP_SHARE = 0.42;
const SIDE_POINTS = 14;

/** Spread the questions over the axis: flat at zero, and a rounded peak at each question as high as its value.
 * Each side of a peak is at most `MAX_HALF_WIDTH` of the axis and never more than `GAP_SHARE` of the gap to the nearest question,
 * so the line always comes back down to zero between two questions. */
export function trendPoints(rows: ChartRow[], startMs: number, endMs: number): TrendPoint[] {
  const span = Math.max(1, endMs - startMs);
  const tops = [...rows].sort((a, b) => a.startNs - b.startNs).map((row) => ({ row, t: row.startNs / 1e6 }));
  const points: TrendPoint[] = [{ t: startMs, value: 0, owner: null, spike: false }];
  tops.forEach(({ row, t }, index) => {
    const gapBefore = index > 0 ? t - tops[index - 1].t : Infinity;
    const gapAfter = index < tops.length - 1 ? tops[index + 1].t - t : Infinity;
    // Both sides equally wide, so every peak is symmetric; the closer neighbour decides how wide it may be.
    const left = Math.max(1, Math.min(span * MAX_HALF_WIDTH, Math.min(gapBefore, gapAfter) * GAP_SHARE));
    const right = left;
    // A smooth bump: value x cos^2 from the foot (0) to the top (1) and back.
    const bump = (share: number) => row.value * Math.cos((Math.PI / 2) * share) ** 2;
    for (let i = SIDE_POINTS; i >= 1; i--) points.push({ t: t - (left * i) / SIDE_POINTS, value: bump(i / SIDE_POINTS), owner: row, spike: false });
    points.push({ t, value: row.value, owner: row, spike: true });
    for (let i = 1; i <= SIDE_POINTS; i++) points.push({ t: t + (right * i) / SIDE_POINTS, value: bump(i / SIDE_POINTS), owner: row, spike: false });
  });
  points.push({ t: Math.max(endMs, points[points.length - 1].t), value: 0, owner: null, spike: false });
  return points;
}

function tick(ms: number, spanMs: number): string {
  const date = new Date(ms);
  return spanMs <= 36 * 3600_000 ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
    : date.toLocaleDateString([], { day: "numeric", month: "short" });
}

const ALL_MEASURES: Measure[] = ["steps", "tokens", "cost", "time"];

/** The peak trend chart: the Overview shows it with a Steps | Tokens | Cost | Time switch, the Usage & cost page with one measure. */
export function StepsChart({ timeline, hours, onOpen, measures = ALL_MEASURES }: {
  timeline: QueryTimeline; hours: number; onOpen: (row: ChartRow) => void; measures?: Measure[];
}) {
  const [chosen, setMeasure] = useState<Measure>(measures[0]);
  const measure = measures.includes(chosen) ? chosen : measures[0];
  const [focus, setFocus] = useState<number | null>(null);
  const rows = useMemo(() => [...chartRows(timeline, measure)].sort((a, b) => a.startNs - b.startNs), [timeline, measure]);
  // The axis covers only the questions: from a little before the first to a little after the last (the empty time before and after
  // is left out), so each question gets a clear peak.
  const [startMs, endMs] = useMemo(() => {
    const now = Date.now();
    if (!rows.length) return [now - hours * 3600_000, now];
    const first = rows[0].startNs / 1e6;
    const last = rows[rows.length - 1].startNs / 1e6;
    const padding = Math.max(60_000, (last - first) * 0.12);
    return [Math.max(now - hours * 3600_000, first - padding), last + padding];
  }, [rows, hours]);
  const points = useMemo(() => trendPoints(rows, startMs, endMs), [rows, startMs, endMs]);
  const average = rows.length ? rows.reduce((sum, row) => sum + row.value, 0) / rows.length : 0;
  const focusRow = focus !== null ? rows[focus] : null;
  // The line draws itself in once when the chart first appears; later updates (new questions) show at once, without animation.
  const [firstDraw, setFirstDraw] = useState(true);
  useEffect(() => { const timer = setTimeout(() => setFirstDraw(false), 1600); return () => clearTimeout(timer); }, []);
  const animate = firstDraw && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const onKey = (event: React.KeyboardEvent) => {
    if (!rows.length) return;
    if (event.key === "ArrowRight") { event.preventDefault(); setFocus((i) => Math.min(rows.length - 1, (i ?? -1) + 1)); }
    else if (event.key === "ArrowLeft") { event.preventDefault(); setFocus((i) => Math.max(0, (i ?? rows.length) - 1)); }
    else if (event.key === "Enter" && focusRow) onOpen(focusRow);
    else if (event.key === "Escape") setFocus(null);
  };
  // A flat line at zero says nothing: say it in words (e.g. every question ran on a free local model).
  if (rows.length && rows.every((row) => row.value === 0) && measures.length === 1) {
    return <p className="flat-note">{measure === "cost" ? "Every question in this period cost $0: the model runs on your own computer, or no price is known."
      : `Every question in this period has 0 ${measure}.`}</p>;
  }
  return (
    <div>
      <div className="row spread chart-head" style={{ marginBottom: 6 }}>
        <span className="muted chart-legend"><i className="dot ok" /> question <i className="dot problem" /> had a problem <i className="avg-swatch" /> average</span>
        {measures.length > 1 && <div className="seg" role="group" aria-label="What the line shows">
          {measures.map((id) => (
            <button key={id} className={measure === id ? "on" : ""} aria-pressed={measure === id} onClick={() => setMeasure(id)}>{id[0].toUpperCase() + id.slice(1)}</button>
          ))}
        </div>}
      </div>
      <div className="steps-chart" role="img" tabIndex={0} onKeyDown={onKey} onBlur={() => setFocus(null)}
        aria-label={`Questions over time: a spike for each question, as high as its ${measure}. Use the arrow keys to move between questions and Enter to open one.`}>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={points} margin={{ top: 12, right: 12, left: -6, bottom: 0 }}
            onClick={(state) => { const index = state?.activeTooltipIndex; const owner = index !== undefined && index !== null ? points[Number(index)]?.owner : null; if (owner) onOpen(owner); }}>
            <defs>
              <linearGradient id="steps-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.5} /><stop offset="100%" stopColor="var(--accent)" stopOpacity={0.04} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={[startMs, endMs]} stroke="var(--muted)" fontSize={11} tickLine={false}
              tickCount={7} minTickGap={48} tickFormatter={(ms: number) => tick(ms, endMs - startMs)} />
            <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false} allowDecimals={measure !== "steps"} tickFormatter={FORMAT[measure]} width={52} />
            <ReferenceLine y={average} stroke="var(--muted)" strokeDasharray="5 5" ifOverflow="extendDomain" />
            <Tooltip cursor={{ stroke: "var(--accent)", strokeDasharray: "4 4" }} wrapperStyle={{ zIndex: 20, outline: "none" }}
              content={({ active, payload }) => {
                const owner = active ? (payload?.[0]?.payload as TrendPoint | undefined)?.owner : null;
                return owner ? <PointCard row={owner} /> : null;
              }} />
            <Area type="monotone" dataKey="value" baseValue={0} stroke="none" fill="url(#steps-fill)" isAnimationActive={animate} />
            <Line type="monotone" dataKey="value" name={measure} stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" cursor="pointer" isAnimationActive={animate}
              dot={(props: { cx?: number; cy?: number; index?: number }) => {
                const point = points[props.index ?? 0];
                if (!point?.spike || !point.owner) return <g key={props.index} />;
                const focused = focusRow === point.owner;
                return <circle key={props.index} cx={props.cx} cy={props.cy} r={focused ? 7 : 4.5}
                  className={`chart-dot${point.owner.problem ? " problem" : ""}${focused ? " focused" : ""}`} />;
              }}
              activeDot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {focusRow && <div className="chart-focus" aria-live="polite"><PointCard row={focusRow} /></div>}
    </div>
  );
}
