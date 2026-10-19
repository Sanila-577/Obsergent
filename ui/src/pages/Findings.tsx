// Things worth a look: drift, risky tools, injection-like text, agent smells, refused gateway calls.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Finding, Severity } from "../api/types";
import { Card, EmptyState, PageHead, QueryState, Segmented, SeverityBadge } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useLiveInterval } from "../lib/state";
import { FINDING_WORDS, PAGES } from "../lib/words";

const TYPE_LABEL: Record<string, string> = {
  tool_changed: "tool description changed", tool_added: "tool added", tool_removed: "tool removed", risky_tool: "risky tool",
  prompt_injection: "injection-like text", loop: "loop", tool_error: "tool error", slow_tool: "slow tool", gateway_decision: "refused by gateway",
};

export function Findings() {
  const client = useQueryClient();
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [type, setType] = useState("");
  const [showAcknowledged, setShowAcknowledged] = useState(false);
  const findings = useQuery({ queryKey: ["findings", showAcknowledged], queryFn: () => api.findings({ include_acknowledged: showAcknowledged }), refetchInterval: useLiveInterval() });

  // Acknowledge / restore: update the list immediately, then let the server confirm.
  const toggle = useMutation({
    mutationFn: (f: Finding) => (f.acknowledged ? api.unacknowledge(f.id) : api.acknowledge(f.id)),
    onMutate: async (f) => {
      await client.cancelQueries({ queryKey: ["findings"] });
      client.setQueryData<Finding[]>(["findings", showAcknowledged], (rows) => rows?.flatMap((row) => row.id !== f.id ? [row] : showAcknowledged ? [{ ...row, acknowledged: !row.acknowledged }] : []));
    },
    onSettled: () => { client.invalidateQueries({ queryKey: ["findings"] }); client.invalidateQueries({ queryKey: ["overview"] }); },
  });

  return (
    <>
      <PageHead title={PAGES.findings.title} about={PAGES.findings.about}>
        <Segmented value={severity} onChange={setSeverity} options={[{ id: "all", label: "All" }, { id: "high", label: "Important" }, { id: "medium", label: "Worth a look" }, { id: "low", label: "Minor" }]} />
        <label className="check"><input type="checkbox" checked={showAcknowledged} onChange={(e) => setShowAcknowledged(e.target.checked)} /> Show dismissed</label>
      </PageHead>
      <QueryState query={findings} empty={{ when: (f) => f.length === 0, title: "Nothing to check yet", hint: <p>Either nothing has been recorded yet, or everything recorded looks fine: no changed tools, loops, failures or blocked requests.</p> }}>
        {(all) => {
          const types = [...new Set(all.map((f) => f.type))];
          const rows = all.filter((f) => (severity === "all" || f.severity === severity) && (!type || f.type === type));
          return (
            <div className="col">
              <div className="row wrap">
                {(["high", "medium", "low"] as Severity[]).map((s) => <span key={s} className={`badge ${s}`}>{all.filter((f) => f.severity === s && !f.acknowledged).length} {s === "high" ? "important" : s === "medium" ? "worth a look" : "minor"}</span>)}
                <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Type"><option value="">All kinds</option>{types.map((t) => <option key={t} value={t}>{FINDING_WORDS[t] ?? TYPE_LABEL[t] ?? t}</option>)}</select>
              </div>
              <Card flush>
                {rows.length === 0 ? <EmptyState title="Nothing matches these filters" /> : rows.map((f) => (
                  <div key={f.id} className={`finding${f.acknowledged ? " acked" : ""}`}>
                    <span className={`bar ${f.severity}`} />
                    <div className="grow">
                      <div className="row wrap"><SeverityBadge severity={f.severity} /><strong>{FINDING_WORDS[f.type] ?? TYPE_LABEL[f.type] ?? f.type}</strong>{f.count > 1 && <span className="badge outline">×{f.count}</span>}<span className="muted">{timeAgo(f.seen_ns)}</span></div>
                      <div style={{ margin: "4px 0" }}>{f.message}</div>
                      <div className="row wrap" style={{ gap: 14 }}>
                        {f.trace_id && <Link to={`/runs/${f.trace_id}${f.span_id ? `?span=${f.span_id}` : ""}`}>Open the conversation →</Link>}
                        {f.server && <Link to={`/servers?server=${f.server}`}>Tool server {f.server} →</Link>}
                        {f.type === "gateway_decision" && <Link to="/gateway">Gateway guard →</Link>}
                      </div>
                    </div>
                    <button className="small" onClick={() => toggle.mutate(f)}>{f.acknowledged ? <><Undo2 size={13} /> Restore</> : <><Check size={13} /> Dismiss</>}</button>
                  </div>))}
              </Card>
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
