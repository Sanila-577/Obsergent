// The landing page: how is everything doing right now?
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, ListBadges, PageHead, QueryState, Skeleton, Tile } from "../components/ui";
import { formatCount, formatMs, formatPercent, formatTime, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";

// The chart library is large: load it after the first paint.
const ActivityChart = lazy(() => import("../components/ActivityChart").then((m) => ({ default: m.ActivityChart })));

export function Overview() {
  const { hours } = useSettings();
  const refetchInterval = useLiveInterval();
  const overview = useQuery({ queryKey: ["overview", hours], queryFn: () => api.overview(hours), refetchInterval });
  const recent = useQuery({ queryKey: ["traces", { limit: 6 }], queryFn: () => api.traces({ limit: 6 }), refetchInterval });
  const windowLabel = hours >= 168 ? "last 7 days" : `last ${hours} h`;

  return (
    <>
      <PageHead title="Overview" sub={windowLabel} />
      <QueryState query={overview} empty={{ when: (o) => o.counts.spans === 0, title: "Nothing recorded in this window yet",
        hint: <p>Start the proxy or the SDK, run an agent, then come back. See the README quickstart. Try a longer window with the buttons at the top right.</p> }}>
        {(o) => {
          const refused = Object.entries(o.decisions).filter(([d]) => d !== "allowed").reduce((sum, [, n]) => sum + n, 0);
          return (
            <div className="col" style={{ gap: 16 }}>
              <div className="grid tiles">
                <Tile label="Runs" value={formatCount(o.counts.runs)} hint={`${formatCount(o.counts.spans)} spans`} to="/runs" />
                <Tile label="Tool calls" value={formatCount(o.counts.tool_calls)} hint={`${o.servers} server(s)`} to="/servers" />
                <Tile label="Error rate" value={formatPercent(o.error_rate)} hint={`${formatCount(o.counts.errors)} failed spans`} tone={o.error_rate > 0.05 ? "bad" : undefined} to="/runs?errors_only=1" />
                <Tile label="Tool latency p95" value={formatMs(o.tool_latency.p95_ms)} hint={`median ${formatMs(o.tool_latency.p50_ms)}`} />
                <Tile label="Refused by gateway" value={formatCount(refused)} hint="401 · 403 · 429 · denied" tone={refused ? "warn" : undefined} to="/gateway" />
                <Tile label="Open findings" value={formatCount(o.open_findings)} hint={o.open_findings_high ? `${o.open_findings_high} high severity` : "none high"} tone={o.open_findings_high ? "bad" : undefined} to="/findings" />
              </div>

              <Card title="MCP tool calls over time"><Suspense fallback={<Skeleton lines={3} />}><ActivityChart data={o.activity} hours={hours} /></Suspense></Card>

              <div className="grid two">
                <Card title="Busiest tools" flush>
                  <table><thead><tr><th>Tool</th><th>Server</th><th className="num">Calls</th><th className="num">Errors</th><th className="num">p95</th></tr></thead>
                    <tbody>{o.busiest_tools.map((t) => (
                      <tr key={`${t.server}-${t.tool}`}><td><Link to={`/runs?tool=${t.tool}`}>{t.tool}</Link></td><td className="muted">{t.server}</td>
                        <td className="num">{t.calls}</td><td className="num">{t.errors || "-"}</td><td className="num">{formatMs(t.p95_ms)}</td></tr>))}</tbody></table>
                </Card>
                <Card title="Slowest tools (p95)" flush>
                  <table><thead><tr><th>Tool</th><th className="num">p95</th><th className="num">median</th><th className="num">Calls</th></tr></thead>
                    <tbody>{o.slowest_tools.map((t) => (
                      <tr key={`${t.server}-${t.tool}`}><td><Link to={`/runs?tool=${t.tool}`}>{t.tool}</Link></td><td className="num">{formatMs(t.p95_ms)}</td>
                        <td className="num">{formatMs(t.p50_ms)}</td><td className="num">{t.calls}</td></tr>))}</tbody></table>
                </Card>
              </div>

              <Card title="Latest runs" actions={<Link to="/runs">All runs →</Link>} flush>
                <QueryState query={recent} empty={{ when: (r) => r.length === 0, title: "No runs yet" }}>
                  {(runs) => (
                    <table><thead><tr><th>When</th><th>Run</th><th className="num">Duration</th><th className="num">Tool calls</th><th>Services</th></tr></thead>
                      <tbody>{runs.map((r) => (
                        <tr key={r.trace_id} className="click"><td className="muted nowrap">{formatTime(r.start_ns)} · {timeAgo(r.start_ns)}</td>
                          <td><Link to={`/runs/${r.trace_id}`}>{r.root_name}</Link></td><td className="num">{formatMs(r.duration_ms)}</td>
                          <td className="num">{r.tool_calls}</td><td><ListBadges value={r.services} /></td></tr>))}</tbody></table>
                  )}
                </QueryState>
              </Card>

              {o.models.length > 0 && (
                <Card title="Models used by your agents" flush>
                  <table><thead><tr><th>Model</th><th>Provider</th><th className="num">Calls</th><th className="num">Tokens</th><th className="num">Avg latency</th><th className="num">p95</th></tr></thead>
                    <tbody>{o.models.map((m) => (
                      <tr key={m.model}><td>{m.model}</td><td className="muted">{m.provider ?? "-"}</td><td className="num">{m.calls}</td>
                        <td className="num">{formatCount(m.total_tokens)}</td><td className="num">{formatMs(m.avg_ms)}</td><td className="num">{formatMs(m.p95_ms)}</td></tr>))}</tbody></table>
                </Card>
              )}
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
