// Every model call of a run: model, tokens, latency, and what it saw and answered.
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { Generation } from "../api/types";
import { formatCount, formatMs, formatTime } from "../lib/format";
import { CallCost } from "./Money";
import { JsonView } from "./JsonView";

export function GenerationsTable({ generations }: { generations: Generation[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <table>
      <thead><tr><th style={{ width: 24 }} /><th>When</th><th>Model</th><th className="num">Prompt tokens</th><th className="num">Completion</th><th className="num">Latency</th><th className="num">Cost</th><th>Asked for</th></tr></thead>
      <tbody>
        {generations.map((g) => (
          <>
            <tr key={g.span_id} className="click" onClick={() => setOpen(open === g.span_id ? null : g.span_id)}>
              <td>{open === g.span_id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
              <td className="nowrap">{formatTime(g.start_ns)}</td>
              <td>{g.model ?? g.span_name}{g.provider && <span className="muted"> · {g.provider}</span>}</td>
              <td className="num">{formatCount(g.prompt_tokens)}</td><td className="num">{formatCount(g.completion_tokens)}</td>
              <td className="num">{formatMs(g.latency_ms)}</td>
              <td className="num"><CallCost cost={g.cost} /></td>
              <td>{g.output_messages.flatMap((m) => m.tool_calls.map((c) => c.name)).map((name, i) => <span key={i} className="badge proxy" style={{ marginRight: 4 }}>{name}</span>)}
                {!g.output_messages.some((m) => m.tool_calls.length) && <span className="muted">final answer</span>}</td>
            </tr>
            {open === g.span_id && (
              <tr key={`${g.span_id}-detail`}><td /><td colSpan={7}>
                <div className="grid two">
                  <div><h3>Input ({g.input_messages.length} messages)</h3><JsonView value={g.input_messages} /></div>
                  <div><h3>Output</h3><JsonView value={g.output_messages} /><h3 style={{ marginTop: 12 }}>Parameters</h3><JsonView value={g.parameters} empty="(defaults)" /></div>
                </div>
              </td></tr>
            )}
          </>
        ))}
      </tbody>
    </table>
  );
}
