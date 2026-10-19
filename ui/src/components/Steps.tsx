// The step-by-step timeline of one question (the waterfall and the inspector), loaded by trace id.
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../api/client";
import type { TraceDetail } from "../api/types";
import { CostRibbon } from "./CostRibbon";
import { SpanInspector } from "./SpanInspector";
import { Waterfall } from "./Waterfall";
import { Card, EmptyState, QueryState } from "./ui";

export function Steps({ traceId, spanId, onSpan }: { traceId: string; spanId: string | null; onSpan: (spanId: string) => void }) {
  const trace = useQuery({ queryKey: ["trace", traceId], queryFn: () => api.trace(traceId) });
  return (
    <QueryState query={trace}>
      {(data) => <StepsBody data={data} traceId={traceId} spanId={spanId} onSpan={onSpan} />}
    </QueryState>
  );
}

function StepsBody({ data, traceId, spanId, onSpan }: { data: TraceDetail; traceId: string; spanId: string | null; onSpan: (spanId: string) => void }) {
  const spans = data.spans;
  const runStart = useMemo(() => Math.min(...spans.map((s) => s.start_ns)), [spans]);
  const selected = spans.find((s) => s.span_id === spanId) ?? null;
  return (
    <div className="col">
      <CostRibbon runId={traceId} onPick={onSpan} />
      <div className="run-layout">
        <Card flush><Waterfall spans={spans} smells={data.smells} selectedId={spanId} onSelect={onSpan} /></Card>
        <div className="inspector">
          {selected ? <SpanInspector span={selected} allSpans={spans} runStart={runStart} />
            : <Card><EmptyState title="Pick a step">Click a row to see what it asked for, what came back and, for gateway requests, what the gateway did.</EmptyState></Card>}
        </div>
      </div>
    </div>
  );
}
