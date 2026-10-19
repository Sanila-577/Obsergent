// One run in detail: timeline (waterfall + inspector), conversation, model calls, findings, raw data.
// Loads API data with caching.
import { useQuery } from "@tanstack/react-query";
// Icons.
import { ArrowLeft, Download } from "lucide-react";
// Cache calculations.
import { useMemo } from "react";
// Router: links, navigate(), URL id and ?query parameters.
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
// API functions.
import { api } from "../api/client";
import { ConversationView } from "../components/Conversation";
import { GenerationsTable } from "../components/Generations";
import { JsonView } from "../components/JsonView";
import { SpanInspector } from "../components/SpanInspector";
import { CostRibbon } from "../components/CostRibbon";
import { TotalCost } from "../components/Money";
import { Waterfall } from "../components/Waterfall";
import { Card, CopyButton, EmptyState, ErrorBox, LayerBadge, QueryState, SeverityBadge, Skeleton, Tabs } from "../components/ui";
import { formatCount, formatMs, formatTime, shortId } from "../lib/format";
import { useSettings } from "../lib/state";
import { layerOf, type Layer } from "../lib/trace";

// The five tabs.
type Tab = "timeline" | "conversation" | "model" | "findings" | "raw";

// The page for one run (/runs/<id>).
export function RunDetail() {
  const { detailed } = useSettings();
  // The run id from the URL.
  const { id = "" } = useParams();
  // Change page from code.
  const navigate = useNavigate();
  // The ?tab=...&span=... part of the URL.
  const [params, setParams] = useSearchParams();
  // Which tab is open (default timeline).
  const tab = (params.get("tab") as Tab) || "timeline";
  // Which span is selected (kept in the URL so it can be shared).
  const selectedId = params.get("span");

  // Load the run's spans.
  const trace = useQuery({ queryKey: ["trace", id], queryFn: () => api.trace(id) });
  // Load the chat only when its tab is open.
  const conversation = useQuery({ queryKey: ["conversation", id], queryFn: () => api.conversation(id), enabled: tab === "conversation" });
  // Load model calls only when their tab is open.
  const generations = useQuery({ queryKey: ["generations", id], queryFn: () => api.generations(id), enabled: tab === "model" });

  // Change URL parameters without adding a history entry.
  const setUrl = (changes: Record<string, string | null>) => {
    // Copy the current parameters.
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) { if (value) next.set(key, value); else next.delete(key); }
    // Apply them.
    setParams(next, { replace: true });
  };

  // The loaded spans.
  const spans = trace.data?.spans ?? [];
  // When the run started.
  const runStart = useMemo(() => Math.min(...spans.map((s) => s.start_ns)), [spans]);
  // The selected span object.
  const selected = spans.find((s) => s.span_id === selectedId) ?? null;
  // Which layers appear in this run.
  const layers = useMemo(() => [...new Set(spans.map(layerOf))] as Layer[], [spans]);
  // The earliest span names the run.
  const root = [...spans].sort((a, b) => a.start_ns - b.start_ns)[0];
  // Total duration.
  const totalMs = spans.length ? (Math.max(...spans.map((s) => s.end_ns)) - runStart) / 1e6 : 0;
  // Total tokens of all model calls.
  const tokens = spans.reduce((sum, s) => sum + Number(s.attributes["llm.token_count.total"] ?? 0), 0);
  // Number of failed spans.
  const errors = spans.filter((s) => s.status_code === "ERROR").length;

  // Still loading.
  if (trace.isPending) return <Skeleton lines={6} />;
  // Failed: show the error with a back link.
  if (trace.error) return <><Link to="/runs"><ArrowLeft size={14} /> Conversations</Link><div style={{ marginTop: 12 }}><ErrorBox error={trace.error} /></div></>;
  // Loaded successfully.
  const data = trace.data!;

  return (
    <>
      <div className="row" style={{ marginBottom: 6 }}><Link to="/runs"><ArrowLeft size={14} style={{ verticalAlign: "-2px" }} /> Conversations</Link></div>
      <div className="page-head">
        <h1>{data.question || root?.name || "Run"}</h1>
        {detailed && <span className="muted mono">{shortId(data.trace_id, 12)}</span>}
        {detailed && layers.map((layer) => <LayerBadge key={layer} layer={layer} />)}
        <div className="grow" />
        <CopyButton text={data.trace_id} label="Copy id" />
        <button className="small" onClick={() => navigate(`/compare?a=${data.trace_id}`)}>Compare with…</button>
      </div>
      <div className="row wrap muted" style={{ marginBottom: 16, gap: 18 }}>
        <span>{root && formatTime(root.start_ns)}</span><span>{formatMs(totalMs)} total</span><span>{spans.length} steps</span>
        {data.cost.calls > 0 && <span>Cost: <TotalCost cost={data.cost} /></span>}
        {errors > 0 && <span className="badge error">{errors} problem{errors === 1 ? "" : "s"}</span>}
        {tokens > 0 && <span>{formatCount(tokens)} tokens</span>}
        {data.smells.length > 0 && <span className="badge medium">{data.smells.length} thing{data.smells.length === 1 ? "" : "s"} to check</span>}
      </div>

      {tab === "timeline" && <div style={{ marginBottom: 14 }}><CostRibbon runId={id} onPick={(spanId) => setUrl({ span: spanId })} /></div>}

      <Tabs value={tab} onChange={(next) => setUrl({ tab: next === "timeline" ? null : next })} tabs={[
        { id: "timeline", label: "Step by step" }, { id: "conversation", label: "Chat" }, { id: "model", label: "Model calls" },
        { id: "findings", label: `Things to check${data.smells.length ? ` (${data.smells.length})` : ""}` }, ...(detailed ? [{ id: "raw" as Tab, label: "Raw" }] : [])]} />

      {tab === "timeline" && (
        <div className="run-layout">
          <Card flush><Waterfall spans={spans} smells={data.smells} selectedId={selectedId} onSelect={(spanId) => setUrl({ span: spanId })} /></Card>
          <div className="inspector">
            {selected ? <SpanInspector span={selected} allSpans={spans} runStart={runStart} />
              : <Card><EmptyState title="Pick a step">Click a row to see what it asked for, what came back and, for gateway requests, what the gateway did. <p className="muted"><kbd>j</kbd> / <kbd>k</kbd> move, <kbd>/</kbd> searches.</p></EmptyState></Card>}
          </div>
        </div>
      )}

      {tab === "conversation" && (
        <QueryState query={conversation} empty={{ when: (c) => c.messages.length === 0, title: "No model calls in this run",
          hint: <p>The conversation comes from the agent-side recording (<code>obsergent.sdk.init()</code>). A run recorded only through the proxy has MCP calls but no model messages.</p> }}>
          {(c) => <><div className="row wrap muted" style={{ marginBottom: 12, gap: 16 }}><span>{c.summary.calls} model call(s)</span><span>{c.summary.models.join(", ")}</span><span>{formatCount(c.summary.total_tokens)} tokens</span><span>{formatMs(c.summary.latency_ms)} in the model</span></div><ConversationView messages={c.messages} runId={id} /></>}
        </QueryState>
      )}

      {tab === "model" && (
        <Card flush>
          <QueryState query={generations} empty={{ when: (g) => g.generations.length === 0, title: "No model calls in this run" }}>
            {(g) => <GenerationsTable generations={g.generations} />}
          </QueryState>
        </Card>
      )}

      {tab === "findings" && (
        <Card flush>
          {data.smells.length === 0 ? <EmptyState title="Nothing suspicious in this run">Loops, ignored tool errors and slow tools would show up here.</EmptyState>
            : data.smells.map((smell, index) => (
              <div key={index} className="finding"><span className={`bar ${smell.severity}`} />
                <div className="grow"><div className="row"><SeverityBadge severity={smell.severity} /><strong>{smell.type.replace("_", " ")}</strong></div><div>{smell.message}</div></div>
                {smell.span_id && <button className="small" onClick={() => setUrl({ tab: null, span: smell.span_id! })}>Show span</button>}</div>))}
        </Card>
      )}

      {tab === "raw" && detailed && (
        <Card title="Raw run data" actions={<div className="row"><CopyButton text={JSON.stringify(data, null, 2)} label="Copy JSON" />
          <a className="btn small" download={`run-${shortId(data.trace_id)}.json`} href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(data, null, 2))}`}><Download size={13} /> Download</a></div>}>
          <JsonView value={data} />
        </Card>
      )}
    </>
  );
}
