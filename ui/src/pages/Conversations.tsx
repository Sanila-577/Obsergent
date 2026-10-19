// The questions you asked: a scrollable strip of question cards, and below it everything that happened in the selected one.
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { QueryCard, QueryThread } from "../api/types";
import { FirstRun } from "../components/FirstRun";
import { Help } from "../components/Help";
import { TotalCost } from "../components/Money";
import { Steps } from "../components/Steps";
import { Thread } from "../components/Thread";
import { Card, EmptyState, ErrorBox, PageHead, QueryState, Skeleton, Tabs } from "../components/ui";
import { formatMs, formatTime, shortId, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

type Tab = "conversation" | "steps";

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
      data-trace={card.trace_id} title={card.question}>
      <span className="q-card-top">
        <span className={`dot ${card.status}`} title={card.status === "ok" ? "answered" : "had a problem"} />
        <span className="muted">{timeAgo(card.started_ns)}</span>
        <span className="grow" />
        <TotalCost cost={card.cost} />
      </span>
      <span className="q-card-text">{card.question || card.root_name || "(no question text)"}</span>
      <span className="q-card-foot">
        <span className="badge outline">{card.exchanges} exchanges</span>
        {card.tools.slice(0, 2).map((tool) => <span key={tool} className="badge proxy">{tool}</span>)}
        {card.tools.length > 2 && <span className="muted">+{card.tools.length - 2}</span>}
      </span>
    </button>
  );
}

// The details at the right of a thread.
function Summary({ thread }: { thread: QueryThread }) {
  const { detailed } = useSettings();
  return (
    <Card title="About this question">
      <dl className="kv" style={{ gridTemplateColumns: "92px minmax(0,1fr)" }}>
        <dt>Asked</dt><dd>{formatTime(thread.started_ns)}</dd>
        <dt>Took</dt><dd>{formatMs(thread.duration_ms)}</dd>
        <dt>Cost</dt><dd><TotalCost cost={thread.cost} />{thread.cost.exact ? <span className="muted"> ({thread.cost.exact} reported by the provider)</span> : null}</dd>
        <dt>Agent</dt><dd><Link to={`/agents?agent=${encodeURIComponent(thread.agent)}`}>{thread.agent || "-"}</Link></dd>
        <dt>Models</dt><dd className="row wrap" style={{ gap: 4 }}>{thread.models.map((m) => <Link key={m} className="badge model" to={`/models?model=${encodeURIComponent(m)}`}>{m}</Link>)}</dd>
        <dt>Tools used</dt><dd className="row wrap" style={{ gap: 4 }}>{thread.tools.length ? thread.tools.map((t) => <Link key={t} className="badge proxy" to={`/mcps?tool=${encodeURIComponent(t)}`}>{t}</Link>) : "none"}</dd>
        <dt>Exchanges<Help topic="exchange" /></dt><dd>{thread.exchanges} ({thread.model_calls} model call{thread.model_calls === 1 ? "" : "s"}, {thread.tool_calls} tool use{thread.tool_calls === 1 ? "" : "s"})</dd>
        <dt>Result</dt><dd>{thread.status === "ok" ? <span className="badge ok">answered</span> : <span className="badge error" title={thread.problem}>had a problem</span>}</dd>
        {detailed && <><dt>Run id</dt><dd className="mono">{shortId(thread.trace_id, 12)}</dd>
          {thread.session && <><dt>Chat session</dt><dd className="mono">{thread.session}</dd></>}
          {thread.user_id && <><dt>User</dt><dd className="mono">{thread.user_id}</dd></>}
          <dt>More</dt><dd><Link to={`/runs/${thread.trace_id}`}>Open as a full run →</Link></dd></>}
      </dl>
    </Card>
  );
}

export function Conversations() {
  const [params, setParams] = useSearchParams();
  const refetchInterval = useLiveInterval();
  const [find, setFind] = useState(params.get("find") ?? "");
  const debounced = useDebounced(find);
  const strip = useRef<HTMLDivElement>(null);
  // A time slot opened from the chart on the Overview page: only the questions asked in it.
  const since = params.get("from") ? Number(params.get("from")) : undefined;
  const until = params.get("to") ? Number(params.get("to")) : undefined;
  const cards = useQuery({ queryKey: ["queries", debounced, since, until], queryFn: () => api.queries({ limit: 100, q: debounced || undefined, since, until }), refetchInterval });

  const list = useMemo(() => cards.data ?? [], [cards.data]);
  const selectedId = params.get("q") ?? list[0]?.trace_id ?? "";
  const tab = (params.get("tab") as Tab) || "conversation";
  const spanId = params.get("span");
  const thread = useQuery({ queryKey: ["query", selectedId], queryFn: () => api.query(selectedId), enabled: !!selectedId, retry: false, refetchInterval });

  const setUrl = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) { if (value) next.set(key, value); else next.delete(key); }
    setParams(next, { replace: true });
  };
  const pick = (id: string) => setUrl({ q: id, tab: null, span: null });

  // Keep the selected card in view (after a reload, a link from the chart, or the arrow keys).
  useEffect(() => {
    strip.current?.querySelector<HTMLElement>(`[data-trace="${selectedId}"]`)?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }, [selectedId, list.length]);

  // Left and right arrow keys move between questions (unless a field has the focus).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes((event.target as HTMLElement).tagName) || event.metaKey || event.ctrlKey) return;
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

  return (
    <>
      <PageHead title={PAGES.conversations.title} about={PAGES.conversations.about}
        sub={cards.data ? `${list.length} question${list.length === 1 ? "" : "s"}${debounced ? " match" : ""}` : undefined}>
        <label className="searchbox"><Search size={14} /><input type="search" placeholder="Search your questions" value={find}
          onChange={(e) => { setFind(e.target.value); setUrl({ find: e.target.value || null }); }} aria-label="Search your questions" /></label>
      </PageHead>
      {cards.isPending ? <Skeleton lines={4} /> : cards.error ? <ErrorBox error={cards.error} /> : list.length === 0 ? (
        debounced ? <EmptyState title="No questions match your search" /> : <FirstRun kind="runs" title="No questions yet" />
      ) : (
        <div className="col" style={{ gap: 16 }}>
          <div className="q-strip-wrap">
            <button className="icon q-arrow" onClick={() => scrollBy(-340)} aria-label="Scroll questions left"><ChevronLeft size={18} /></button>
            <div className="q-strip" ref={strip} role="list" aria-label="Your questions"
              onPointerDown={(e) => { if (e.pointerType === "mouse" && strip.current) drag.current = { x: e.clientX, left: strip.current.scrollLeft }; }}
              onPointerMove={(e) => { if (drag.current && strip.current) strip.current.scrollLeft = drag.current.left - (e.clientX - drag.current.x); }}
              onPointerUp={() => { drag.current = null; }} onPointerLeave={() => { drag.current = null; }}>
              {list.map((card) => <div role="listitem" key={card.trace_id}><QuestionCard card={card} selected={card.trace_id === selectedId} onPick={() => pick(card.trace_id)} /></div>)}
            </div>
            <button className="icon q-arrow" onClick={() => scrollBy(340)} aria-label="Scroll questions right"><ChevronRight size={18} /></button>
          </div>
          {(since || until) && <div className="row"><span className="badge outline">Only questions asked {since ? formatTime(since * 1e9) : ""} – {until ? formatTime(until * 1e9) : "now"}</span>
            <button className="small" onClick={() => setUrl({ from: null, to: null })}>Show all questions</button></div>}
          <div className="muted" style={{ fontSize: 12.5, marginTop: -8 }}>Click a question to read everything that happened in it. Use <kbd>←</kbd> <kbd>→</kbd> to move between questions.</div>

          {selectedId && (
            <QueryState query={thread}>
              {(t) => (
                <section aria-label="The selected question" className="col" style={{ gap: 12 }}>
                  <div className="thread-title">
                    <h2>{t.question || t.root_name}</h2>
                    <div className="muted">{formatTime(t.started_ns)} · {formatMs(t.duration_ms)} · {t.exchanges} exchanges</div>
                  </div>
                  <Tabs value={tab} onChange={(next) => setUrl({ tab: next === "conversation" ? null : next, span: null })}
                    tabs={[{ id: "conversation", label: "Conversation" }, { id: "steps", label: "Steps" }]} />
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
