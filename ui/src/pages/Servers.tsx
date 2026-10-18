// MCP servers and their tools: how they are used, and how their tool lists changed over time (rug-pull detection).
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ToolListDiff } from "../api/types";
import { DiffText } from "../components/DiffText";
import { JsonView } from "../components/JsonView";
import { Card, DecisionBadge, EmptyState, PageHead, QueryState, SeverityBadge } from "../components/ui";
import { formatMs, formatTime, timeAgo } from "../lib/format";
import { useSettings } from "../lib/state";

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

export function Servers() {
  const { hours } = useSettings();
  const [params, setParams] = useSearchParams();
  const servers = useQuery({ queryKey: ["servers"], queryFn: api.servers });
  const tools = useQuery({ queryKey: ["tools", hours], queryFn: () => api.tools(hours) });
  const names = [...new Set([...(servers.data ?? []).map((s) => s.server_name), ...(tools.data ?? []).map((t) => t.server).filter(Boolean) as string[]])].sort();
  const current = params.get("server") ?? names[0];
  const other = params.get("vs") ?? "";
  const setParam = (key: string, value: string | null) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next, { replace: true }); };

  const snapshots = useQuery({ queryKey: ["snapshots", current], queryFn: () => api.snapshots(current), enabled: !!current, retry: false });
  const fromId = params.get("from") ? Number(params.get("from")) : undefined;
  const toId = params.get("to") ? Number(params.get("to")) : undefined;
  const diff = useQuery({ queryKey: ["server-diff", current, fromId, toId], queryFn: () => api.serverDiff(current, fromId, toId), enabled: !!snapshots.data && snapshots.data.snapshots.length > 1 });
  const compare = useQuery({ queryKey: ["server-compare", current, other], queryFn: () => api.serverCompare(current, other), enabled: !!current && !!other, retry: false });

  if (servers.isPending || tools.isPending) return <QueryState query={servers}>{() => null}</QueryState>;
  if (names.length === 0) return <><PageHead title="Servers & tools" /><Card><EmptyState title="No MCP servers seen yet">Run an agent or an app through the proxy and its servers and tools show up here.</EmptyState></Card></>;
  const serverTools = (tools.data ?? []).filter((t) => t.server === current);
  const list = snapshots.data?.snapshots ?? [];

  return (
    <>
      <PageHead title="Servers & tools" sub={`${names.length} server(s)`}>
        <Link className="btn" to={`/gateway?server=${current}`}>Suggest an access policy →</Link>
      </PageHead>
      <div className="grid" style={{ gridTemplateColumns: "230px minmax(0,1fr)", alignItems: "start" }}>
        <Card flush>
          <table><tbody>{names.map((name) => (
            <tr key={name} className={`click${name === current ? " selected" : ""}`} onClick={() => setParams({ server: name })}>
              <td><strong>{name}</strong><div className="muted" style={{ fontSize: 12 }}>{servers.data?.find((s) => s.server_name === name)?.versions ?? 0} tool-list version(s)</div></td></tr>))}</tbody></table>
        </Card>

        <div className="col">
          <Card title={`Tools used on ${current}`} flush>
            {serverTools.length === 0 ? <EmptyState title="No calls in this time window" /> : (
              <table><thead><tr><th>Tool</th><th className="num">Calls</th><th className="num">Errors</th><th className="num">median</th><th className="num">p95</th><th>Gateway</th><th>Last used</th></tr></thead>
                <tbody>{serverTools.map((t) => (
                  <tr key={t.tool}><td><Link to={`/runs?tool=${t.tool}&server=${current}`}>{t.tool}</Link></td><td className="num">{t.calls}</td><td className="num">{t.errors || "-"}</td>
                    <td className="num">{formatMs(t.p50_ms)}</td><td className="num">{formatMs(t.p95_ms)}</td>
                    <td><span className="row wrap" style={{ gap: 4 }}>{Object.entries(t.decisions).map(([d, n]) => <span key={d}><DecisionBadge decision={d} /> {n}</span>)}</span></td>
                    <td className="muted nowrap">{timeAgo(t.last_seen_ns)}</td></tr>))}</tbody></table>
            )}
          </Card>

          <Card title="Version history of the tool list">
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
      </div>
    </>
  );
}
