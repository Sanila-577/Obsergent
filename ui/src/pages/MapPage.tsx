// Connections: who uses which MCP server. Layers from left to right: apps and agents, the gateway (when there is one), MCP servers.
// A server's tools are hidden until you open them, so the picture stays readable. Hover follows a path; click shows details.
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Topology, TopologyNode } from "../api/types";
import { FirstRun } from "../components/FirstRun";
import { FlowGraph, type FlowEdgeInfo, type FlowNodeInfo } from "../components/FlowGraph";
import { Card, PageHead, QueryState } from "../components/ui";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

const KIND_WORDS: Record<string, string> = { client: "app or agent", gateway: "gateway", server: "MCP server", tool: "tool" };

// Turn the API's nodes and edges into boxes and arrows.
export function topologyParts(data: Topology): { nodes: FlowNodeInfo[]; edges: FlowEdgeInfo[] } {
  const nodes = data.nodes.map<FlowNodeInfo>((node) => ({
    id: node.id, kind: node.kind, label: node.label, badge: node.kind === "server" && node.via_gateway ? "via gateway" : undefined,
    sub: node.kind === "server" && node.tool_count ? `${node.tool_count} tool${node.tool_count === 1 ? "" : "s"} used` : undefined,
  }));
  const edges = data.edges.map<FlowEdgeInfo>((edge) => ({
    source: edge.source, target: edge.target, calls: edge.calls, errors: edge.errors,
    label: `${edge.calls} call${edge.calls === 1 ? "" : "s"}${edge.errors ? ` · ${edge.errors} failed` : ""}`,
  }));
  return { nodes, edges };
}

function Panel({ node, data, expanded, onToggle, onClose }: { node: TopologyNode; data: Topology; expanded: boolean; onToggle: () => void; onClose: () => void }) {
  const calls = data.edges.filter((e) => e.target === node.id).reduce((sum, e) => sum + e.calls, 0)
    || data.edges.filter((e) => e.source === node.id).reduce((sum, e) => sum + e.calls, 0);
  const errors = data.edges.filter((e) => e.target === node.id || e.source === node.id).reduce((sum, e) => sum + e.errors, 0);
  return (
    <aside className="flow-panel" aria-label={`Details of ${node.label}`}>
      <div className="row spread"><span className="badge outline">{KIND_WORDS[node.kind]}</span><button className="small ghost" onClick={onClose}>Close</button></div>
      <h2 style={{ marginTop: 8 }}>{node.label}</h2>
      <p className="muted">{calls} call{calls === 1 ? "" : "s"} through here{errors ? `, ${errors} failed` : ""}.</p>
      {node.kind === "server" && (
        <p className="col" style={{ gap: 8 }}>
          {(node.tool_count ?? 0) > 0 && <button onClick={onToggle}>{expanded ? "Hide its tools" : `Show its ${node.tool_count} tool${node.tool_count === 1 ? "" : "s"}`}</button>}
          <Link className="btn" to={`/mcps?server=${encodeURIComponent(node.label)}`}>Open the MCP page →</Link>
          <Link className="btn" to={`/runs?server=${encodeURIComponent(node.label)}`}>See its activity →</Link>
        </p>
      )}
      {node.kind === "client" && <p className="col" style={{ gap: 8 }}><Link className="btn" to={`/agents?agent=${encodeURIComponent(node.label)}`}>Open the agent →</Link><Link className="btn" to={`/runs?q=${encodeURIComponent(node.label)}`}>See its activity →</Link></p>}
      {node.kind === "gateway" && <p><Link className="btn" to="/gateway">Open the gateway page →</Link></p>}
      {node.kind === "tool" && <p><Link className="btn" to={`/mcps?tool=${encodeURIComponent(node.label)}`}>About this tool →</Link></p>}
    </aside>
  );
}

export function MapPage() {
  const { hours } = useSettings();
  const [expand, setExpand] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const topology = useQuery({ queryKey: ["topology", hours, expand], queryFn: () => api.topology(hours, expand.join(",")), placeholderData: (previous) => previous, refetchInterval: useLiveInterval() });
  const parts = useMemo(() => (topology.data ? topologyParts(topology.data) : { nodes: [], edges: [] }), [topology.data]);
  const roots = useMemo(() => (topology.data?.nodes ?? []).filter((n) => n.kind === "client").map((n) => n.id), [topology.data]);

  return (
    <>
      <PageHead title={PAGES.map.title} about={PAGES.map.about} help={PAGES.map.help}>
        {topology.data && topology.data.nodes.some((n) => n.kind === "server" && (n.tool_count ?? 0) > 0) && (
          <button onClick={() => setExpand(expand.length ? [] : ["*"])}>{expand.length ? "Hide all tools" : "Show all tools"}</button>
        )}
      </PageHead>
      <QueryState query={topology} empty={{ when: (t) => t.nodes.length === 0, title: "No connections yet", hint: <FirstRun kind="map" title="No connections yet" /> }}>
        {(data) => {
          const selected = data.nodes.find((n) => n.id === selectedId) ?? null;
          return (
            <Card>
              <div className="flow-layout">
                <FlowGraph nodes={parts.nodes} edges={parts.edges} roots={roots} last={[]} kindLabels={KIND_WORDS} selectedId={selected?.id ?? null}
                  onSelect={setSelectedId} ariaLabel="Connections between apps, the gateway and MCP servers" height={500} columnGap={270}
                  legend={<><span><i className="swatch client" /> app or agent</span><span><i className="swatch gateway" /> gateway</span><span><i className="swatch server" /> MCP server</span><span><i className="swatch tool" /> tool</span><span className="muted">thicker arrow = more calls · hover a box to follow its path</span></>} />
                {selected && <Panel node={selected} data={data} expanded={expand.includes("*") || expand.includes(selected.label)} onClose={() => setSelectedId(null)}
                  onToggle={() => setExpand((now) => (now.includes(selected.label) ? now.filter((n) => n !== selected.label) : [...now.filter((n) => n !== "*"), selected.label]))} />}
              </div>
            </Card>
          );
        }}
      </QueryState>
    </>
  );
}
