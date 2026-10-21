// Usage & cost: how many tokens your models used and what they cost. A Tokens | Dollars switch at the top; each view has a
// headline, a chart you can click and "where did it go?".
import { useQuery } from "@tanstack/react-query";
import { CircleDollarSign, Cpu } from "lucide-react";
import { lazy, Suspense, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Money } from "../components/MoneyBlock";
import { PriceBadge } from "../components/PriceBadge";
import { Card, EmptyState, PageHead, QueryState, Skeleton, Tabs } from "../components/ui";
import { colorFor } from "../lib/colors";
import { formatChange, formatMoney, formatTokens, moneyInWords, timeAgo } from "../lib/format";
import { CountUp } from "../components/CountUp";
import { Help } from "../components/Help";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

// The chart library is large: load it after the first paint.
const StepsChart = lazy(() => import("../components/StepsChart").then((m) => ({ default: m.StepsChart })));

type Split = "model" | "tool" | "run";
type TokenSplit = "model" | "agent" | "tool" | "question";

// A peak opens its question; a time slot (many questions) opens the questions of that slot.
function openRow(navigate: (to: string) => void, row: { count: number; startNs: number; endNs?: number; traceId: string }) {
  navigate(row.count > 1 ? `/conversations?from=${Math.floor(row.startNs / 1e9)}&to=${Math.ceil((row.endNs ?? row.startNs) / 1e9)}`
    : `/conversations?q=${row.traceId}`);
}

// The tokens view: totals, the trend, where the tokens went, and the warnings.
function TokensView() {
  const { hours } = useSettings();
  const navigate = useNavigate();
  const refetchInterval = useLiveInterval();
  const [split, setSplit] = useState<TokenSplit>("model");
  const usage = useQuery({ queryKey: ["usage", hours], queryFn: () => api.usage(hours), refetchInterval });
  const timeline = useQuery({ queryKey: ["queries-timeline", hours], queryFn: () => api.queriesTimeline(hours), refetchInterval });
  return (
    <QueryState query={usage} empty={{ when: (u) => u.totals.calls === 0, title: "No tokens used in this period" }}>
      {(u) => {
        const models = u.by_model.map((m) => m.model);
        const rows = split === "model" ? u.by_model.map((m) => ({ key: m.model, name: m.model, total: m.total, detail: `${formatTokens(m.input)} in · ${formatTokens(m.output)} out · ${m.calls} calls`, to: `/models?model=${encodeURIComponent(m.model)}` }))
          : split === "agent" ? u.by_agent.map((a) => ({ key: a.agent, name: a.agent, total: a.total, detail: `${a.questions} questions`, to: `/agents?agent=${encodeURIComponent(a.agent)}` }))
          : split === "tool" ? u.by_tool.map((t) => ({ key: t.tool, name: t.tool, total: t.total, detail: `${t.calls} uses`, to: `/mcps?tool=${encodeURIComponent(t.tool)}` }))
          : u.by_question.map((q) => ({ key: q.trace_id, name: q.question || "Question", total: q.tokens.total, detail: `${q.steps ?? "-"} steps · ${timeAgo(q.started_ns)}`, to: `/conversations?q=${q.trace_id}` }));
        const top = Math.max(...rows.map((row) => row.total), 1);
        const budget = u.budget;
        return (
          <div className="col" style={{ gap: 16 }}>
            <Card>
              <div className="headline">
                <div className="big"><CountUp value={u.totals.total} format={formatTokens} /> <span className="unit">tokens</span></div>
                <div className="headline-facts">
                  {u.change !== null && <span className={`trend ${u.change > 0 ? "up" : "down"}`}>{formatChange(u.change)} vs before</span>}
                  <span><strong>{formatTokens(u.totals.input)}</strong> in<Help topic="tokensIn" /> · <strong>{formatTokens(u.totals.output)}</strong> out<Help topic="tokensOut" />{u.totals.cached > 0 && <> · <strong>{formatTokens(u.totals.cached)}</strong> cached</>}</span>
                  <span className="muted">in = what the model read · out = what it wrote</span>
                  <span><strong>{formatTokens(u.totals.avg_per_question)}</strong> per question · <strong>{formatTokens(u.totals.avg_per_call)}</strong> per model call</span>
                </div>
              </div>
              <div className="budget-line">
                {budget.enabled ? (
                  <>
                    <span>Today: {formatTokens(budget.used)} of {formatTokens(budget.budget ?? 0)}</span>
                    <span className={`budget-bar ${budget.level}`}><span style={{ width: `${Math.min(100, (budget.share ?? 0) * 100)}%` }} /></span>
                    <strong>{Math.round((budget.share ?? 0) * 100)}%</strong>
                  </>
                ) : <span className="muted">No daily budget set<Help topic="budget" /></span>}
              </div>
            </Card>

            <Card title={<>Tokens of each question<Help topic="tokensInOut" /></>}>
              {timeline.data && <Suspense fallback={<Skeleton lines={4} />}>
                <StepsChart timeline={timeline.data} hours={hours} measures={["tokens"]} onOpen={(row) => openRow(navigate, row)} />
              </Suspense>}
              <div className="legend" style={{ marginTop: 8 }}>{models.map((model) => <Link key={model} to={`/models?model=${encodeURIComponent(model)}`}><i className="dot" style={{ background: colorFor(models, model) }} /> {model}</Link>)}</div>
            </Card>

            <Card title="Where did the tokens go?" flush>
              <div style={{ padding: "0 16px" }}>
                <Tabs<TokenSplit> value={split} onChange={setSplit} tabs={[{ id: "model", label: "By model" }, { id: "agent", label: "By agent" }, { id: "tool", label: "By tool" }, { id: "question", label: "Heaviest questions" }]} />
              </div>
              {rows.length === 0 ? <EmptyState title="Nothing to show" /> : (
                <ul className="share-list">{rows.map((row) => (
                  <li key={row.key}><Link to={row.to} className="share-row">
                    <span className="share-name" title={row.name}>{row.name}</span>
                    <span className="share-bar"><span style={{ width: `${Math.max(2, (row.total / top) * 100)}%`, background: split === "model" ? colorFor(models, row.name) : "var(--accent)" }} /></span>
                    <span className="share-usd">{formatTokens(row.total)}</span>
                    <span className="share-detail muted">{row.detail}</span>
                  </Link></li>))}</ul>
              )}
            </Card>

            <div className="grid three">
              <Card title={<>Hidden overhead<Help text="Every model call carries the descriptions of all the tools the agent offers it. Fewer or shorter tool descriptions mean fewer tokens." /></>}>
                <div className="big-number">≈ {formatTokens(u.tool_definitions.per_call)}</div>
                <div className="muted">tokens of tool descriptions in every model call</div>
              </Card>
              <Card title="Close to the model's limit">
                {u.near_limit.length === 0 ? <div className="ok-text">✓ none</div> : (
                  <ul className="plain-list">{u.near_limit.slice(0, 4).map((n) => (
                    <li key={`${n.trace_id}${n.span_id}`}><Link to={`/conversations?q=${n.trace_id}`}>{n.model}: {Math.round(n.share * 100)}% of {formatTokens(n.context)}</Link></li>))}</ul>
                )}
              </Card>
              <Card title={<span id="heavy">Heavy questions</span>}>
                {u.heavy.length === 0 ? <div className="ok-text">✓ none</div> : (
                  <ul className="plain-list">{u.heavy.slice(0, 4).map((h) => (
                    <li key={h.trace_id}><Link to={`/conversations?q=${h.trace_id}`}>{formatTokens(h.tokens)}{h.times_usual ? ` (${h.times_usual.toFixed(0)}×)` : ""}: {h.question.slice(0, 48)}</Link></li>))}</ul>
                )}
              </Card>
            </div>
          </div>
        );
      }}
    </QueryState>
  );
}

export function Spending() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "dollars" ? "dollars" : "tokens";
  return (
    <>
      <PageHead title={PAGES.spending.title} about={PAGES.spending.about} help={PAGES.spending.help}>
        <div className="seg big-seg" role="group" aria-label="Show tokens or dollars">
          <button className={view === "tokens" ? "on" : ""} aria-pressed={view === "tokens"} onClick={() => setParams({ view: "tokens" }, { replace: true })}><Cpu size={14} /> Tokens</button>
          <button className={view === "dollars" ? "on" : ""} aria-pressed={view === "dollars"} onClick={() => setParams({ view: "dollars" }, { replace: true })}><CircleDollarSign size={14} /> Dollars</button>
        </div>
      </PageHead>
      {view === "tokens" ? <TokensView /> : <DollarsView />}
    </>
  );
}

// The dollars view: what the model calls cost.
function DollarsView() {
  const { hours, detailed } = useSettings();
  const navigate = useNavigate();
  const refetchInterval = useLiveInterval();
  const [split, setSplit] = useState<Split>("model");
  const spending = useQuery({ queryKey: ["spending", hours], queryFn: () => api.spending(hours, hours <= 6 ? 12 : 24), refetchInterval });
  const timeline = useQuery({ queryKey: ["queries-timeline", hours], queryFn: () => api.queriesTimeline(hours), refetchInterval });

  return (
    <>
      <QueryState query={spending}
        empty={{ when: (s) => s.enabled && s.totals.calls === 0, title: "No model calls in this period yet",
          hint: <p>Run your agent and its spending appears here. Try a longer period with the buttons at the top right.</p> }}>
        {(s) => {
          if (!s.enabled) return <EmptyState title="Cost calculation is switched off">Set <code>pricing.enabled: true</code> in <code>config.yaml</code> to see what your models cost.</EmptyState>;
          const models = s.by_model.map((m) => m.model);
          const perCall = s.totals.priced ? s.totals.usd / s.totals.priced : 0;
          const unpricedModels = s.by_model.filter((m) => m.status === "unpriced");
          const rows = split === "model" ? s.by_model.map((m) => ({ key: m.model, name: m.model, usd: m.usd, calls: m.calls, detail: `${formatTokens(m.prompt_tokens + m.completion_tokens)} tokens (${formatTokens(m.prompt_tokens)} in · ${formatTokens(m.completion_tokens)} out)`, status: m.status, to: `/runs?model=${encodeURIComponent(m.model)}` }))
            : split === "tool" ? s.by_tool.map((t) => ({ key: t.tool, name: t.tool, usd: t.usd, calls: t.calls, detail: "what the model spent deciding to use it", status: "priced", to: `/runs?tool=${encodeURIComponent(t.tool)}` }))
            : s.top_runs.map((r) => ({ key: r.trace_id, name: r.question || "Conversation", usd: r.usd, calls: r.calls, detail: timeAgo(r.start_ns), status: "priced", to: `/runs/${r.trace_id}` }));
          const top = Math.max(...rows.map((row) => row.usd), 1e-9);
          return (
            <div className="col" style={{ gap: 16 }}>
              <Card>
                <div className="headline">
                  <div className="big"><CountUp value={s.totals.usd} format={formatMoney} /></div>
                  <div className="headline-facts">
                    <span>You spent <strong>{moneyInWords(s.totals.usd)}</strong> on <strong>{s.totals.calls}</strong> model call{s.totals.calls === 1 ? "" : "s"}</span>
                    {s.totals.priced > 0 && <span>about <strong>{moneyInWords(perCall)}</strong> per call</span>}
                    {s.totals.local > 0 && <span className="ok-text">{s.totals.local} free calls on your own computer</span>}
                    {(s.totals.exact_usd ?? 0) > 0 && s.totals.usd > 0 && (
                      <span><strong>{Math.round(((s.totals.exact_usd ?? 0) / s.totals.usd) * 100)}%</strong> of this amount was reported by the provider itself (exact)</span>
                    )}
                  </div>
                </div>
                {unpricedModels.length > 0 && (
                  <div className="notice" role="note">
                    <strong>{s.totals.unpriced} call(s) are not counted</strong> because no price is known for {unpricedModels.map((m) => m.model).join(", ")}.
                    Prices are looked up automatically and hourly; <Link to="/about">learn more</Link>.
                  </div>
                )}
              </Card>

              <Card title="Cost of each question">
                {timeline.data && <Suspense fallback={<Skeleton lines={4} />}>
                  <StepsChart timeline={timeline.data} hours={hours} measures={["cost"]} onOpen={(row) => openRow(navigate, row)} />
                </Suspense>}
                <div className="legend" style={{ marginTop: 8 }}>
                  {models.map((model) => (
                    <button key={model} className="small ghost" onClick={() => navigate(`/runs?model=${encodeURIComponent(model)}`)} title="Show conversations that used this model">
                      <i className="dot" style={{ background: colorFor(models, model) }} /> {model}
                    </button>))}
                </div>
              </Card>

              <Card title="Where did the money go?" flush>
                <div style={{ padding: "0 16px" }}>
                  <Tabs<Split> value={split} onChange={setSplit} tabs={[{ id: "model", label: "By model" }, { id: "tool", label: "By tool" }, { id: "run", label: "Most expensive" }]} />
                </div>
                {rows.length === 0 ? <EmptyState title="Nothing to show yet" /> : (
                  <ul className="share-list">
                    {rows.map((row) => (
                      <li key={row.key}>
                        <Link to={row.to} className="share-row">
                          <span className="share-name" title={row.name}>{row.name}</span>
                          <span className="share-bar"><span style={{ width: `${Math.max(2, (row.usd / top) * 100)}%`, background: split === "model" ? colorFor(models, row.name) : "var(--accent)" }} /></span>
                          <span className="share-usd"><Money usd={row.usd} status={row.status} /></span>
                          <span className="share-detail muted">{row.calls} call{row.calls === 1 ? "" : "s"} · {row.detail}</span>
                        </Link>
                      </li>))}
                  </ul>
                )}
              </Card>

              <PriceBadge detailed={detailed} />
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
