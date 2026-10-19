// What your AI models cost: a headline, a chart you can click, and "where did the money go?".
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Money } from "../components/MoneyBlock";
import { PriceBadge } from "../components/PriceBadge";
import { Card, EmptyState, PageHead, QueryState, Skeleton, Tabs } from "../components/ui";
import { colorFor } from "../lib/colors";
import { formatMoney, formatTokens, moneyInWords, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

// The chart library is large: load it after the first paint.
const SpendChart = lazy(() => import("../components/SpendChart").then((m) => ({ default: m.SpendChart })));

type Split = "model" | "tool" | "run";

export function Spending() {
  const { hours, detailed } = useSettings();
  const navigate = useNavigate();
  const refetchInterval = useLiveInterval();
  const [split, setSplit] = useState<Split>("model");
  const spending = useQuery({ queryKey: ["spending", hours], queryFn: () => api.spending(hours, hours <= 6 ? 12 : 24), refetchInterval });
  const windowWords = hours >= 168 ? "the last 7 days" : hours === 1 ? "the last hour" : `the last ${hours} hours`;

  const openSlot = (fromNs: number, toNs: number, model?: string) => {
    const params = new URLSearchParams({ from: String(Math.floor(fromNs / 1e9)), to: String(Math.ceil(toNs / 1e9)) });
    if (model) params.set("model", model);
    navigate(`/runs?${params}`);
  };

  return (
    <>
      <PageHead title={PAGES.spending.title} about={PAGES.spending.about} />
      <QueryState query={spending}
        empty={{ when: (s) => s.enabled && s.totals.calls === 0, title: "No model calls in this period yet",
          hint: <p>Run your agent and its spending appears here. Try a longer period with the buttons at the top right.</p> }}>
        {(s) => {
          if (!s.enabled) return <EmptyState title="Cost calculation is switched off">Set <code>pricing.enabled: true</code> in <code>config.yaml</code> to see what your models cost.</EmptyState>;
          const models = s.by_model.map((m) => m.model);
          const perCall = s.totals.priced ? s.totals.usd / s.totals.priced : 0;
          const unpricedModels = s.by_model.filter((m) => m.status === "unpriced");
          const rows = split === "model" ? s.by_model.map((m) => ({ key: m.model, name: m.model, usd: m.usd, calls: m.calls, detail: `${formatTokens(m.prompt_tokens + m.completion_tokens)} words processed`, status: m.status, to: `/runs?model=${encodeURIComponent(m.model)}` }))
            : split === "tool" ? s.by_tool.map((t) => ({ key: t.tool, name: t.tool, usd: t.usd, calls: t.calls, detail: "what the model spent deciding to use it", status: "priced", to: `/runs?tool=${encodeURIComponent(t.tool)}` }))
            : s.top_runs.map((r) => ({ key: r.trace_id, name: r.question || "Conversation", usd: r.usd, calls: r.calls, detail: timeAgo(r.start_ns), status: "priced", to: `/runs/${r.trace_id}` }));
          const top = Math.max(...rows.map((row) => row.usd), 1e-9);
          return (
            <div className="col" style={{ gap: 16 }}>
              <Card>
                <div className="headline">
                  <div className="big">{formatMoney(s.totals.usd)}</div>
                  <div>
                    You spent <strong>{moneyInWords(s.totals.usd)}</strong> in {windowWords}, across {s.totals.calls} model call{s.totals.calls === 1 ? "" : "s"}.
                    {s.totals.local > 0 && <> {s.totals.local} ran on your own computer and cost nothing.</>}
                    {s.totals.priced > 0 && <> That is about {moneyInWords(perCall)} per call.</>}
                  </div>
                </div>
                {(s.totals.exact_usd ?? 0) > 0 && s.totals.usd > 0 && (
                  <p className="muted" style={{ margin: "10px 0 0" }}>
                    <strong>{Math.round(((s.totals.exact_usd ?? 0) / s.totals.usd) * 100)}%</strong> of this amount was reported by the
                    provider itself (exact); the rest is estimated from the words processed and the model's price.
                  </p>
                )}
                {unpricedModels.length > 0 && (
                  <div className="notice" role="note">
                    <strong>{s.totals.unpriced} call(s) are not counted</strong> because no price is known for {unpricedModels.map((m) => m.model).join(", ")}.
                    Prices are looked up automatically and hourly; <Link to="/about">learn more</Link>.
                  </div>
                )}
              </Card>

              <Card title="Spending over time">
                <p className="muted" style={{ marginTop: -6 }}>Each bar is a time slot, split by model. <strong>Click a bar</strong> to see those conversations.</p>
                <Suspense fallback={<Skeleton lines={4} />}><SpendChart series={s.series} models={models} hours={hours} onSlot={openSlot} /></Suspense>
                <div className="legend" style={{ marginTop: 8 }}>
                  {models.map((model) => (
                    <button key={model} className="small ghost" onClick={() => navigate(`/runs?model=${encodeURIComponent(model)}`)} title="Show conversations that used this model">
                      <i className="dot" style={{ background: colorFor(models, model) }} /> {model}
                    </button>))}
                </div>
              </Card>

              <Card title="Where did the money go?" flush>
                <div style={{ padding: "0 16px" }}>
                  <Tabs<Split> value={split} onChange={setSplit} tabs={[{ id: "model", label: "By model" }, { id: "tool", label: "By action" }, { id: "run", label: "Most expensive conversations" }]} />
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
