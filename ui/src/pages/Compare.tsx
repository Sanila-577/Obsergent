// Two runs side by side, with the first step where they stopped behaving the same highlighted.
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { JsonView } from "../components/JsonView";
import { Card, EmptyState, PageHead, QueryState } from "../components/ui";
import { PAGES } from "../lib/words";
import { formatMs, formatTime, shortId } from "../lib/format";

export function Compare() {
  const [params, setParams] = useSearchParams();
  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const runs = useQuery({ queryKey: ["runs-for-compare"], queryFn: () => api.traces({ limit: 100 }) });
  const diff = useQuery({ queryKey: ["diff", a, b], queryFn: () => api.diff(a, b), enabled: !!a && !!b });
  const pick = (key: "a" | "b", value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next, { replace: true }); };
  const options = (current: string) => (
    <select value={current} onChange={(e) => pick(current === a ? "a" : "b", e.target.value)} aria-label={current === a ? "Run A" : "Run B"}>
      <option value="">Choose a run…</option>
      {(runs.data ?? []).map((r) => <option key={r.trace_id} value={r.trace_id}>{formatTime(r.start_ns)} · {r.root_name} · {formatMs(r.duration_ms)} · {shortId(r.trace_id)}</option>)}
    </select>
  );

  return (
    <>
      <PageHead title={PAGES.compare.title} about={PAGES.compare.about} />
      <div className="card row wrap" style={{ marginBottom: 14 }}><span className="muted">A</span>{options(a)}<ArrowRight size={14} /><span className="muted">B</span>{options(b)}</div>
      {!a || !b ? <Card><EmptyState title="Choose two conversations">Pick them above, or tick two in the Conversations list and press “Compare these 2”.</EmptyState></Card> : (
        <QueryState query={diff}>{(d) => {
          const length = Math.max(d.steps_a.length, d.steps_b.length);
          const divergence = d.divergence.same ? null : (d.divergence.step ?? 0);
          return (
            <div className="col">
              <Card>{d.divergence.same
                ? <div className="row"><span className="badge ok">same</span> Both conversations used the same {d.divergence.steps} action(s) with the same inputs.</div>
                : <div className="row wrap"><span className="badge high">first difference at action {divergence}</span><strong>{d.divergence.reason}</strong></div>}</Card>
              <div className="grid two">
                {([["A", d.a, d.steps_a], ["B", d.b, d.steps_b]] as const).map(([label, id, steps]) => (
                  <Card key={label} title={<span>Conversation {label} <Link to={`/runs/${id}`} className="mono">{shortId(id)}</Link></span>} flush>
                    {Array.from({ length }, (_, index) => {
                      const step = steps[index];
                      const marked = divergence === index + 1;
                      return (
                        <div key={index} className="finding" style={marked ? { background: "color-mix(in srgb, var(--bad) 10%, transparent)" } : undefined}>
                          <span className="badge outline">{index + 1}</span>
                          {step ? <div className="grow"><strong>{step[0]}</strong><JsonView value={step[1]} empty="(no arguments)" /></div> : <span className="muted">no step {index + 1}</span>}
                        </div>
                      );
                    })}
                  </Card>
                ))}
              </div>
            </div>
          );
        }}</QueryState>
      )}
    </>
  );
}
