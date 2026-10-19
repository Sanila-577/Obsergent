// The MCP servers your agents use and the tools each one offers, as cards you can open. The "Changes" tab shows tool-list drift.
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Globe, Search, Terminal, Waypoints } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { McpServer, McpTool } from "../api/types";
import { FirstRun } from "../components/FirstRun";
import { Help } from "../components/Help";
import { ToolChanges } from "../components/ToolChanges";
import { Card, DecisionBadge, EmptyState, PageHead, QueryState, Segmented, Tabs } from "../components/ui";
import { formatMs, timeAgo } from "../lib/format";
import { useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

type Tab = "tools" | "changes";
type Filter = "all" | "used" | "unused";

function ServerCard({ server, selected, onPick }: { server: McpServer; selected: boolean; onPick: () => void }) {
  return (
    <button className={`gcard${selected ? " on" : ""}`} onClick={onPick} aria-pressed={selected} data-server={server.name}>
      <span className="gcard-top"><strong>{server.name}</strong>
        <span className="badge outline" title={server.transport === "web" ? "Reached over the web" : "A program started on this computer"}>
          {server.transport === "web" ? <Globe size={12} /> : <Terminal size={12} />}{server.transport === "web" ? "web address" : "program"}</span></span>
      <span className="gcard-stats"><span><b>{server.tool_count}</b> tool{server.tool_count === 1 ? "" : "s"}</span><span><b>{server.calls}</b> call{server.calls === 1 ? "" : "s"}</span><span><b>{server.errors}</b> failed</span></span>
      <span className="row wrap" style={{ gap: 4 }}>
        {server.via_gateway && <span className="badge gateway"><Waypoints size={12} /> via gateway</span>}
        {server.changed && <span className="badge high"><AlertTriangle size={12} /> tools changed</span>}
        <span className="muted" style={{ fontSize: 12 }}>last used {server.last_seen_ns ? timeAgo(server.last_seen_ns) : "never"}</span>
      </span>
    </button>
  );
}

function ToolCard({ tool, selected, onPick }: { tool: McpTool; selected: boolean; onPick: () => void }) {
  return (
    <button className={`gcard tool${selected ? " on" : ""}`} onClick={onPick} aria-pressed={selected} data-tool={tool.name}>
      <span className="gcard-top"><strong>{tool.name}</strong>
        <span className="row" style={{ gap: 4 }}>
          {tool.risky && <span className="badge medium" title="The name suggests it can change or send data">can change data</span>}
          {tool.changed && <span className="badge high">changed</span>}
          <span className={`badge ${tool.used ? "ok" : "neutral"}`}>{tool.used ? "used" : "not used yet"}</span></span></span>
      <span className="gcard-desc">{tool.description || "No description."}</span>
      <span className="row wrap" style={{ gap: 4 }}>{tool.parameters.length ? tool.parameters.map((p) => <span key={p.name} className="badge outline mono">{p.name}{p.required ? "*" : ""}</span>) : <span className="muted" style={{ fontSize: 12 }}>no inputs</span>}</span>
      <span className="gcard-stats"><span><b>{tool.calls}</b> calls</span><span><b>{formatMs(tool.p50_ms)}</b> typical</span><span>{tool.last_used_ns ? timeAgo(tool.last_used_ns) : "never used"}</span></span>
    </button>
  );
}

// Everything about one tool, with its inputs described in words.
function ToolDetail({ tool, server }: { tool: McpTool; server: McpServer }) {
  const { detailed } = useSettings();
  return (
    <Card title={<span className="row">{tool.name} <span className="muted">on {server.name}</span></span>}>
      <p style={{ marginTop: 0 }}>{tool.description || "This tool has no description."}</p>
      <div className="grid two" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
        <div>
          <h3>What you give it</h3>
          {tool.parameters.length === 0 ? <p className="muted">Nothing: it needs no inputs.</p> : (
            <table><thead><tr><th>Input</th><th>Kind</th><th>Needed?</th><th>What it is</th></tr></thead>
              <tbody>{tool.parameters.map((p) => <tr key={p.name}><td className="mono">{p.name}</td><td>{p.type}{p.choices.length > 0 && <div className="muted" style={{ fontSize: 12 }}>one of: {p.choices.join(", ")}</div>}</td>
                <td>{p.required ? <span className="badge ok">needed</span> : <span className="muted">optional</span>}</td><td className="muted">{p.description || "-"}</td></tr>)}</tbody></table>
          )}
        </div>
        <div>
          <h3>How it is used<Help topic="typical" /></h3>
          <dl className="kv" style={{ gridTemplateColumns: "130px 1fr" }}>
            <dt>Times used</dt><dd>{tool.calls}{tool.errors > 0 && <span className="badge error" style={{ marginLeft: 6 }}>{tool.errors} failed</span>}</dd>
            <dt>Typical time</dt><dd>{formatMs(tool.p50_ms)}</dd>
            <dt>Slowest 5%</dt><dd>{formatMs(tool.p95_ms)}</dd>
            <dt>Last used</dt><dd>{tool.last_used_ns ? timeAgo(tool.last_used_ns) : "never"}</dd>
            {tool.decisions.length > 0 && <><dt>Gateway</dt><dd className="row wrap" style={{ gap: 4 }}>{tool.decisions.map((d) => <DecisionBadge key={d} decision={d} />)}</dd></>}
          </dl>
          <p className="row wrap">
            {tool.calls > 0 && <Link className="btn small" to={`/runs?tool=${encodeURIComponent(tool.name)}&server=${encodeURIComponent(server.name)}`}>See the calls →</Link>}
            <Link className="btn small" to={`/gateway?server=${encodeURIComponent(server.name)}`}>Should it be allowed? →</Link>
          </p>
        </div>
      </div>
      {detailed && <><h3>Raw input definition</h3><pre className="code mono">{JSON.stringify(tool.schema, null, 2)}</pre></>}
    </Card>
  );
}

export function Mcps() {
  const [params, setParams] = useSearchParams();
  const servers = useQuery({ queryKey: ["mcps"], queryFn: api.mcps });
  const [filter, setFilter] = useState<Filter>("all");
  const [text, setText] = useState("");
  const tab = (params.get("tab") as Tab) || "tools";
  const setParam = (changes: Record<string, string | null>) => { const next = new URLSearchParams(params); for (const [k, v] of Object.entries(changes)) { if (v) next.set(k, v); else next.delete(k); } setParams(next, { replace: true }); };

  // The server named in the URL; or the one that offers the tool named in the URL; or the first.
  const current = useMemo(() => {
    const list = servers.data ?? [];
    return list.find((s) => s.name === params.get("server")) ?? list.find((s) => s.tools.some((t) => t.name === params.get("tool"))) ?? list[0];
  }, [servers.data, params]);

  return (
    <>
      <PageHead title={PAGES.mcps.title} about={PAGES.mcps.about} sub={servers.data ? `${servers.data.length} MCP server${servers.data.length === 1 ? "" : "s"}` : undefined}>
        <Help topic="mcp" />
      </PageHead>
      <QueryState query={servers} empty={{ when: (s) => s.length === 0, title: "No MCP server seen yet", hint: <FirstRun kind="servers" title="No MCP server seen yet" /> }}>
        {(list) => {
          const tools = (current?.tools ?? []).filter((t) => (filter === "all" || (filter === "used") === t.used)
            && `${t.name} ${t.description}`.toLowerCase().includes(text.trim().toLowerCase()));
          const selectedTool = current?.tools.find((t) => t.name === params.get("tool")) ?? null;
          return (
            <div className="col" style={{ gap: 16 }}>
              <div className="gcards" role="list" aria-label="MCP servers">
                {list.map((s) => <div role="listitem" key={s.name}><ServerCard server={s} selected={s.name === current?.name} onPick={() => setParam({ server: s.name, tool: null })} /></div>)}
              </div>
              {current && (
                <>
                  <Tabs value={tab} onChange={(next) => setParam({ tab: next === "tools" ? null : next })}
                    tabs={[{ id: "tools", label: `Tools (${current.tool_count})` }, { id: "changes", label: <>Changes{current.changes > 0 && <span className="nav-badge" style={{ marginLeft: 6 }}>{current.changes}</span>}</> }]} />
                  {tab === "tools" ? (
                    <div className="col" style={{ gap: 14 }}>
                      <div className="row wrap">
                        <label className="searchbox"><Search size={14} /><input type="search" placeholder="Search tools" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search tools" /></label>
                        <Segmented<Filter> value={filter} onChange={setFilter} options={[{ id: "all", label: "All" }, { id: "used", label: "Used" }, { id: "unused", label: "Not used yet" }]} />
                        {current.command && <span className="muted mono truncate" style={{ maxWidth: 420 }} title={current.command}>{current.command}</span>}
                      </div>
                      {tools.length === 0 ? <EmptyState title="No tool matches" /> : <div className="gcards tools" role="list" aria-label={`Tools of ${current.name}`}>
                        {tools.map((t) => <div role="listitem" key={t.name}><ToolCard tool={t} selected={t.name === selectedTool?.name} onPick={() => setParam({ tool: t.name === selectedTool?.name ? null : t.name })} /></div>)}</div>}
                      {selectedTool ? <ToolDetail tool={selectedTool} server={current} /> : tools.length > 0 && <p className="muted">Click a tool to see what you give it and how it is used.</p>}
                    </div>
                  ) : <ToolChanges current={current.name} names={list.map((s) => s.name)} />}
                </>
              )}
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
