// The thread of one question: you on the right, the AI on the left (its replies and the tools it used), each step with its tokens.
import { ArrowUpRight, ChevronDown } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { ThreadItem } from "../api/types";
import { formatMs, formatTokens } from "../lib/format";
import { useSettings } from "../lib/state";
import { HELP } from "../lib/words";
import { ModelChip } from "./HoverCard";
import { CallCost } from "./Money";
import { JsonView } from "./JsonView";
import { SideIcon } from "./Sides";
import { CopyButton, DecisionBadge, Segmented } from "./ui";

/** The size of a step in tokens: exact for model calls, "≈" (estimated from the text length) for your message and tool results. */
export function stepTokens(item: ThreadItem): number {
  return (item.tokens?.input ?? 0) + (item.tokens?.output ?? 0);
}

function TokenTag({ item }: { item: ThreadItem }) {
  const t = item.tokens;
  if (!t) return null;
  if (!t.exact) return <span className="token-tag estimated" title={HELP.estimated}>≈ {formatTokens(t.input)} tokens</span>;
  return (
    <span className="token-tag" title={`${t.input} tokens read · ${t.output} written${t.cached ? ` · ${t.cached} from the cache` : ""}${t.reasoning ? ` · ${t.reasoning} reasoning` : ""}`}>
      {formatTokens(t.input + t.output)} tokens <span className="muted">({formatTokens(t.input)} in · {formatTokens(t.output)} out)</span>
    </span>
  );
}

// A tool use: header always visible, input and result in a collapsible body.
function ToolBlock({ item, traceId, open, onToggle }: { item: ThreadItem; traceId: string; open: boolean; onToggle: () => void }) {
  const failed = item.status === "ERROR";
  return (
    <div className={`thread-tool${failed ? " failed" : ""}`}>
      <button className="thread-tool-head" onClick={onToggle} aria-expanded={open}>
        <SideIcon side="tool" size={12} /><strong>{item.name}</strong>
        {item.server && <span className="muted">on {item.server}</span>}
        <span className="grow" />
        {failed && <span className="badge error">failed</span>}
        {item.decision && <DecisionBadge decision={item.decision} />}
        <TokenTag item={item} />
        {item.duration_ms != null && <span className="muted">{formatMs(item.duration_ms)}</span>}
        <ChevronDown size={14} className={open ? "turned" : ""} />
      </button>
      {open && (
        <div className="thread-tool-body">
          <h3>Input</h3><JsonView value={item.arguments} empty="(no input)" />
          <h3>Result</h3><JsonView value={item.result} empty="(nothing returned)" />
          {item.mcp_span_id && <Link to={`/conversations?q=${traceId}&tab=timeline&span=${item.mcp_span_id}`}><ArrowUpRight size={13} style={{ verticalAlign: "-2px" }} /> Show in the timeline</Link>}
        </div>
      )}
    </div>
  );
}

export function Thread({ thread, traceId }: { thread: ThreadItem[]; traceId: string }) {
  const { detailed } = useSettings();
  const [current, setCurrent] = useState(0);
  const [openTools, setOpenTools] = useState<Set<number>>(new Set());
  const [rail, setRail] = useState<"steps" | "tokens">("steps");
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const go = (index: number) => {
    setCurrent(index);
    refs.current[index]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const toggle = (index: number) => setOpenTools((open) => { const next = new Set(open); if (next.has(index)) next.delete(index); else next.add(index); return next; });
  const tools = thread.flatMap((item, i) => (item.kind === "tool" ? [i] : []));
  const allOpen = tools.length > 0 && openTools.size === tools.length;
  const human = thread.filter((item) => item.side === "human").length;
  const ai = thread.length - human;
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="sides-bar" aria-label={`${thread.length} steps: ${human} from you, ${ai} from the AI`}>
        <span className="sides-end ai"><SideIcon side="ai" /> <strong>{ai}</strong> AI</span>
        <span className="sides-line" /><span className="sides-total">{thread.length} steps</span><span className="sides-line" />
        <span className="sides-end human"><strong>{human}</strong> you <SideIcon side="human" /></span>
      </div>
      <div className="thread-rail">
        <span className="muted nowrap">Step {current + 1} of {thread.length}</span>
        <div className="thread-segments" role="group" aria-label="Jump to a step">
          {thread.map((item, index) => (
            <button key={index} className={`thread-seg ${item.kind}${index === current ? " on" : ""}${item.status === "ERROR" ? " bad" : ""}`}
              style={rail === "tokens" ? { flexGrow: Math.max(1, stepTokens(item)) } : undefined}
              onClick={() => go(index)} title={`${index + 1}. ${item.kind === "tool" ? `tool: ${item.name}` : item.kind === "question" ? "you" : "AI"} · ${item.tokens?.exact ? "" : "≈ "}${formatTokens(stepTokens(item))} tokens`}
              aria-label={`Step ${index + 1}`} />
          ))}
        </div>
        <Segmented value={rail} onChange={setRail} options={[{ id: "steps", label: "Steps" }, { id: "tokens", label: "By tokens" }]} />
        {tools.length > 0 && <button className="small ghost" onClick={() => setOpenTools(allOpen ? new Set() : new Set(tools))}>{allOpen ? "Close tools" : "Open tools"}</button>}
      </div>
      <div className="chat thread">
        {thread.map((item, index) => (
          <div key={index} ref={(el) => { refs.current[index] = el; }} className={`bubble-row ${item.side}`}>
            {item.side === "ai" && <SideIcon side={item.kind === "tool" ? "tool" : "ai"} />}
            <div className={`bubble ${item.kind} ${item.side}${index === current ? " current" : ""}`} onClick={() => setCurrent(index)}>
              {item.kind === "tool" ? <ToolBlock item={item} traceId={traceId} open={openTools.has(index)} onToggle={() => toggle(index)} /> : (
                <>
                  {item.side === "ai" && <div className="role">{item.kind === "answer" ? "Answer" : "Model"} <ModelChip name={item.model ?? ""} />
                    {detailed && item.raw_model && item.raw_model !== item.model && <span className="badge outline mono">{item.raw_model}</span>}</div>}
                  {item.text ? <div className="bubble-text">{item.text}</div> : <div className="muted">Used {(item.requests ?? []).join(", ") || "a tool"}</div>}
                  <div className="bubble-foot muted">
                    <TokenTag item={item} />
                    {item.side === "ai" && item.duration_ms != null && <span>{formatMs(item.duration_ms)}</span>}
                    {item.side === "ai" && <CallCost cost={item.cost} />}
                    {item.status === "ERROR" && <span className="badge error" title={item.message}>failed</span>}
                    {item.kind === "answer" && <CopyButton text={item.text ?? ""} label="Copy" />}
                  </div>
                </>
              )}
            </div>
            {item.side === "human" && <SideIcon side="human" />}
          </div>
        ))}
      </div>
    </div>
  );
}
