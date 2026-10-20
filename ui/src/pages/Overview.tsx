// The landing page in three calm rows: four numbers, the questions over time, and the latest questions with the models used.
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDollarSign, Cpu, Footprints, MessagesSquare } from "lucide-react";
import { lazy, Suspense } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Overview as OverviewData, QueryCard } from "../api/types";
import { CountUp } from "../components/CountUp";
import { FirstRun } from "../components/FirstRun";
import { ModelChip } from "../components/HoverCard";
import { TotalCost } from "../components/Money";
import { SideCounts } from "../components/Sides";
import { Card, PageHead, QueryState, Skeleton, Tile } from "../components/ui";
import { formatChange, formatCount, formatMoney, formatMs, formatTokens, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

// The chart library is large: load it after the first paint.
const StepsChart = lazy(() => import("../components/StepsChart").then((m) => ({ default: m.StepsChart })));

// One of the latest questions: click to open it; the answer shows when the pointer rests on it.
function LatestQuery({ card }: { card: QueryCard }) {
  return (
    <Link className={`latest-q${card.status === "problem" ? " problem" : ""}`} to={`/conversations?q=${card.trace_id}`}>
      <span className="latest-q-top"><span className={`dot ${card.status}`} /><span className="muted">{timeAgo(card.started_ns)}</span><span className="grow" /><TotalCost cost={card.cost} /></span>
      <span className="latest-q-text">{card.question || card.root_name}</span>
      <span className="latest-q-answer">{card.answer || (card.status === "problem" ? card.problem || "No answer" : "No answer recorded")}</span>
      <span className="latest-q-foot"><SideCounts human={card.human_messages} ai={card.ai_messages} /><span className="badge outline">{formatTokens(card.tokens.total)} tokens</span></span>
    </Link>
  );
}

// The ring around the Tokens tile when a daily budget is set.
function BudgetRing({ share, level }: { share: number; level: string }) {
  const circumference = 2 * Math.PI * 15;
  return (
    <svg className={`budget-ring ${level}`} viewBox="0 0 36 36" width="36" height="36" role="img" aria-label={`${Math.round(share * 100)}% of today's budget`}>
      <circle cx="18" cy="18" r="15" className="track" /><circle cx="18" cy="18" r="15" className="fill" strokeDasharray={`${Math.min(1, share) * circumference} ${circumference}`} />
    </svg>
  );
}

// The chips that say what needs a look; nothing wrong -> one green line.
function NeedsAttention({ o }: { o: OverviewData }) {
  const refused = Object.entries(o.decisions).filter(([d]) => d !== "allowed").reduce((sum, [, n]) => sum + n, 0);
  const budget = o.tokens.budget;
  const chips = [
    o.problem_questions > 0 && { to: "/conversations?filter=problems", text: `${o.problem_questions} question${o.problem_questions === 1 ? "" : "s"} had a problem`, tone: "bad" },
    budget.enabled && budget.level !== "ok" && { to: "/spending?view=tokens", text: `${Math.round((budget.share ?? 0) * 100)}% of today's token budget`, tone: budget.level === "over" ? "bad" : "warn" },
    o.heavy_questions > 0 && { to: "/spending?view=tokens", text: `${o.heavy_questions} heavy question${o.heavy_questions === 1 ? "" : "s"}`, tone: "warn" },
    refused > 0 && { to: "/gateway", text: `${refused} blocked by the gateway`, tone: "warn" },
    o.open_findings > 0 && { to: "/findings", text: `${o.open_findings} thing${o.open_findings === 1 ? "" : "s"} to check`, tone: o.open_findings_high ? "bad" : "warn" },
  ].filter(Boolean) as { to: string; text: string; tone: string }[];
  if (!chips.length) return <div className="attention ok" role="status"><CheckCircle2 size={16} /> All good</div>;
  return (
    <div className="attention" role="list" aria-label="Needs attention">
      <AlertTriangle size={16} className="attention-icon" />
      {chips.map((chip) => <Link role="listitem" key={chip.to + chip.text} className={`attention-chip ${chip.tone}`} to={chip.to}>{chip.text} →</Link>)}
    </div>
  );
}

export function Overview() {
  const { hours } = useSettings();
  const navigate = useNavigate();
  const refetchInterval = useLiveInterval();
  const overview = useQuery({ queryKey: ["overview", hours], queryFn: () => api.overview(hours), refetchInterval });
  const windowLabel = hours >= 168 ? "last 7 days" : hours === 1 ? "last hour" : "today";

  return (
    <>
      <PageHead title={PAGES.overview.title} about={PAGES.overview.about} help={PAGES.overview.help} sub={windowLabel} />
      <QueryState query={overview} empty={{ when: (o) => o.counts.spans === 0, title: "Nothing recorded yet", hint: <FirstRun kind="overview" /> }}>
        {(o) => {
          const budget = o.tokens.budget;
          return (
            <div className="col" style={{ gap: 16 }}>
              <div className="grid tiles four">
                <Tile icon={<MessagesSquare size={15} />} label="Discussions" value={<CountUp value={o.discussions} format={formatCount} />} hint="questions asked" to="/conversations" />
                <Tile icon={<Footprints size={15} />} label="Steps" value={<CountUp value={o.steps_total} format={formatCount} />}
                  hint={<SideCounts human={o.human_messages} ai={o.ai_messages} compact />} to="/conversations?sort=steps" />
                <Tile icon={<Cpu size={15} />} label="Tokens" value={<CountUp value={o.tokens.total} format={formatTokens} />}
                  trend={formatChange(o.tokens.change)} hint={`${formatTokens(o.tokens.input)} in · ${formatTokens(o.tokens.output)} out`}
                  extra={budget.enabled ? <BudgetRing share={budget.share ?? 0} level={budget.level ?? "ok"} /> : undefined} to="/spending?view=tokens" />
                <Tile icon={<CircleDollarSign size={15} />} label="Cost" value={o.cost?.enabled ? <CountUp value={o.cost.totals.usd} format={formatMoney} /> : "-"}
                  hint={o.cost?.enabled && o.cost.totals.local ? `${o.cost.totals.local} free local calls` : "estimated from prices"} to="/spending?view=dollars" />
              </div>
              <NeedsAttention o={o} />

              <Card title="Questions over time">
                {o.timeline.points.length === 0 ? <p className="muted">No questions in this period.</p> : (
                  <div data-tour="chart">
                    <Suspense fallback={<Skeleton lines={3} />}>
                      <StepsChart timeline={o.timeline} hours={hours} onOpen={(row) => navigate(row.count > 1
                        ? `/conversations?from=${Math.floor(row.startNs / 1e9)}&to=${Math.ceil((row.endNs ?? row.startNs) / 1e9)}`
                        : `/conversations?q=${row.traceId}`)} />
                    </Suspense>
                  </div>
                )}
              </Card>

              <div className="grid overview-bottom">
                <Card title="Latest questions" actions={<Link to="/conversations">All →</Link>}>
                  {o.latest_queries.length === 0 ? <p className="muted">No questions in this period.</p>
                    : <div className="latest-grid" data-tour="question">{o.latest_queries.slice(0, 4).map((card) => <LatestQuery key={card.trace_id} card={card} />)}</div>}
                </Card>
                {o.models.length > 0 && (
                  <Card title="Models used" actions={<Link to="/models">All →</Link>} flush>
                    <table><thead><tr><th>Model</th><th className="num">Calls</th><th className="num">Tokens</th><th className="num">Speed</th></tr></thead>
                      <tbody>{o.models.map((m) => (
                        <tr key={`${m.provider}-${m.model}`} className="click" onClick={() => navigate(`/models?model=${encodeURIComponent(m.model)}`)}>
                          <td><ModelChip name={m.model} /></td><td className="num">{m.calls}</td>
                          <td className="num" title={`${formatTokens(m.prompt_tokens)} in · ${formatTokens(m.completion_tokens)} out`}>{formatTokens(m.total_tokens)}</td>
                          <td className="num">{formatMs(m.avg_ms)}</td></tr>))}</tbody></table>
                  </Card>
                )}
              </div>
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
