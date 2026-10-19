// The landing page: how is everything doing right now? Questions first, then tools, models and spending.
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { QueryCard } from "../api/types";
import { FirstRun } from "../components/FirstRun";
import { Help } from "../components/Help";
import { TotalCost } from "../components/Money";
import { Card, PageHead, QueryState, Skeleton, Tile } from "../components/ui";
import { formatCount, formatMoney, formatMs, formatPercent, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

// The chart library is large: load it after the first paint.
const QuestionPeaks = lazy(() => import("../components/QuestionPeaks").then((m) => ({ default: m.QuestionPeaks })));

// One of the latest questions: click to open it; the answer shows when the pointer rests on it.
function LatestQuery({ card }: { card: QueryCard }) {
  return (
    <Link className={`latest-q${card.status === "problem" ? " problem" : ""}`} to={`/conversations?q=${card.trace_id}`}>
      <span className="latest-q-top"><span className={`dot ${card.status}`} /><span className="muted">{timeAgo(card.started_ns)}</span><span className="grow" /><TotalCost cost={card.cost} /></span>
      <span className="latest-q-text">{card.question || card.root_name}</span>
      <span className="latest-q-answer">{card.answer ? card.answer : card.status === "problem" ? `It had a problem: ${card.problem || "no answer"}` : "No answer was recorded."}</span>
      <span className="latest-q-foot">
        <span className="badge outline">{card.exchanges} exchanges</span>
        {card.tools.map((tool) => <span key={tool} className="badge proxy">{tool}</span>)}
      </span>
    </Link>
  );
}

export function Overview() {
  const { hours } = useSettings();
  const navigate = useNavigate();
  const refetchInterval = useLiveInterval();
  const overview = useQuery({ queryKey: ["overview", hours], queryFn: () => api.overview(hours), refetchInterval });
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
                <Tile label="Discussions" value={formatCount(o.discussions)} hint={`${formatCount(o.counts.llm_calls)} model call${o.counts.llm_calls === 1 ? "" : "s"}`} to="/conversations" />
                <Tile label="Tools" value={formatCount(o.tools_total)} hint={`across ${o.mcps} MCP server${o.mcps === 1 ? "" : "s"}`} to="/mcps" />
                {o.cost?.enabled && <Tile label="Spending" value={formatMoney(o.cost.totals.usd)} hint={o.cost.totals.local ? `${o.cost.totals.local} free local call(s)` : `${o.cost.totals.priced} priced call(s)`} to="/spending" />}
                <Tile label="Problem rate" value={formatPercent(o.error_rate)} hint={`${formatCount(o.counts.errors)} steps had a problem`} tone={o.error_rate > 0.05 ? "bad" : undefined} to="/runs?errors_only=1" />
                <Tile label="Blocked by the gateway" value={formatCount(refused)} hint="not logged in, not allowed, too many, or a rule" tone={refused ? "warn" : undefined} to="/gateway" />
                <Tile label="Things to check" value={formatCount(o.open_findings)} hint={o.open_findings_high ? `${o.open_findings_high} important` : "none urgent"} tone={o.open_findings_high ? "bad" : undefined} to="/findings" />
              </div>

              <Card title={<>Questions over time<Help topic="discussion" /></>}>
                {o.timeline.points.length === 0 ? <p className="muted">No question was asked in this period.</p> : (
                  <Suspense fallback={<Skeleton lines={3} />}>
                    <QuestionPeaks timeline={o.timeline} onOpen={(row) => navigate(row.count > 1
                      ? `/conversations?from=${Math.floor(row.startNs / 1e9)}&to=${Math.ceil((row.endNs ?? row.startNs) / 1e9)}`
                      : `/conversations?q=${row.traceId}`)} />
                  </Suspense>
                )}
              </Card>

              <Card title="Latest queries asked" actions={<Link to="/conversations">All questions →</Link>}>
                {o.latest_queries.length === 0 ? <p className="muted">No question was asked in this period.</p>
                  : <div className="latest-grid">{o.latest_queries.map((card) => <LatestQuery key={card.trace_id} card={card} />)}</div>}
              </Card>

              {o.models.length > 0 && (
                <Card title="Models your agents used" actions={<Link to="/models">About the models →</Link>} flush>
                  <table><thead><tr><th>Model</th><th>Provider</th><th className="num">Calls</th><th className="num">Words processed<Help topic="tokens" /></th><th className="num">Typical speed</th><th className="num">Slowest 5%</th></tr></thead>
                    <tbody>{o.models.map((m) => (
                      <tr key={`${m.provider}-${m.model}`} className="click" onClick={() => navigate(`/models?model=${encodeURIComponent(m.model)}`)}>
                        <td><Link to={`/models?model=${encodeURIComponent(m.model)}`}>{m.model}</Link></td><td className="muted">{m.provider ?? "-"}</td><td className="num">{m.calls}</td>
                        <td className="num">{formatCount(m.total_tokens)}</td><td className="num">{formatMs(m.avg_ms)}</td><td className="num">{formatMs(m.p95_ms)}</td></tr>))}</tbody></table>
                </Card>
              )}

              <div className="grid two">
                <Card title="Most used tools" flush>
                  <table><thead><tr><th>Tool</th><th>MCP server</th><th className="num">Times used</th><th className="num">Problems</th><th className="num">Slowest 5%<Help topic="slowest" /></th></tr></thead>
                    <tbody>{o.busiest_tools.map((t) => (
                      <tr key={`${t.server}-${t.tool}`}><td><Link to={`/mcps?server=${t.server ?? ""}&tool=${t.tool}`}>{t.tool}</Link></td><td className="muted">{t.server}</td>
                        <td className="num">{t.calls}</td><td className="num">{t.errors || "-"}</td><td className="num">{formatMs(t.p95_ms)}</td></tr>))}</tbody></table>
                </Card>
                <Card title="Slowest tools (p95)" flush>
                  <table><thead><tr><th>Tool</th><th className="num">Slowest 5%</th><th className="num">Typical<Help topic="typical" /></th><th className="num">Times used</th></tr></thead>
                    <tbody>{o.slowest_tools.map((t) => (
                      <tr key={`${t.server}-${t.tool}`}><td><Link to={`/mcps?server=${t.server ?? ""}&tool=${t.tool}`}>{t.tool}</Link></td><td className="num">{formatMs(t.p95_ms)}</td>
                        <td className="num">{formatMs(t.p50_ms)}</td><td className="num">{t.calls}</td></tr>))}</tbody></table>
                </Card>
              </div>
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
