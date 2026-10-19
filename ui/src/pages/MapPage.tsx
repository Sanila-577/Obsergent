// The MCP map: who calls which server, and which tools each server serves. Click a node to see its runs.
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { TopologyNode } from "../api/types";
import { FirstRun } from "../components/FirstRun";
import { Card, PageHead, QueryState } from "../components/ui";
import { PAGES } from "../lib/words";
import { useSettings } from "../lib/state";

type NodeData = { node: TopologyNode };

function MapNode({ data }: NodeProps<Node<NodeData>>) {
  const { node } = data;
  return (
    <div className={`map-node ${node.kind}`}>
      <Handle type="target" position={Position.Left} /><small>{node.kind === "client" ? "app / agent" : node.kind}</small>
      <strong>{node.label}</strong>{node.via_gateway && <span className="badge gateway" style={{ marginLeft: 6 }}>via gateway</span>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { map: MapNode };
const COLUMN: Record<TopologyNode["kind"], number> = { client: 0, server: 1, tool: 2 };

export function MapPage() {
  const { hours } = useSettings();
  const navigate = useNavigate();
  const topology = useQuery({ queryKey: ["topology", hours], queryFn: () => api.topology(hours) });

  const { nodes, edges } = useMemo(() => {
    const data = topology.data;
    if (!data) return { nodes: [] as Node<NodeData>[], edges: [] as Edge[] };
    const rowOf: Record<string, number> = { client: 0, server: 0, tool: 0 };
    const nodes = data.nodes.map<Node<NodeData>>((node) => ({
      id: node.id, type: "map", position: { x: COLUMN[node.kind] * 330, y: rowOf[node.kind]++ * 96 }, data: { node },
    }));
    const edges = data.edges.map<Edge>((edge) => {
      const colour = edge.errors ? "#f87171" : "#38bdf8"; // marker colours must be real colours, not CSS variables
      return {
        id: `${edge.source}->${edge.target}`, source: edge.source, target: edge.target,
        label: `${edge.calls} call${edge.calls === 1 ? "" : "s"}${edge.errors ? ` · ${edge.errors} failed` : ""}`,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: colour },
        style: { stroke: colour, strokeWidth: 1.2 + Math.min(2.2, Math.log10(edge.calls + 1)) }, // thicker = more traffic
        labelStyle: { fill: "var(--text)", fontSize: 11 }, labelBgStyle: { fill: "var(--panel)" }, labelBgPadding: [6, 3],
      };
    });
    return { nodes, edges };
  }, [topology.data]);

  return (
    <>
      <PageHead title={PAGES.map.title} about={PAGES.map.about} />
      <QueryState query={topology} empty={{ when: (t) => t.nodes.length === 0, title: "No connections yet", hint: <FirstRun kind="map" title="No connections yet" /> }}>
        {() => (
          <Card flush>
            <div style={{ height: 560 }} aria-label="Connections between apps, tool servers and tools">
              <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.3} nodesDraggable proOptions={{ hideAttribution: true }}
                onNodeClick={(_, node) => {
                  const { kind, label } = (node.data as NodeData).node;
                  if (kind === "server") navigate(`/runs?server=${label}`);
                  else if (kind === "tool") navigate(`/runs?tool=${label}`);
                }}>
                <Background gap={22} color="var(--border)" /><Controls showInteractive={false} />
              </ReactFlow>
            </div>
          </Card>
        )}
      </QueryState>
    </>
  );
}
