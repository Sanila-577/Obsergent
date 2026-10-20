// The questions you asked: a scrollable strip of question cards, and below it everything that happened in the selected one.
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { QueryCard, QueryThread } from "../api/types";
import { FirstRun } from "../components/FirstRun";
import { AgentChip, ModelChip, ToolChip } from "../components/HoverCard";
import { TotalCost } from "../components/Money";
import { SideCounts } from "../components/Sides";
import { Steps } from "../components/Steps";
import { Thread } from "../components/Thread";
import { Card, EmptyState, ErrorBox, PageHead, QueryState, Segmented, Skeleton, Tabs } from "../components/ui";
import { formatMs, formatTime, formatTokens, shortId, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

type Tab = "conversation" | "timeline";
type Sort = "newest" | "steps" | "tokens" | "problems";
const SORTS: Record<Sort, (a: QueryCard, b: QueryCard) => number> = {
  newest: (a, b) => b.started_ns - a.started_ns, steps: (a, b) => b.steps - a.steps,
  tokens: (a, b) => b.tokens.total - a.tokens.total, problems: (a, b) => Number(b.status === "problem") - Number(a.status === "problem") || b.started_ns - a.started_ns,
};
const DAY_NS = 24 * 3600 * 1e9;

// Wait until typing stops before asking the server.
function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

// One question card in the strip.
function QuestionCard({ card, selected, onPick }: { card: QueryCard; selected: boolean; onPick: () => void }) {
  return (
    <button className={`q-card${selected ? " on" : ""}${card.status === "problem" ? " problem" : ""}`} onClick={onPick} aria-pressed={selected}
      data-trace={card.trace_id} title={card.answer ? `Answer: ${card.answer}` : card.question}>
      <span className="q-card-top">
        <span className={`dot ${card.status}`} title={card.status === "ok" ? "answered" : "had a problem"} />
        <span className="muted">{timeAgo(card.started_ns)}</span>
        <span className="grow" />
        <TotalCost cost={card.cost} />
      </span>
      <span className="q-card-text">{card.question || card.root_name || "(no question text)"}</span>
      <span className="q-card-foot"><SideCounts human={card.human_messages} ai={card.ai_messages} /><span className="badge outline">{formatTokens(card.tokens.total)} tokens</span></span>
    </button>
  );
}

// The details at the right of a thread.
function Summary({ thread }: { thread: QueryThread }) {
  const { detailed } = useSettings();
  const t = thread.tokens;
  const parts = [["in", t.input - t.cached, "var(--agent)"], ["cached", t.cached, "var(--accent-2)"], ["out", t.output, "var(--proxy)"]] as const;
  return (
    <Card title="Summary">
      <div className="summary-big">
        <div><span className="muted">Steps</span><strong>{thread.steps}</strong><SideCounts human={thread.human_messages} ai={thread.ai_messages} compact /></div>
        <div><span className="muted">Tokens</span><strong>{formatTokens(t.total)}</strong><span className="muted">{formatTokens(t.input)} in · {formatTokens(t.output)} out</span></div>
        <div><span className="muted">Cost</span><strong><TotalCost cost={thread.cost} /></strong><span className="muted">{formatMs(thread.duration_ms)}</span></div>
      </div>
      {t.total > 0 && <div className="token-bar" role="img" aria-label="How the tokens split">{parts.map(([label, n, colour]) => n > 0 &&
        <span key={label} style={{ flexGrow: n, background: colour }} title={`${label}: ${n.toLocaleString()} tokens`} />)}</div>}
      <dl className="kv" style={{ gridTemplateColumns: "70px minmax(0,1fr)", marginTop: 12 }}>
        <dt>Agent</dt><dd>{thread.agent ? <AgentChip name={thread.agent} /> : "-"}</dd>
        <dt>Models</dt><dd className="row wrap" style={{ gap: 4 }}>{thread.models.map((m) => <ModelChip key={m} name={m} />)}</dd>
        <dt>Tools</dt><dd className="row wrap" style={{ gap: 4 }}>{thread.tools.length ? thread.tools.map((tool) => <ToolChip key={tool} name={tool} />) : "none"}</dd>
        <dt>Result</dt><dd>{thread.status === "ok" ? <span className="badge ok">answered</span> : <span className="badge error" title={thread.problem}>problem</span>}</dd>
        {detailed && <><dt>Run id</dt><dd className="mono">{shortId(thread.trace_id, 12)}</dd>
          {thread.session && <><dt>Session</dt><dd className="mono">{thread.session}</dd></>}
          {thread.user_id && <><dt>User</dt><dd className="mono">{thread.user_id}</dd></>}</>}
      </dl>
    </Card>
  );
}

export function Conversations() {
  const [params, setParams] = useSearchParams();
  const { live } = useSettings();
  const refetchInterval = useLiveInterval();
  const [find, setFind] = useState(params.get("find") ?? "");
  const debounced = useDebounced(find);
  const strip = useRef<HTMLDivElement>(null);
  // A time slot opened from the Overview chart: only the questions asked in it.
  const since = params.get("from") ? Number(params.get("from")) : undefined;
  const until = params.get("to") ? Number(params.get("to")) : undefined;
  const cards = useQuery({ queryKey: ["queries", debounced, since, until], queryFn: () => api.queries({ limit: 100, q: debounced || undefined, since, until }), refetchInterval });

  const sort = (params.get("sort") as Sort) || "newest";
  const filter = params.get("filter") ?? "";
  const setUrl = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) { if (value) next.set(key, value); else next.delete(key); }
    setParams(next, { replace: true });
  };

  // Quick filters work on the loaded questions: problems, heavy (twice the usual tokens), today, one model, one tool.
  const list = useMemo(() => {
    const all = cards.data ?? [];
    const usual = all.length ? [...all].map((c) => c.tokens.total).sort((a, b) => a - b)[Math.floor(all.length / 2)] : 0;
    const keep = (card: QueryCard) => !filter || (filter === "problems" ? card.status === "problem"
      : filter === "heavy" ? card.tokens.total > 2 * usual
      : filter === "today" ? card.started_ns > Date.now() * 1e6 - DAY_NS
      : filter.startsWith("model:") ? card.models.includes(filter.slice(6))
      : filter.startsWith("tool:") ? card.tools.includes(filter.slice(5)) : true);
    return all.filter(keep).sort(SORTS[sort]);
  }, [cards.data, filter, sort]);
  const models = useMemo(() => [...new Set((cards.data ?? []).flatMap((c) => c.models))], [cards.data]);
  const toolNames = useMemo(() => [...new Set((cards.data ?? []).flatMap((c) => c.tools))], [cards.data]);

  const selectedId = params.get("q") ?? list[0]?.trace_id ?? "";
  const tab = (params.get("tab") as Tab) || "conversation";
  const spanId = params.get("span");
  const thread = useQuery({ queryKey: ["query", selectedId], queryFn: () => api.query(selectedId), enabled: !!selectedId, retry: false, refetchInterval });
  const pick = (id: string) => setUrl({ q: id, tab: null, span: null });

  // Live mode: a pill announces questions that arrived after the page opened.
  const seen = useRef<Set<string> | null>(null);
  const [fresh, setFresh] = useState<string[]>([]);
  useEffect(() => {
    const ids = (cards.data ?? []).map((c) => c.trace_id);
    if (seen.current === null) { if (ids.length) seen.current = new Set(ids); return; }
    const added = ids.filter((id) => !seen.current!.has(id));
    if (added.length) { added.forEach((id) => seen.current!.add(id)); setFresh((now) => [...added, ...now]); }
  }, [cards.data]);

  // Keep the selected card in view (after a reload, a link from the chart, or the arrow keys).
  useEffect(() => {
    strip.current?.querySelector<HTMLElement>(`[data-trace="${selectedId}"]`)?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }, [selectedId, list.length]);

  // Left and right arrow keys move between questions (unless a field has the focus).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes((event.target as HTMLElement).tagName) || event.metaKey || event.ctrlKey) return;
      if ((event.target as HTMLElement).closest?.(".steps-chart")) return;
      const index = list.findIndex((c) => c.trace_id === selectedId);
      if (event.key === "ArrowRight" && index < list.length - 1) pick(list[index + 1].trace_id);
      if (event.key === "ArrowLeft" && index > 0) pick(list[index - 1].trace_id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Drag the strip with the mouse like a touch screen.
  const drag = useRef<{ x: number; left: number } | null>(null);
  const scrollBy = (amount: number) => strip.current?.scrollBy({ left: amount, behavior: "smooth" });
  const chip = (id: string, label: string) => (
    <button key={id} className={`filter-chip${filter === id ? " on" : ""}`} aria-pressed={filter === id} onClick={() => setUrl({ filter: filter === id ? null : id })}>
      {label}{filter === id && <X size={12} />}
    </button>
  );

  return (
    <>
      <PageHead title={PAGES.conversations.title} about={PAGES.conversations.about} help={PAGES.conversations.help}
        sub={cards.data ? `${list.length} question${list.length === 1 ? "" : "s"}` : undefined}>
        <label className="searchbox"><Search size={14} /><input type="search" placeholder="Search" value={find}
          onChange={(e) => { setFind(e.target.value); setUrl({ find: e.target.value || null }); }} aria-label="Search your questions" /></label>
      </PageHead>
      {cards.isPending ? <Skeleton lines={4} /> : cards.error ? <ErrorBox error={cards.error} /> : (cards.data ?? []).length === 0 ? (
        debounced ? <EmptyState title="No question matches" /> : <FirstRun kind="runs" title="No questions yet" />
      ) : (
        <div className="col" style={{ gap: 14 }}>
          <div className="row wrap toolbar">
            <Segmented<Sort> value={sort} onChange={(next) => setUrl({ sort: next === "newest" ? null : next })}
              options={[{ id: "newest", label: "Newest" }, { id: "steps", label: "Most steps" }, { id: "tokens", label: "Most tokens" }, { id: "problems", label: "Problems first" }]} />
            <div className="row wrap" role="group" aria-label="Quick filters" style={{ gap: 6 }}>
              {chip("problems", "Problems")}{chip("heavy", "Heavy")}{chip("today", "Today")}
              {models.length > 1 && models.map((m) => chip(`model:${m}`, m))}
              {toolNames.map((tool) => chip(`tool:${tool}`, tool))}
            </div>
            {(since || until) && <button className="filter-chip on" onClick={() => setUrl({ from: null, to: null })}>{since ? formatTime(since * 1e9) : ""} – {until ? formatTime(until * 1e9) : "now"} <X size={12} /></button>}
            {live && fresh.length > 0 && <button className="new-pill" onClick={() => { pick(fresh[0]); setFresh([]); }}>{fresh.length} new question{fresh.length === 1 ? "" : "s"} ↑</button>}
          </div>
          {list.length === 0 ? <EmptyState title="No question matches this filter" /> : (
            <div className="q-strip-wrap" data-tour="question">
              <button className="icon q-arrow" onClick={() => scrollBy(-340)} aria-label="Scroll questions left"><ChevronLeft size={18} /></button>
              <div className="q-strip" ref={strip} role="list" aria-label="Your questions"
                onPointerDown={(e) => { if (e.pointerType === "mouse" && strip.current) drag.current = { x: e.clientX, left: strip.current.scrollLeft }; }}
                onPointerMove={(e) => { if (drag.current && strip.current) strip.current.scrollLeft = drag.current.left - (e.clientX - drag.current.x); }}
                onPointerUp={() => { drag.current = null; }} onPointerLeave={() => { drag.current = null; }}>
                {list.map((card) => <div role="listitem" key={card.trace_id}><QuestionCard card={card} selected={card.trace_id === selectedId} onPick={() => pick(card.trace_id)} /></div>)}
              </div>
              <button className="icon q-arrow" onClick={() => scrollBy(340)} aria-label="Scroll questions right"><ChevronRight size={18} /></button>
            </div>
          )}

          {selectedId && (
            <QueryState query={thread}>
              {(t) => (
                <section aria-label="The selected question" className="col" style={{ gap: 12 }}>
                  <div className="thread-title">
                    <h2>{t.question || t.root_name}</h2>
                    <div className="muted">{formatTime(t.started_ns)} · {formatMs(t.duration_ms)}</div>
                  </div>
                  <Tabs value={tab} onChange={(next) => setUrl({ tab: next === "conversation" ? null : next, span: null })}
                    tabs={[{ id: "conversation", label: "Conversation" }, { id: "timeline", label: "Timeline" }]} />
                  {tab === "conversation" ? (
                    <div className="thread-layout">
                      <Thread thread={t.thread} traceId={t.trace_id} />
                      <div className="thread-side"><Summary thread={t} /></div>
                    </div>
                  ) : <Steps traceId={t.trace_id} spanId={spanId} onSpan={(id) => setUrl({ span: id })} />}
                </section>
              )}
            </QueryState>
          )}
        </div>
      )}
    </>
  );
}
