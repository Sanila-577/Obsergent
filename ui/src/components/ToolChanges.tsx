// What changed in an MCP server's tool list over time (rug-pull detection), and a comparison between two servers.
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ToolListDiff } from "../api/types";
import { DiffText } from "./DiffText";
import { JsonView } from "./JsonView";
import { Card, EmptyState, QueryState, SeverityBadge } from "./ui";
import { formatTime, timeAgo } from "../lib/format";

export function DiffView({ diff, labelA, labelB }: { diff: ToolListDiff; labelA: string; labelB: string }) {
  if (diff.same) return <EmptyState title="Identical">{labelA} and {labelB} offer exactly the same tools, descriptions and inputs.</EmptyState>;
  return (
    <div className="col">
      {diff.added.length > 0 && <div><h3>Only in {labelB}</h3><div className="row wrap">{diff.added.map((t) => <span key={t} className="badge ok">+ {t}</span>)}</div></div>}
      {diff.removed.length > 0 && <div><h3>Only in {labelA}</h3><div className="row wrap">{diff.removed.map((t) => <span key={t} className="badge error">− {t}</span>)}</div></div>}
      {diff.changed.map((change) => (
        <div key={change.tool} className="card" style={{ background: "var(--panel-2)" }}>
          <div className="row" style={{ marginBottom: 8 }}><strong>{change.tool}</strong>
            {change.description_changed && <span className="badge high">description changed</span>}{change.schema_changed && <span className="badge medium">inputs changed</span>}</div>
          {change.description_changed && <DiffText segments={change.description.diff} />}
          {change.schema_changed && <div className="grid two" style={{ marginTop: 10 }}><div><h3>{labelA}</h3><JsonView value={change.schema.before} /></div><div><h3>{labelB}</h3><JsonView value={change.schema.after} /></div></div>}
        </div>
      ))}
    </div>
  );
}

export function ToolChanges({ current, names }: { current: string; names: string[] }) {
  const [params, setParams] = useSearchParams();
  const other = params.get("vs") ?? "";
  const setParam = (key: string, value: string | null) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next, { replace: true }); };
  const snapshots = useQuery({ queryKey: ["snapshots", current], queryFn: () => api.snapshots(current), enabled: !!current, retry: false });
  const fromId = params.get("from") ? Number(params.get("from")) : undefined;
  const toId = params.get("to") ? Number(params.get("to")) : undefined;
  const diff = useQuery({ queryKey: ["server-diff", current, fromId, toId], queryFn: () => api.serverDiff(current, fromId, toId), enabled: !!snapshots.data && snapshots.data.snapshots.length > 1 });
  const compare = useQuery({ queryKey: ["server-compare", current, other], queryFn: () => api.serverCompare(current, other), enabled: !!current && !!other, retry: false });
  const list = snapshots.data?.snapshots ?? [];
  return (
    <div className="col">
      <Card title="Has this MCP server changed?">
        {snapshots.error ? <EmptyState title="No tool list recorded for this server yet">It is saved the first time a client asks the server for its tools (<code>tools/list</code>) through the proxy.</EmptyState>
          : <QueryState query={snapshots}>{(s) => (
            <div className="col">
              <div className="row wrap">{s.snapshots.map((snap, i) => <span key={snap.id} className="badge outline" title={formatTime(snap.first_seen_ns)}>v{i + 1} · {snap.tools.length} tools · {timeAgo(snap.first_seen_ns)}</span>)}</div>
              {s.drift.length > 0 && <div>{s.drift.map((d, i) => <div key={i} className="row" style={{ marginBottom: 4 }}><SeverityBadge severity={d.severity} /> {d.message}</div>)}</div>}
              {list.length > 1 ? (
                <>
                  <div className="row wrap"><span className="muted">Compare</span>
                    <select value={fromId ?? list[0].id} onChange={(e) => setParam("from", e.target.value)} aria-label="From version">{list.map((snap, i) => <option key={snap.id} value={snap.id}>v{i + 1}</option>)}</select>
                    <span className="muted">with</span>
                    <select value={toId ?? list[list.length - 1].id} onChange={(e) => setParam("to", e.target.value)} aria-label="To version">{list.map((snap, i) => <option key={snap.id} value={snap.id}>v{i + 1}</option>)}</select></div>
                  <QueryState query={diff}>{(d) => <DiffView diff={d} labelA="the earlier version" labelB="the later version" />}</QueryState>
                </>
              ) : <p className="muted">Only one version has been seen so far: nothing to compare. If the server changes a description or an input later, the difference is shown here.</p>}
            </div>)}</QueryState>}
      </Card>

      <Card title="Compare with another server" actions={
        <select value={other} onChange={(e) => setParam("vs", e.target.value || null)} aria-label="Compare with"><option value="">Choose a server…</option>{names.filter((n) => n !== current).map((n) => <option key={n}>{n}</option>)}</select>}>
        {!other ? <p className="muted">Useful when the same server is recorded twice: directly, and through a gateway. Name them differently (e.g. <code>bookshop</code> and <code>bookshop-wso2</code>) and see whether the gateway changes the tools an agent receives.</p>
          : compare.error ? <EmptyState title={`No tool list recorded for ${other}`} />
          : <QueryState query={compare}>{(d) => <DiffView diff={d} labelA={current} labelB={other} />}</QueryState>}
      </Card>
    </div>
  );
}
