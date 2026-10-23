// The AI models that were used: provider, usage, tokens, price, speed and what each model can do. Click a model for its details.
import { useQuery } from "@tanstack/react-query";
import { Brain, Check, Cpu, Eye, Unlock, Wrench, X } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ModelEntry } from "../api/types";
import { FirstRun } from "../components/FirstRun";
import { Help } from "../components/Help";
import { Card, PageHead, QueryState, Segmented, Skeleton } from "../components/ui";
import { formatCount, formatMoney, formatMs, formatPercent, formatTime, formatTokens, timeAgo } from "../lib/format";
import { perMillion } from "../lib/models";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

// The charts load after the first paint.
const Sparkline = lazy(() => import("../components/ModelTokensChart").then((m) => ({ default: m.Sparkline })));
const ModelTokensChart = lazy(() => import("../components/ModelTokensChart").then((m) => ({ default: m.ModelTokensChart })));
const CompareModelsChart = lazy(() => import("../components/ModelTokensChart").then((m) => ({ default: m.CompareModelsChart })));

type Sort = "calls" | "usd" | "tokens" | "recent";
const SORTS: Record<Sort, (a: ModelEntry, b: ModelEntry) => number> = {
  calls: (a, b) => b.calls - a.calls, usd: (a, b) => b.usd - a.usd,
  tokens: (a, b) => b.tokens.total - a.tokens.total, recent: (a, b) => b.last_ns - a.last_ns,
};

// The small icons that say what a model can do.
function Abilities({ model }: { model: ModelEntry }) {
  const info = model.info;
  const items = [
    info.tool_call && { icon: <Wrench size={12} />, text: "uses tools" },
    info.reasoning && { icon: <Brain size={12} />, text: "reasons" },
    (info.input_modalities ?? []).includes("image") && { icon: <Eye size={12} />, text: "reads images" },
    info.open_weights && { icon: <Unlock size={12} />, text: "open weights" },
    model.status === "local" && { icon: <Cpu size={12} />, text: "runs on your computer" },
  ].filter(Boolean) as { icon: JSX.Element; text: string }[];
  if (!items.length) return <span className="muted" style={{ fontSize: 12 }}>no details known</span>;
  return <span className="row wrap" style={{ gap: 4 }}>{items.map((item) => <span key={item.text} className="badge outline">{item.icon}{item.text}</span>)}</span>;
}

// The price of a model in words.
function PriceLine({ model, used = false }: { model: ModelEntry; used?: boolean }) {
  if (model.status === "local") return <span className="money local">free (runs on your computer)</span>;
  if (!model.price) return <span className="muted">no price known</span>;
  return (
    <span>{perMillion(model.price.input)} in · {perMillion(model.price.output)} out <span className="muted">per 1M tokens</span>
      {used && <span className="used-line">you used {formatTokens(model.tokens.input)} in + {formatTokens(model.tokens.output)} out = <strong>{formatMoney(model.usd)}</strong></span>}
    </span>
  );
}

function ModelCard({ model, selected, onPick }: { model: ModelEntry; selected: boolean; onPick: () => void }) {
  return (
    <button className={`gcard${selected ? " on" : ""}`} onClick={onPick} aria-pressed={selected} data-model={model.model}>
      <span className="gcard-top"><strong>{model.model}</strong><span className="badge model">{model.provider || "unknown provider"}</span></span>
      <span className="gcard-stats">
        <span><b>{formatTokens(model.tokens.total)}</b> tokens</span>
        <span><b>{formatCount(model.calls)}</b> calls</span>
        <span><b>{model.status === "local" ? "free" : model.status === "unpriced" ? "no price" : formatMoney(model.usd)}</b></span>
      </span>
      {model.series && <Suspense fallback={<div className="sparkline" />}><Sparkline series={model.series} /></Suspense>}
      <PriceLine model={model} />
      <Abilities model={model} />
    </button>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return <><dt>{label}</dt><dd>{value ?? "-"}</dd></>;
}

function Detail({ model }: { model: ModelEntry }) {
  const { detailed, hours } = useSettings();
  const info = model.info;
  const yes = (v: boolean | null | undefined) => (v === undefined || v === null ? "-" : v ? <span className="ok-text"><Check size={13} /> yes</span> : <span className="muted"><X size={13} /> no</span>);
  return (
    <Card title={<span className="row">{model.display} <span className="badge model">{model.provider || "unknown provider"}</span></span>}>
      <div className="grid two" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
        <div>
          <h3>How it was used</h3>
          <dl className="kv" style={{ gridTemplateColumns: "150px 1fr" }}>
            <Fact label="Calls" value={`${model.calls} (${formatPercent(model.error_rate)} failed)`} />
            <Fact label="Questions answered" value={<Link to="/conversations">{model.questions}</Link>} />
            <Fact label="Tokens in" value={formatTokens(model.tokens.input)} />
            <Fact label="Tokens out" value={formatTokens(model.tokens.output)} />
            <Fact label="From the cache" value={formatTokens(model.tokens.cached)} />
            {model.tokens.reasoning > 0 && <Fact label="Reasoning" value={formatTokens(model.tokens.reasoning)} />}
            <Fact label="Per question" value={`${formatTokens(model.tokens.total / Math.max(1, model.questions))} tokens`} />
            <Fact label="Typical speed" value={formatMs(model.avg_ms)} />
            <Fact label="Slowest 5%" value={formatMs(model.p95_ms)} />
            <Fact label="First used" value={formatTime(model.first_ns)} />
            <Fact label="Last used" value={`${formatTime(model.last_ns)} (${timeAgo(model.last_ns)})`} />
          </dl>
        </div>
        <div>
          <h3>What it cost<Help topic="cost" /></h3>
          <dl className="kv" style={{ gridTemplateColumns: "150px 1fr" }}>
            <Fact label="Total" value={model.status === "local" ? "free" : model.status === "unpriced" ? "no price known" : formatMoney(model.usd)} />
            {model.exact_usd > 0 && <Fact label="Reported by provider" value={formatMoney(model.exact_usd)} />}
            {model.estimated_usd > 0 && <Fact label="Estimated" value={formatMoney(model.estimated_usd)} />}
            <Fact label="Price" value={<PriceLine model={model} used />} />
            {model.price?.cache_read != null && <Fact label="Cached tokens" value={`${perMillion(model.price.cache_read)} per 1M`} />}
            {model.price && <Fact label="Price source" value={`${model.price.source.replace("_", ".")} (${model.price.confidence.replace("_", " ")})`} />}
            <Fact label="" value={<Link to={`/spending`}>See all spending →</Link>} />
          </dl>
        </div>
        <div>
          <h3>What it can do</h3>
          <dl className="kv" style={{ gridTemplateColumns: "150px 1fr" }}>
            <Fact label="Reads" value={(info.input_modalities ?? []).join(", ") || "-"} />
            <Fact label="Writes" value={(info.output_modalities ?? []).join(", ") || "-"} />
            <Fact label="Memory size" value={info.context ? `${formatTokens(info.context)} tokens at once` : "-"} />
            <Fact label="Longest answer" value={info.max_output ? `${formatTokens(info.max_output)} tokens` : "-"} />
            <Fact label="Uses tools" value={yes(info.tool_call)} />
            <Fact label="Reasons step by step" value={yes(info.reasoning)} />
            <Fact label="Open weights" value={yes(info.open_weights)} />
            <Fact label="Released" value={info.release_date ?? "-"} />
            <Fact label="Knows events until" value={info.knowledge ?? "-"} />
            <Fact label="Family" value={info.family ?? "-"} />
          </dl>
          {!Object.keys(info).length && <p className="muted">The price lists know nothing more about this model. They are checked automatically (see Usage &amp; cost).</p>}
        </div>
      </div>
      {model.series && <><h3 style={{ marginTop: 16 }}>Tokens over time</h3><Suspense fallback={<Skeleton lines={3} />}><ModelTokensChart series={model.series} hours={hours} /></Suspense></>}
      {detailed && <p className="muted mono" style={{ marginBottom: 0 }}>Names recorded: {model.versions.join(", ")}</p>}
    </Card>
  );
}

export function Models() {
  const [params, setParams] = useSearchParams();
  const { hours } = useSettings();
  const models = useQuery({ queryKey: ["models", hours], queryFn: () => api.models(hours), refetchInterval: useLiveInterval() });
  const [sort, setSort] = useState<Sort>("calls");
  const [compare, setCompare] = useState(false);
  const provider = params.get("provider") ?? "";
  const providers = useMemo(() => [...new Set((models.data ?? []).map((m) => m.provider || "unknown provider"))].sort(), [models.data]);
  const setParam = (key: string, value: string | null) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next, { replace: true }); };

  return (
    <>
      <PageHead title={PAGES.models.title} about={PAGES.models.about} help={PAGES.models.help}>
        {providers.length > 1 && <select value={provider} onChange={(e) => setParam("provider", e.target.value || null)} aria-label="Provider"><option value="">All providers</option>{providers.map((p) => <option key={p}>{p}</option>)}</select>}
        <Segmented<Sort> value={sort} onChange={setSort} options={[{ id: "calls", label: "Most used" }, { id: "usd", label: "Most spent" }, { id: "tokens", label: "Most tokens" }, { id: "recent", label: "Latest" }]} />
      </PageHead>
      <QueryState query={models} empty={{ when: (m) => m.length === 0, title: "No model was used yet", hint: <FirstRun kind="overview" title="No model was used yet" /> }}>
        {(all) => {
          const shown = all.filter((m) => !provider || (m.provider || "unknown provider") === provider).sort(SORTS[sort]);
          const selected = all.find((m) => m.model === params.get("model")) ?? null;
          const totals = { calls: all.reduce((s, m) => s + m.calls, 0), usd: all.reduce((s, m) => s + m.usd, 0), tokens: all.reduce((s, m) => s + m.tokens.total, 0) };
          return (
            <div className="col" style={{ gap: 16 }}>
              <div className="row spread wrap">
                <div className="muted">{all.length} model{all.length === 1 ? "" : "s"} · {formatTokens(totals.tokens)} tokens · {formatCount(totals.calls)} calls · {formatMoney(totals.usd)}</div>
                {all.length > 1 && <button className={compare ? "primary small" : "small"} aria-pressed={compare} onClick={() => setCompare(!compare)}>Compare all models</button>}
              </div>
              {compare && <Card title="Tokens of every model"><Suspense fallback={<Skeleton lines={3} />}><CompareModelsChart models={shown} hours={hours} /></Suspense></Card>}
              <div className="gcards" role="list" aria-label="Models">
                {shown.map((m) => <div role="listitem" key={`${m.provider}-${m.model}`}><ModelCard model={m} selected={selected?.model === m.model} onPick={() => setParam("model", selected?.model === m.model ? null : m.model)} /></div>)}
              </div>
              {selected ? <Detail model={selected} /> : <p className="muted">Click a model to see everything about it.</p>}
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
