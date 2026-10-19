// The landing page: how is everything doing right now?
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { FirstRun } from "../components/FirstRun";
import { Help } from "../components/Help";
import { Card, PageHead, QueryState, Skeleton, Tile } from "../components/ui";
import { formatCount, formatMoney, formatMs, formatPercent, formatTime, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

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
      <PageHead title={PAGES.overview.title} about={PAGES.overview.about} sub={windowLabel} />
      <QueryState query={overview} empty={{ when: (o) => o.counts.spans === 0, title: "Nothing recorded in this period yet", hint: <FirstRun kind="overview" title="Nothing recorded in this period yet" /> }}>
        {(o) => {
          const refused = Object.entries(o.decisions).filter(([d]) => d !== "allowed").reduce((sum, [, n]) => sum + n, 0);
          return (
            <div className="col" style={{ gap: 16 }}>
              <div className="grid tiles">
                <Tile label="Conversations" value={formatCount(o.counts.runs)} hint={`${formatCount(o.counts.spans)} steps`} to="/runs" />
                {o.cost?.enabled && <Tile label="Spending" value={formatMoney(o.cost.totals.usd)} hint={o.cost.totals.local ? `${o.cost.totals.local} free local call(s)` : `${o.cost.totals.priced} priced call(s)`} to="/spending" />}
                <Tile label="Actions used" value={formatCount(o.counts.tool_calls)} hint={`${o.servers} tool server${o.servers === 1 ? "" : "s"}`} to="/servers" />
                <Tile label="Problem rate" value={formatPercent(o.error_rate)} hint={`${formatCount(o.counts.errors)} steps had a problem`} tone={o.error_rate > 0.05 ? "bad" : undefined} to="/runs?errors_only=1" />
                <Tile label="Slowest 5% of actions" value={formatMs(o.tool_latency.p95_ms)} hint={`typical ${formatMs(o.tool_latency.p50_ms)}`} />
                <Tile label="Blocked by the gateway" value={formatCount(refused)} hint="not logged in, not allowed, too many, or a rule" tone={refused ? "warn" : undefined} to="/gateway" />
                <Tile label="Things to check" value={formatCount(o.open_findings)} hint={o.open_findings_high ? `${o.open_findings_high} important` : "none urgent"} tone={o.open_findings_high ? "bad" : undefined} to="/findings" />
              </div>

              <Card title="Actions over time"><Suspense fallback={<Skeleton lines={3} />}><ActivityChart data={o.activity} hours={hours} /></Suspense></Card>

              <div className="grid two">
                <Card title="Most used actions" flush>
                  <table><thead><tr><th>Action</th><th>Tool server</th><th className="num">Times used</th><th className="num">Problems</th><th className="num">Slowest 5%<Help topic="slowest" /></th></tr></thead>
                    <tbody>{o.busiest_tools.map((t) => (
                      <tr key={`${t.server}-${t.tool}`}><td><Link to={`/runs?tool=${t.tool}`}>{t.tool}</Link></td><td className="muted">{t.server}</td>
                        <td className="num">{t.calls}</td><td className="num">{t.errors || "-"}</td><td className="num">{formatMs(t.p95_ms)}</td></tr>))}</tbody></table>
                </Card>
                <Card title="Slowest actions (p95)" flush>
                  <table><thead><tr><th>Action</th><th className="num">Slowest 5%</th><th className="num">Typical<Help topic="typical" /></th><th className="num">Times used</th></tr></thead>
                    <tbody>{o.slowest_tools.map((t) => (
                      <tr key={`${t.server}-${t.tool}`}><td><Link to={`/runs?tool=${t.tool}`}>{t.tool}</Link></td><td className="num">{formatMs(t.p95_ms)}</td>
                        <td className="num">{formatMs(t.p50_ms)}</td><td className="num">{t.calls}</td></tr>))}</tbody></table>
                </Card>
              </div>

              <Card title="Latest conversations" actions={<Link to="/runs">All conversations →</Link>} flush>
                <QueryState query={recent} empty={{ when: (r) => r.length === 0, title: "No conversations yet" }}>
                  {(runs) => (
                    <table><thead><tr><th>When</th><th>Conversation</th><th className="num">Took</th><th className="num">Actions</th></tr></thead>
                      <tbody>{runs.map((r) => (
                        <tr key={r.trace_id} className="click"><td className="muted nowrap">{formatTime(r.start_ns)} · {timeAgo(r.start_ns)}</td>
                          <td><Link to={`/runs/${r.trace_id}`}>{r.question || r.root_name}</Link></td><td className="num">{formatMs(r.duration_ms)}</td>
                          <td className="num">{r.tool_calls}</td></tr>))}</tbody></table>
                  )}
                </QueryState>
              </Card>

              {o.models.length > 0 && (
                <Card title="Models your agents used" flush>
                  <table><thead><tr><th>Model</th><th>Provider</th><th className="num">Calls</th><th className="num">Words processed<Help topic="tokens" /></th><th className="num">Typical speed</th><th className="num">Slowest 5%</th></tr></thead>
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
