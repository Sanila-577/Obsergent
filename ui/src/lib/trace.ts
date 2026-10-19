// Pure logic for drawing a run: the span tree, which layer each span belongs to, the critical path and
// how to reproduce a call. No React in here, so it is easy to test.
// Types only.
import type { Smell, Span } from "../api/types";

// The five parts of the system a span can come from.
export type Layer = "agent" | "model" | "proxy" | "gateway" | "server";

// Text shown for each layer.
export const LAYER_LABEL: Record<Layer, string> = {
  agent: "Agent",
  model: "Model",
  proxy: "Proxy",
  gateway: "Gateway",
  server: "Server",
};

/** Which part of the system produced a span. */
// Decide which layer produced a span, from its attributes.
export function layerOf(span: Span): Layer {
  // Shortcut.
  const attrs = span.attributes;
  // Marked by the server as an API Manager span.
  if (attrs["obsergent.layer"] === "gateway") return "gateway";
  // Recorded by the Obsergent proxy (it has MCP method info).
  if (span.service === "obsergent-proxy" || attrs["mcp.method.name"]) return "proxy";
  // A model call.
  if (attrs["openinference.span.kind"] === "LLM") return "model";
  // Another agent step (chain, tool...).
  if (attrs["openinference.span.kind"]) return "agent";
  // Otherwise guess from the program name.
  return span.service.includes("server") ? "server" : "agent";
}

// One span placed in the tree.
export interface TreeNode {
  span: Span;
  depth: number;
  children: TreeNode[];
  /** True when this span lies on the slowest chain from the root (the critical path). */
  critical: boolean;
}

/** Build the span tree. A span whose parent is not in the trace becomes a root. */
// Turn the flat span list into a tree using parent ids.
export function buildTree(spans: Span[]): TreeNode[] {
  // All span ids in the run.
  const ids = new Set(spans.map((s) => s.span_id));
  // parent id -> its children.
  const byParent = new Map<string | null, Span[]>();
  // Go through spans oldest first.
  for (const span of [...spans].sort((a, b) => a.start_ns - b.start_ns)) {
    // A missing parent makes the span a root.
    const parent = span.parent_span_id && ids.has(span.parent_span_id) ? span.parent_span_id : null;
    // Add the span to its parent's list.
    byParent.set(parent, [...(byParent.get(parent) ?? []), span]);
  }
  // Build a node and, recursively, its children.
  const make = (span: Span, depth: number): TreeNode => ({
    span,
    depth,
    critical: false,
    children: (byParent.get(span.span_id) ?? []).map((child) => make(child, depth + 1)),
  });
  // The top-level nodes.
  const roots = (byParent.get(null) ?? []).map((span) => make(span, 0));
  // Mark the slowest chain.
  for (const root of roots) markCritical(root);
  return roots;
}

/** Follow, from a node, the child that took the longest: that chain decides how long the node took. */
// From this node follow the slowest child down to a leaf.
function markCritical(node: TreeNode): void {
  // This node is on the slowest path.
  node.critical = true;
  // A leaf ends the path.
  if (!node.children.length) return;
  // Continue into the slowest child.
  markCritical(node.children.reduce((slowest, child) => (child.span.duration_ms > slowest.span.duration_ms ? child : slowest)));
}

// One drawn line of the waterfall.
export interface Row {
  node: TreeNode;
  /** Position and width of the bar as fractions (0..1) of the whole run. */
  left: number;
  width: number;
}

/** Flatten the visible part of the tree (collapsed nodes hide their children) into drawable rows. */
// Turn the tree into rows, skipping collapsed or non-matching parts.
export function flatten(roots: TreeNode[], collapsed: Set<string>, matches?: (span: Span) => boolean): Row[] {
  // Every node of the tree in one list.
  const all = roots.flatMap(function walk(node): TreeNode[] {
    return [node, ...node.children.flatMap(walk)];
  });
  // Nothing to draw.
  if (!all.length) return [];
  // When the run began.
  const start = Math.min(...all.map((n) => n.span.start_ns));
  // Length of the run (1 avoids dividing by zero).
  const total = Math.max(...all.map((n) => n.span.end_ns)) - start || 1;
  // Result rows.
  const rows: Row[] = [];
  // Walk the tree, adding rows.
  const visit = (node: TreeNode, ancestorShown: boolean) => {
    // A node is shown if its ancestors are, and it (or a descendant) matches the search.
    const shown = ancestorShown && (!matches || matches(node.span) || hasMatch(node, matches));
    // Add the row: bar position and width as fractions of the run.
    if (shown) {
      rows.push({
        node,
        left: (node.span.start_ns - start) / total,
        width: Math.max((node.span.end_ns - node.span.start_ns) / total, 0.002),
      });
    }
    // Visit children unless this node is collapsed.
    if (!collapsed.has(node.span.span_id)) node.children.forEach((child) => visit(child, ancestorShown && shown));
  };
  // visit => Start from the roots.
  roots.forEach((root) => visit(root, true));
  // The rows to draw.
  return rows;
}

// Does any descendant match the search?
function hasMatch(node: TreeNode, matches: (span: Span) => boolean): boolean {
  return node.children.some((child) => matches(child.span) || hasMatch(child, matches));
}

/** Span ids that an automatic finding points at (shown as a marker on the waterfall). */
// span id -> findings pointing at it.
export function smellIndex(smells: Smell[]): Map<string, Smell[]> {
  const index = new Map<string, Smell[]>();
  for (const smell of smells) {
    if (smell.span_id) index.set(smell.span_id, [...(index.get(smell.span_id) ?? []), smell]);
  }
  return index;
}

// Text to repeat a call.
export interface Reproduction {
  jsonRpc: string;
  curl: string;
}

/** The JSON-RPC message and a curl command that would repeat an MCP call (the caller fills in the URL/token). */
// Build the JSON-RPC message and a curl command for a recorded MCP call.
export function reproduceCall(span: Span): Reproduction | null {
  // Only MCP spans can be reproduced.
  const method = span.attributes["mcp.method.name"];
  if (typeof method !== "string") return null;
  // params of the message.
  const params: Record<string, unknown> = {};
  // For a tool call add its name and arguments.
  if (method === "tools/call") {
    params.name = span.attributes["gen_ai.tool.name"];
    try {
      // The arguments were stored as JSON text.
      params.arguments = JSON.parse(String(span.attributes["mcp.tool.arguments"] ?? "{}"));
    } catch {
      params.arguments = {};
    }
  }
  // The JSON-RPC request.
  const message = { jsonrpc: "2.0", id: 1, method, ...(Object.keys(params).length ? { params } : {}) };
  // Pretty text version.
  const jsonRpc = JSON.stringify(message, null, 2);
  // A shell command the user can run (URL and token are placeholders).
  const curl = [
    "curl -X POST \"$MCP_URL\"",
    "  -H 'content-type: application/json'",
    "  -H 'accept: application/json, text/event-stream'",
    "  -H \"authorization: Bearer $TOKEN\"        # if the server needs one",
    "  -H \"mcp-session-id: $SESSION_ID\"         # after `initialize`",
    `  -d '${JSON.stringify(message)}'`,
  ].join(" \\\n");
  // Both texts.
  return { jsonRpc, curl };
}

/** Every node below `node` (not including it). */
// Every node below a node.
export function descendants(node: TreeNode): TreeNode[] {
  return node.children.flatMap((child) => [child, ...descendants(child)]);
}

/** Milliseconds per gateway phase (key validation, backend, ...) below a gateway call span. */
// Milliseconds per gateway phase under a gateway call.
export function phasesBelow(node: TreeNode): Record<string, number> {
  // phase -> ms.
  const totals: Record<string, number> = {};
  // Look at each descendant span.
  for (const { span } of descendants(node)) {
    // Is it a phase span?
    const phase = span.attributes["gateway.phase"];
    if (typeof phase === "string") totals[phase] = (totals[phase] ?? 0) + Number(span.attributes["gateway.latency_ms"] ?? span.duration_ms);
  }
  return totals;
}

/** The node of one span anywhere in the forest, or undefined. */
// Find a span's node anywhere in the tree.
export function findNode(roots: TreeNode[], spanId: string): TreeNode | undefined {
  // Search each root and, recursively, its children.
  for (const root of roots) {
    if (root.span.span_id === spanId) return root;
    const inside = findNode(root.children, spanId);
    if (inside) return inside;
  }
  // Not found.
  return undefined;
}
