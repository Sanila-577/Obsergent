// The thread of one question: you, the model, the tools it used, and the answer, as chat bubbles in order.
import { ArrowUpRight, ChevronDown, Wrench } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { ThreadItem } from "../api/types";
import { formatMs, formatTokens } from "../lib/format";
import { useSettings } from "../lib/state";
import { CallCost } from "./Money";
import { JsonView } from "./JsonView";
import { CopyButton, DecisionBadge } from "./ui";

// One line that names who is speaking.
function Who({ item }: { item: ThreadItem }) {
  const { detailed } = useSettings();
  if (item.kind === "question") return <span>You asked</span>;
  if (item.kind === "tool") return <span>Tool</span>;
  return (
    <span className="row" style={{ gap: 8 }}>
      {item.kind === "answer" ? "Answer" : "Model"}
      <Link className="badge model" to={`/models?model=${encodeURIComponent(item.model ?? "")}`} title="About this model">{item.model}</Link>
      {detailed && item.raw_model && item.raw_model !== item.model && <span className="badge outline mono" title="The name the provider recorded">{item.raw_model}</span>}
    </span>
  );
}

// A tool use: header always visible, arguments and result in a collapsible body.
function ToolBlock({ item, traceId, open, onToggle }: { item: ThreadItem; traceId: string; open: boolean; onToggle: () => void }) {
  const failed = item.status === "ERROR";
  return (
    <div className={`thread-tool${failed ? " failed" : ""}`}>
      <button className="thread-tool-head" onClick={onToggle} aria-expanded={open}>
        <Wrench size={14} /><strong>{item.name}</strong>
        {item.server && <span className="muted">on {item.server}</span>}
        <span className="grow" />
        {failed && <span className="badge error">failed</span>}
        {item.decision && <DecisionBadge decision={item.decision} />}
        {item.duration_ms != null && <span className="muted">{formatMs(item.duration_ms)}</span>}
        <ChevronDown size={14} className={open ? "turned" : ""} />
      </button>
      {open && (
        <div className="thread-tool-body">
          <h3>What it was asked</h3><JsonView value={item.arguments} empty="(no input)" />
          <h3>What it returned</h3><JsonView value={item.result} empty="(nothing returned)" />
          {item.mcp_span_id && <Link to={`/conversations?q=${traceId}&tab=steps&span=${item.mcp_span_id}`}><ArrowUpRight size={13} style={{ verticalAlign: "-2px" }} /> See this call in the step-by-step view</Link>}
        </div>
      )}
    </div>
  );
}

export function Thread({ thread, traceId }: { thread: ThreadItem[]; traceId: string }) {
  const { detailed } = useSettings();
  const [current, setCurrent] = useState(0);
  const [openTools, setOpenTools] = useState<Set<number>>(new Set());
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const go = (index: number) => {
    setCurrent(index);
    refs.current[index]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const toggle = (index: number) => setOpenTools((open) => { const next = new Set(open); if (next.has(index)) next.delete(index); else next.add(index); return next; });
  const allOpen = openTools.size === thread.filter((i) => i.kind === "tool").length && openTools.size > 0;
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="thread-rail" aria-label={`Step ${current + 1} of ${thread.length}`}>
        <span className="muted nowrap">Step {current + 1} of {thread.length}</span>
        <div className="thread-segments" role="group" aria-label="Jump to a step">
          {thread.map((item, index) => (
            <button key={index} className={`thread-seg ${item.kind}${index === current ? " on" : ""}${item.status === "ERROR" ? " bad" : ""}`}
              onClick={() => go(index)} title={`${index + 1}. ${item.kind === "tool" ? `tool: ${item.name}` : item.kind === "question" ? "your question" : item.kind}`} aria-label={`Step ${index + 1}`} />
          ))}
        </div>
        <button className="small ghost" onClick={() => setOpenTools(allOpen ? new Set() : new Set(thread.flatMap((item, i) => (item.kind === "tool" ? [i] : []))))}>
          {allOpen ? "Collapse tools" : "Open all tools"}
        </button>
      </div>
      <div className="chat thread">
        {thread.map((item, index) => (
          <div key={index} ref={(el) => { refs.current[index] = el; }} className={`bubble ${item.kind}${index === current ? " current" : ""}`} onClick={() => setCurrent(index)}>
            {item.kind !== "tool" && <div className="role"><Who item={item} /></div>}
            {item.kind === "tool" ? <ToolBlock item={item} traceId={traceId} open={openTools.has(index)} onToggle={() => toggle(index)} />
              : item.text ? <div className="bubble-text">{item.text}</div>
              : <div className="muted">Decided to use {(item.requests ?? []).join(", ") || "a tool"}.</div>}
            {item.kind === "question" || item.kind === "tool" ? null : (
              <div className="bubble-foot muted">
                {item.duration_ms != null && <span>{formatMs(item.duration_ms)}</span>}
                <CallCost cost={item.cost} />
                {detailed && <span>{formatTokens(item.prompt_tokens)} in / {formatTokens(item.completion_tokens)} out</span>}
                {item.status === "ERROR" && <span className="badge error" title={item.message}>failed{item.message ? `: ${item.message.slice(0, 80)}` : ""}</span>}
                {item.kind === "answer" && <CopyButton text={item.text ?? ""} label="Copy answer" />}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
