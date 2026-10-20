import { describe, expect, it } from "vitest";
import type { QueryTimeline, ThreadItem } from "../api/types";
import { chartRows, trendPoints } from "./StepsChart";
import { stepTokens } from "./Thread";

const timeline: QueryTimeline = {
  mode: "questions",
  points: [{
    trace_id: "a", start_ns: 1_700_000_000_000_000_000, question: "Which books?", steps: 7, human_messages: 1, ai_messages: 6,
    model_calls: 3, tool_calls: 3, tokens: { input: 3100, output: 300, cached: 0, reasoning: 0, total: 3400 }, cost_usd: 0.01,
    duration_ms: 4200, status: "ok",
  }],
};

describe("the steps chart", () => {
  it("plots steps, tokens, cost or time, and keeps every detail for the hover card", () => {
    expect(chartRows(timeline, "steps")[0].value).toBe(7);
    expect(chartRows(timeline, "tokens")[0].value).toBe(3400);
    expect(chartRows(timeline, "cost")[0].value).toBe(0.01);
    expect(chartRows(timeline, "time")[0].value).toBe(4.2);
    const row = chartRows(timeline, "steps")[0];
    expect([row.human, row.ai, row.tokensIn, row.tokensOut]).toEqual([1, 6, 3100, 300]);
  });
});

describe("the trend line", () => {
  it("rests at zero and rises to a rounded peak at each question, over the whole window", () => {
    const rows = chartRows(timeline, "steps");
    const at = rows[0].startNs / 1e6;
    const points = trendPoints(rows, at - 3600_000, at + 600_000);
    expect(points[0]).toMatchObject({ t: at - 3600_000, value: 0 });
    expect(points[points.length - 1]).toMatchObject({ t: at + 600_000, value: 0 });
    const tops = points.filter((p) => p.spike);
    expect(tops).toHaveLength(1);
    expect(tops[0]).toMatchObject({ t: at, value: 7 });
    // the peak is wide and smooth: it rises and falls over many points, all belonging to the question
    const peak = points.filter((p) => p.value > 0);
    expect(peak.length).toBeGreaterThan(10);
    expect(peak.every((p) => p.owner?.traceId === "a")).toBe(true);
    const before = peak.filter((p) => p.t < at).map((p) => p.value);
    expect(before).toEqual([...before].sort((x, y) => x - y)); // rising towards the top
  });

  it("keeps each peak's real height and comes down to zero between two close questions", () => {
    const [row] = chartRows(timeline, "steps");
    const other = { ...row, traceId: "b", startNs: row.startNs + 60_000_000_000, value: 3 };
    const at = row.startNs / 1e6;
    const points = trendPoints([row, other], at - 3600_000, at + 600_000);
    expect(points.filter((p) => p.spike).map((p) => p.value)).toEqual([7, 3]);
    // between the two peaks the line touches zero (each side uses less than half of the gap)
    const between = points.filter((p) => p.t > at && p.t < at + 60_000);
    expect(Math.min(...between.map((p) => p.value))).toBeLessThan(1e-9);
    expect(points.map((p) => p.t)).toEqual([...points.map((p) => p.t)].sort((x, y) => x - y)); // always left to right
  });
});

describe("a step's tokens", () => {
  it("adds what was read and written", () => {
    expect(stepTokens({ kind: "model", side: "ai", start_ns: 0, tokens: { input: 243, output: 20, exact: true } } as ThreadItem)).toBe(263);
    expect(stepTokens({ kind: "tool", side: "ai", start_ns: 0, tokens: { input: 35, output: 0, exact: false } } as ThreadItem)).toBe(35);
  });
});
