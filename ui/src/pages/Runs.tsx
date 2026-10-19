// Every recorded run, newest first, with filters that live in the URL (so a filtered list can be shared).
// Paged loading ("Load older runs").
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
// Icon.
import { GitCompare } from "lucide-react";
// State and effects.
import { useEffect, useState } from "react";
// Router helpers.
import { Link, useNavigate, useSearchParams } from "react-router-dom";
// API functions.
import { api } from "../api/client";
// Types only.
import type { TraceFilters, TraceSummary } from "../api/types";
import { DecisionBadge, EmptyState, ErrorBox, ListBadges, PageHead, Skeleton } from "../components/ui";
import { FirstRun } from "../components/FirstRun";
import { Help } from "../components/Help";
import { TotalCost } from "../components/Money";
import { formatCount, formatMs, formatTime, splitList, timeAgo } from "../lib/format";
// Refresh interval for live mode.
import { useLiveInterval, useSettings } from "../lib/state";
import { DECISION_WORDS, PAGES } from "../lib/words";

// Runs per page.
const PAGE = 50;
const RANGES: Record<string, number | undefined> = { all: undefined, "1h": 1, "6h": 6, "24h": 24, "7d": 168 };
// Gateway decisions offered in the filter.
const DECISIONS = ["allowed", "unauthorized", "forbidden", "throttled", "denied", "error"];

/** Wait until the user stops typing before asking the server. */
// Wait until typing stops before using the value.
function useDebounced<T>(value: T, ms = 300): T {
  // The delayed value.
  const [debounced, setDebounced] = useState(value);
  // { => Restart the timer on each change.
  useEffect(() => {
    // After `ms` copy the value.
    const timer = setTimeout(() => setDebounced(value), ms);
    // clearTimeout => Cancel the previous timer.
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

// The Runs page.
export function Runs() {
  const { detailed } = useSettings();
  // Filters live in the URL query string.
  const [params, setParams] = useSearchParams();
  // Change page from code.
  const navigate = useNavigate();
  // 2 s in live mode, else off.
  const refetchInterval = useLiveInterval();
  // Text in the search box.
  const [search, setSearch] = useState(params.get("q") ?? "");
  // Up to two runs ticked for comparison.
  const [picked, setPicked] = useState<string[]>([]);
  // Search text after the user pauses.
  const debouncedSearch = useDebounced(search);

  // Set or remove one URL parameter.
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  // { if ((params.get("q") => Copy the debounced search text into the URL.
  useEffect(() => { if ((params.get("q") ?? "") !== debouncedSearch) setParam("q", debouncedSearch || null); }, [debouncedSearch]);

  // Selected time range.
  const range = params.get("range") ?? "all";
  // The filters sent to the API, read from the URL.
  const filters: TraceFilters = {
    q: params.get("q") ?? undefined, errors_only: params.get("errors_only") === "1", tool: params.get("tool") ?? undefined,
    server: params.get("server") ?? undefined, decision: params.get("decision") ?? undefined, model: params.get("model") ?? undefined,
    session_id: params.get("session") ?? undefined,
    since: params.get("from") ? Number(params.get("from")) : RANGES[range] ? Date.now() / 1000 - RANGES[range]! * 3600 : undefined,
    until: params.get("to") ? Number(params.get("to")) : undefined,
  };
  // Load a page of runs; the next page starts before the last run shown.
  const runs = useInfiniteQuery({
    queryKey: ["runs", filters],
    queryFn: ({ pageParam }) => api.traces({ ...filters, limit: PAGE, before_ns: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1].start_ns : undefined),
    refetchInterval,
  });
  // Tool names for the Tool filter's suggestions.
  const tools = useQuery({ queryKey: ["tools", 168], queryFn: () => api.tools(168) });
  // Model names for the Model filter.
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });

  // All loaded pages joined.
  const rows: TraceSummary[] = runs.data?.pages.flat() ?? [];
  // Tick/untick a run, keeping at most two.
  const togglePick = (id: string) => setPicked((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now.slice(-1), id]));
  // Is any filter active?
  const filtered = Object.entries(filters).some(([key, v]) => v !== undefined && v !== false && key !== "since" && key !== "until") || range !== "all" || params.has("from");

  return (
    <>
      <PageHead title={PAGES.runs.title} about={PAGES.runs.about} sub={rows.length ? `${rows.length}${runs.hasNextPage ? "+" : ""} shown` : undefined}>
        {picked.length === 2 && <button className="primary" onClick={() => navigate(`/compare?a=${picked[0]}&b=${picked[1]}`)}><GitCompare size={15} /> Compare these 2</button>}
        {picked.length === 1 && <span className="muted">Pick one more conversation to compare</span>}
      </PageHead>

      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row wrap">
          <input type="search" placeholder="Search conversations…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search" />
          <input list="tool-list" placeholder="Action (tool)" value={params.get("tool") ?? ""} onChange={(e) => setParam("tool", e.target.value || null)} aria-label="Action" style={{ width: 150 }} />
          <datalist id="tool-list">{(tools.data ?? []).map((t) => <option key={`${t.server}${t.tool}`} value={String(t.tool)} />)}</datalist>
          {detailed && <input list="server-list" placeholder="Server" value={params.get("server") ?? ""} onChange={(e) => setParam("server", e.target.value || null)} aria-label="Server" style={{ width: 140 }} />}
          <datalist id="server-list">{[...new Set((tools.data ?? []).map((t) => t.server).filter(Boolean))].map((s) => <option key={s} value={String(s)} />)}</datalist>
          <select value={params.get("decision") ?? ""} onChange={(e) => setParam("decision", e.target.value || null)} aria-label="Gateway decision">
            <option value="">Any gateway result</option>{DECISIONS.map((d) => <option key={d} value={d}>{DECISION_WORDS[d] ?? d}</option>)}
          </select>
          <select value={params.get("model") ?? ""} onChange={(e) => setParam("model", e.target.value || null)} aria-label="Model">
            <option value="">Any model</option>{(models.data ?? []).map((m) => <option key={m.model}>{m.model}</option>)}
          </select>
          <select value={range} onChange={(e) => setParam("range", e.target.value === "all" ? null : e.target.value)} aria-label="Time range">
            <option value="all">Any time</option><option value="1h">Last hour</option><option value="6h">Last 6 hours</option><option value="24h">Last 24 hours</option><option value="7d">Last 7 days</option>
          </select>
          <label className="check"><input type="checkbox" checked={params.get("errors_only") === "1"} onChange={(e) => setParam("errors_only", e.target.checked ? "1" : null)} /> Problems only</label>
          {filtered && <button className="small ghost" onClick={() => { setSearch(""); setParams({}, { replace: true }); }}>Clear filters</button>}
        </div>
      </div>

      <div className="card flush">
        {runs.isPending ? <div style={{ padding: 16 }}><Skeleton lines={5} /></div>
          : runs.error ? <div style={{ padding: 16 }}><ErrorBox error={runs.error} /></div>
          : rows.length === 0 ? (filtered ? <EmptyState title="No conversations match these filters"><p>Try clearing a filter.</p></EmptyState> : <FirstRun kind="runs" />)
          : (
            <table>
              <thead><tr><th style={{ width: 28 }} /><th>When</th><th>Conversation</th><th className="num">Duration</th><th className="num">Cost</th><th className="num">Actions<Help topic="action" /></th><th className="num">Problems</th>{detailed && <th className="num">To check</th>}<th>Gateway</th><th>Model</th>{detailed && <th>Services</th>}</tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.trace_id} className={`click${picked.includes(r.trace_id) ? " selected" : ""}`} onClick={() => navigate(`/runs/${r.trace_id}`)}>
                    <td onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={picked.includes(r.trace_id)} onChange={() => togglePick(r.trace_id)} aria-label={`Select ${r.root_name} to compare`} /></td>
                    <td className="nowrap"><div>{formatTime(r.start_ns)}</div><div className="muted" style={{ fontSize: 12 }}>{timeAgo(r.start_ns)}</div></td>
                    <td><Link to={`/runs/${r.trace_id}`} onClick={(e) => e.stopPropagation()}>{r.question || r.root_name}</Link><div className="muted mono" style={{ fontSize: 11 }}>{detailed ? r.trace_id.slice(0, 12) : ""}{r.user_id ? `${detailed ? " · " : ""}${r.user_id}` : ""}</div></td>
                    <td className="num">{formatMs(r.duration_ms)}</td>
                    <td className="num"><TotalCost cost={r.cost} /></td>
                    <td className="num">{r.tool_calls || "-"}</td>
                    <td className="num">{r.error_count ? <span className="badge error">{r.error_count}</span> : "-"}</td>
                    {detailed && <td className="num">{r.smells_count ? <span className="badge medium">{r.smells_count}</span> : "-"}</td>}
                    <td>{splitList(r.decisions).length ? <span className="row wrap" style={{ gap: 4 }}>{splitList(r.decisions).map((d) => <DecisionBadge key={d} decision={d} />)}</span> : <span className="muted">-</span>}</td>
                    <td className="nowrap">{r.models ? <>{r.models}<div className="muted" style={{ fontSize: 12 }}>{formatCount(r.total_tokens)} tokens</div></> : <span className="muted">-</span>}</td>
                    {detailed && <td><ListBadges value={r.services} /></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        {runs.hasNextPage && <div style={{ padding: 12, textAlign: "center" }}><button onClick={() => runs.fetchNextPage()} disabled={runs.isFetchingNextPage}>{runs.isFetchingNextPage ? "Loading…" : "Load older runs"}</button></div>}
      </div>
    </>
  );
}
