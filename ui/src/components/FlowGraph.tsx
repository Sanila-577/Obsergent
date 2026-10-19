// A left-to-right graph of boxes and arrows, used by the Agents page (the steps of an agent) and the Connections page (who
// uses which MCP server). Hovering a box follows its path and dims the rest; clicking selects it; arrow thickness is the traffic.
import {
  Background, Controls, Handle, MarkerType, MiniMap, Panel, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Maximize2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { findBackEdges, layoutGraph, pathAround } from "../lib/layout";

export interface FlowNodeInfo {
  id: string;
  kind: string;
  label: string;
  /** A second line under the name, e.g. "12 calls". */
  sub?: string;
  /** A small badge at the right of the name, e.g. "via gateway". */
  badge?: string;
  tone?: "bad";
}

export interface FlowEdgeInfo {
  source: string;
  target: string;
  calls: number;
  errors: number;
  /** Shown on the arrow while the path is hovered, e.g. "3 calls · 120 ms". */
  label: string;
}

interface NodeData extends Record<string, unknown> {
  info: FlowNodeInfo;
  kindLabel: string;
  dimmed: boolean;
  selected: boolean;
}

// One box. The handles on the sides carry the normal flow; the ones at the bottom carry loops (agent -> tools -> agent).
function FlowNode({ data }: NodeProps<Node<NodeData>>) {
  const { info, kindLabel, dimmed, selected } = data;
  return (
    <div className={`flow-node ${info.kind}${selected ? " selected" : ""}${dimmed ? " dimmed" : ""}${info.tone ? ` ${info.tone}` : ""}`}>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <Handle id="bi" type="target" position={Position.Bottom} />
      <Handle id="bo" type="source" position={Position.Bottom} />
      <small>{kindLabel}</small>
      <strong>{info.label}</strong>
      {info.badge && <span className="badge gateway">{info.badge}</span>}
      {info.sub && <div className="flow-sub">{info.sub}</div>}
    </div>
  );
}

const nodeTypes = { flow: FlowNode };
// Arrow colours must be real colours (the library draws them in SVG), so they cannot be CSS variables.
const GOOD = "#38bdf8";
const BAD = "#f87171";

interface Props {
  nodes: FlowNodeInfo[];
  edges: FlowEdgeInfo[];
  /** Words for each kind of box, e.g. { model: "model", mcp: "MCP server" }. */
  kindLabels: Record<string, string>;
  roots?: string[];
  last?: string[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  ariaLabel: string;
  height?: number;
  columnGap?: number;
  legend?: ReactNode;
}

function Canvas({ nodes, edges, kindLabels, roots = [], last = ["end"], selectedId, onSelect, ariaLabel, height = 520, columnGap = 250, legend }: Props) {
  const [hover, setHover] = useState<string | null>(null);
  const flow = useReactFlow();

  // The layout depends only on the shape of the graph, not on hover or selection.
  const layout = useMemo(() => {
    const back = findBackEdges(nodes, edges, roots);
    const placed = new Map(layoutGraph(nodes, edges, { roots, last, columnGap }).map((p) => [p.id, p]));
    return { back, placed };
  }, [nodes, edges, roots, last, columnGap]);

  // While a box is hovered (or selected) everything not on a path through it is dimmed.
  const focus = hover ?? selectedId;
  const around = useMemo(() => (focus ? pathAround(focus, edges, layout.back) : null), [focus, edges, layout.back]);

  const flowNodes = nodes.map<Node<NodeData>>((info) => ({
    id: info.id, type: "flow", draggable: true,
    position: { x: layout.placed.get(info.id)?.x ?? 0, y: layout.placed.get(info.id)?.y ?? 0 },
    data: { info, kindLabel: kindLabels[info.kind] ?? info.kind, dimmed: around ? !around.has(info.id) : false, selected: info.id === selectedId },
  }));
  const flowEdges = edges.map<Edge>((edge) => {
    const key = `${edge.source}->${edge.target}`;
    const isBack = layout.back.has(key);
    const onPath = around ? around.has(edge.source) && around.has(edge.target) : true;
    const colour = edge.errors ? BAD : GOOD;
    return {
      id: key, source: edge.source, target: edge.target,
      sourceHandle: isBack ? "bo" : undefined, targetHandle: isBack ? "bi" : undefined, type: isBack ? "smoothstep" : "default",
      label: around && onPath ? edge.label : undefined,
      markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: colour },
      className: around && onPath ? "flow-edge-animated" : undefined,
      style: { stroke: colour, strokeWidth: 1.2 + Math.min(3, Math.log10(edge.calls + 1) * 2), opacity: onPath ? 1 : 0.14, strokeDasharray: isBack ? "6 4" : undefined },
      labelStyle: { fill: "var(--text)", fontSize: 11.5, fontWeight: 600 }, labelBgStyle: { fill: "var(--panel)" }, labelBgPadding: [6, 3] as [number, number],
    };
  });

  return (
    <div className="flow" style={{ height }} role="group" aria-label={ariaLabel}>
      <ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.18 }} minZoom={0.25}
        nodesConnectable={false} elementsSelectable proOptions={{ hideAttribution: true }}
        onNodeMouseEnter={(_, node) => setHover(node.id)} onNodeMouseLeave={() => setHover(null)}
        onNodeClick={(_, node) => onSelect(node.id === selectedId ? null : node.id)} onPaneClick={() => onSelect(null)}>
        <Background gap={24} color="var(--border)" />
        <Controls showInteractive={false} />
        {nodes.length > 12 && <MiniMap pannable zoomable className="flow-minimap" maskColor="rgba(0,0,0,.25)" nodeColor="#38bdf8" nodeStrokeWidth={2} />}
        <Panel position="top-right">
          <button className="small" onClick={() => { onSelect(null); flow.fitView({ padding: 0.18, duration: 300 }); }}><Maximize2 size={13} /> Reset view</button>
        </Panel>
        {legend && <Panel position="top-left"><div className="legend flow-legend">{legend}</div></Panel>}
      </ReactFlow>
    </div>
  );
}

export function FlowGraph(props: Props) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>;
}
