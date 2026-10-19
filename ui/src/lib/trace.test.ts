import type { Span } from "../api/types";
import { buildTree, findNode, flatten, layerOf, phasesBelow, reproduceCall, smellIndex } from "./trace";

let counter = 0;
function span(partial: Partial<Span> & { attributes?: Span["attributes"] }): Span {
  counter += 1;
  return {
    trace_id: "t", span_id: `s${counter}`, parent_span_id: null, name: "span", kind: "INTERNAL", service: "agent",
    start_ns: 0, end_ns: 1_000_000, duration_ms: 1, status_code: "UNSET", status_message: "", attributes: {}, events: [], ...partial,
  };
}

describe("layerOf", () => {
  it("recognises each part of the system", () => {
    expect(layerOf(span({ attributes: { "obsergent.layer": "gateway" } }))).toBe("gateway");
    expect(layerOf(span({ service: "obsergent-proxy" }))).toBe("proxy");
    expect(layerOf(span({ attributes: { "mcp.method.name": "tools/call" } }))).toBe("proxy");
    expect(layerOf(span({ attributes: { "openinference.span.kind": "LLM" } }))).toBe("model");
    expect(layerOf(span({ attributes: { "openinference.span.kind": "CHAIN" } }))).toBe("agent");
    expect(layerOf(span({ service: "bookshop-server" }))).toBe("server");
    expect(layerOf(span({ service: "my-agent" }))).toBe("agent");
  });
});

describe("buildTree", () => {
  const root = span({ span_id: "root", start_ns: 0, end_ns: 10_000_000, duration_ms: 10 });
  const fast = span({ span_id: "fast", parent_span_id: "root", start_ns: 1_000_000, end_ns: 2_000_000, duration_ms: 1 });
  const slow = span({ span_id: "slow", parent_span_id: "root", start_ns: 2_000_000, end_ns: 9_000_000, duration_ms: 7 });
  const deep = span({ span_id: "deep", parent_span_id: "slow", start_ns: 3_000_000, end_ns: 8_000_000, duration_ms: 5 });

  it("nests children and marks the slowest chain as critical", () => {
    const [tree] = buildTree([deep, fast, root, slow]); // given out of order
    expect(tree.span.span_id).toBe("root");
    expect(tree.children.map((c) => c.span.span_id)).toEqual(["fast", "slow"]); // ordered by start time
    expect(tree.children[1].children[0].depth).toBe(2);
    const critical = (n: typeof tree): string[] => [n.span.span_id, ...n.children.filter((c) => c.critical).flatMap(critical)];
    expect(critical(tree)).toEqual(["root", "slow", "deep"]);
    expect(tree.children[0].critical).toBe(false);
  });

  it("treats a span whose parent is missing as a root", () => {
    const orphan = span({ span_id: "orphan", parent_span_id: "gone" });
    expect(buildTree([orphan, root]).map((n) => n.span.span_id).sort()).toEqual(["orphan", "root"]);
  });

  it("finds a node anywhere in the tree", () => {
    expect(findNode(buildTree([root, slow, deep]), "deep")?.depth).toBe(2);
    expect(findNode(buildTree([root]), "nope")).toBeUndefined();
  });

  it("hides the children of collapsed nodes and scales bars to the whole run", () => {
    const tree = buildTree([root, fast, slow, deep]);
    expect(flatten(tree, new Set()).length).toBe(4);
    expect(flatten(tree, new Set(["slow"])).map((r) => r.node.span.span_id)).toEqual(["root", "fast", "slow"]);
    const rows = flatten(tree, new Set());
    expect(rows[0].left).toBe(0);
    expect(rows[0].width).toBe(1);
    expect(rows[2].left).toBeCloseTo(0.2);
    expect(flatten([], new Set())).toEqual([]);
  });

  it("keeps the ancestors of a search match visible", () => {
    const tree = buildTree([root, fast, slow, deep]);
    const rows = flatten(tree, new Set(), (s) => s.span_id === "deep");
    expect(rows.map((r) => r.node.span.span_id)).toEqual(["root", "slow", "deep"]);
  });
});

describe("gateway phases", () => {
  it("adds up the phase spans below a gateway call", () => {
    const call = span({ span_id: "call" });
    const phase = (id: string, name: string, ms: number) => span({ span_id: id, parent_span_id: "call", attributes: { "gateway.phase": name, "gateway.latency_ms": ms } });
    const node = findNode(buildTree([call, phase("a", "backend", 2), phase("b", "backend", 1), phase("c", "key_validation", 4)]), "call")!;
    expect(phasesBelow(node)).toEqual({ backend: 3, key_validation: 4 });
  });
});

describe("smellIndex / reproduceCall", () => {
  it("groups findings by span", () => {
    const index = smellIndex([{ type: "tool_error", severity: "medium", message: "x", span_id: "s1" }, { type: "loop", severity: "high", message: "y" }]);
    expect(index.get("s1")?.length).toBe(1);
    expect(index.size).toBe(1);
  });

  it("rebuilds the JSON-RPC message and a curl command for an MCP call", () => {
    const call = span({ attributes: { "mcp.method.name": "tools/call", "gen_ai.tool.name": "search", "mcp.tool.arguments": '{"q":"python"}' } });
    const reproduction = reproduceCall(call)!;
    expect(JSON.parse(reproduction.jsonRpc)).toEqual({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "search", arguments: { q: "python" } } });
    expect(reproduction.curl).toContain('curl -X POST "$MCP_URL"');
    expect(reproduction.curl).toContain('"method":"tools/call"');
    expect(reproduceCall(span({}))).toBeNull();
  });

  it("copes with unreadable arguments", () => {
    const call = span({ attributes: { "mcp.method.name": "tools/call", "gen_ai.tool.name": "t", "mcp.tool.arguments": "{truncated" } });
    expect(JSON.parse(reproduceCall(call)!.jsonRpc).params.arguments).toEqual({});
  });
});
