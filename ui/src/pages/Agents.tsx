// The agents that answered your questions, and how each one works: its steps, the models and tools it uses, drawn as a graph.
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { AgentEntry, AgentGraph, GraphNode } from "../api/types";
import { FirstRun } from "../components/FirstRun";
import { FlowGraph, type FlowEdgeInfo, type FlowNodeInfo } from "../components/FlowGraph";
import { Card, EmptyState, PageHead, QueryState } from "../components/ui";
import { formatMoney, formatMs, formatTokens, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

const KIND_WORDS: Record<string, string> = { start: "question", end: "answer", step: "step", model: "model", tool: "tool", mcp: "MCP server", gateway: "gateway" };

function AgentCard({ agent, selected, onPick }: { agent: AgentEntry; selected: boolean; onPick: () => void }) {
  return (
    <button className={`gcard${selected ? " on" : ""}`} onClick={onPick} aria-pressed={selected} data-agent={agent.name}>
      <span className="gcard-top"><strong>{agent.name}</strong><span className="badge agent">{agent.framework}</span></span>
      <span className="gcard-stats"><span><b>{agent.questions}</b> question{agent.questions === 1 ? "" : "s"}</span><span><b>{formatTokens(agent.tokens.total)}</b> tokens</span><span><b>{formatMoney(agent.usd)}</b></span></span>
      <span className="row wrap" style={{ gap: 4 }}>{agent.models.map((m) => <span key={m} className="badge model">{m}</span>)}{agent.problems > 0 && <span className="badge error">{agent.problems} problem{agent.problems === 1 ? "" : "s"}</span>}</span>
      <span className="muted gcard-line">{Math.round(agent.avg_steps)} steps and {formatTokens(agent.avg_tokens)} tokens per question · {timeAgo(agent.last_ns)}</span>
    </button>
  );
}

// Turn the API's graph into boxes and arrows for FlowGraph.
export function graphParts(graph: AgentGraph): { nodes: FlowNodeInfo[]; edges: FlowEdgeInfo[] } {
  const nodes = graph.nodes.map<FlowNodeInfo>((node) => ({
    id: node.id, kind: node.kind, label: node.label, tone: node.errors ? "bad" : undefined,
    sub: node.kind === "model" ? `${formatTokens(node.tokens)} tokens · ${node.calls}×`
      : node.calls ? `${node.calls}×${node.avg_ms ? ` · ${formatMs(node.avg_ms)}` : ""}` : undefined,
  }));
  const edges = graph.edges.map<FlowEdgeInfo>((edge) => ({
    source: edge.source, target: edge.target, calls: edge.calls, errors: edge.errors,
    label: `${edge.calls}×${edge.avg_ms ? ` · ${formatMs(edge.avg_ms)}` : ""}${edge.errors ? ` · ${edge.errors} failed` : ""}`,
  }));
  return { nodes, edges };
}

function NodePanel({ node, graph, onClose }: { node: GraphNode; graph: AgentGraph; onClose: () => void }) {
  const { detailed } = useSettings();
  const incoming = graph.edges.filter((e) => e.target === node.id);
  const outgoing = graph.edges.filter((e) => e.source === node.id);
  const label = (id: string) => graph.nodes.find((n) => n.id === id)?.label ?? id;
  return (
    <aside className="flow-panel" aria-label={`Details of ${node.label}`}>
      <div className="row spread"><span className="badge outline">{KIND_WORDS[node.kind] ?? node.kind}</span><button className="small ghost" onClick={onClose}>Close</button></div>
      <h2 style={{ marginTop: 8 }}>{node.label}</h2>
      <dl className="kv" style={{ gridTemplateColumns: "100px 1fr" }}>
        <dt>Used</dt><dd>{node.calls} time{node.calls === 1 ? "" : "s"}</dd>
        <dt>Typical time</dt><dd>{formatMs(node.avg_ms)}</dd>
        <dt>Total time</dt><dd>{formatMs(node.total_ms)}</dd>
        {node.kind === "model" && <><dt>Tokens</dt><dd>{formatTokens(node.tokens)}</dd><dt>Cost</dt><dd>{formatMoney(node.cost_usd)}</dd></>}
        <dt>Problems</dt><dd>{node.errors || "none"}</dd>
      </dl>
      {incoming.length > 0 && <><h3>Comes from</h3><div className="row wrap" style={{ gap: 4 }}>{incoming.map((e) => <span key={e.source} className="badge outline">{label(e.source)} · {e.calls}×</span>)}</div></>}
      {outgoing.length > 0 && <><h3>Goes to</h3><div className="row wrap" style={{ gap: 4 }}>{outgoing.map((e) => <span key={e.target} className="badge outline">{label(e.target)} · {e.calls}×</span>)}</div></>}
      {node.kind === "model" && <p><Link to={`/models?model=${encodeURIComponent(node.label)}`}>About this model →</Link></p>}
      {node.kind === "mcp" && <p><Link to={`/mcps?server=${encodeURIComponent(node.label)}`}>See its tools →</Link></p>}
      {node.kind === "tool" && <p><Link to={`/mcps?tool=${encodeURIComponent(node.label)}`}>About this tool →</Link></p>}
      {node.traces.length > 0 && <><h3>Questions that used it</h3>
        <ul className="plain-list">{node.traces.slice(0, 6).map((id) => <li key={id}><Link to={`/conversations?q=${id}`}>{detailed ? id.slice(0, 10) : "Open question"} →</Link></li>)}</ul></>}
    </aside>
  );
}

function AgentView({ name }: { name: string }) {
  const [params, setParams] = useSearchParams();
  const graph = useQuery({ queryKey: ["agent-graph", name], queryFn: () => api.agentGraph(name), refetchInterval: useLiveInterval() });
  const nodeId = params.get("node");
  const select = (id: string | null) => { const next = new URLSearchParams(params); if (id) next.set("node", id); else next.delete("node"); setParams(next, { replace: true }); };
  return (
    <QueryState query={graph} empty={{ when: (g) => g.nodes.length === 0, title: "Nothing to draw yet" }}>
      {(g) => {
        const { nodes, edges } = graphParts(g);
        const selected = g.nodes.find((n) => n.id === nodeId) ?? null;
        return (
          <Card title={<>How <em>{name}</em> works</>} actions={g.approximate ? <span className="badge medium" title="This agent does not record its steps, so the order of its model and tool calls is shown instead.">approximate</span> : <span className="badge outline">{g.framework}</span>}>
            <div className="flow-layout">
              <FlowGraph nodes={nodes} edges={edges} roots={["start"]} last={[]} kindLabels={KIND_WORDS} selectedId={selected?.id ?? null} onSelect={select}
                ariaLabel={`Steps of the agent ${name}`} height={480} columnGap={235}
                legend={<><span><i className="swatch step" /> step</span><span><i className="swatch model" /> model</span><span><i className="swatch tool" /> tool</span><span><i className="swatch mcp" /> MCP server</span><span><i className="swatch gateway" /> gateway</span><span className="muted">thicker arrow = used more · dashed = loops back</span></>} />
              {selected && <NodePanel node={selected} graph={g} onClose={() => select(null)} />}
            </div>
          </Card>
        );
      }}
    </QueryState>
  );
}

export function Agents() {
  const [params, setParams] = useSearchParams();
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents, refetchInterval: useLiveInterval() });
  return (
    <>
      <PageHead title={PAGES.agents.title} about={PAGES.agents.about} help={PAGES.agents.help} />
      <QueryState query={agents} empty={{ when: (a) => a.length === 0, title: "No agent has answered a question yet", hint: <FirstRun kind="overview" title="No agent has answered a question yet" /> }}>
        {(list) => {
          const current = list.find((a) => a.name === params.get("agent")) ?? list[0];
          return (
            <div className="col" style={{ gap: 16 }}>
              <div className="gcards" role="list" aria-label="Agents">
                {list.map((agent) => <div role="listitem" key={agent.name}><AgentCard agent={agent} selected={agent.name === current.name} onPick={() => setParams({ agent: agent.name })} /></div>)}
              </div>
              {current ? <AgentView key={current.name} name={current.name} /> : <EmptyState title="Pick an agent" />}
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
