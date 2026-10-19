import { describe, expect, it } from "vitest";
import { findBackEdges, layoutGraph, pathAround, rankNodes } from "./layout";

// The real shape of the bookshop agent: start -> agent -> tools -> agent (a loop) -> end, with a model, tools and an MCP server.
const nodes = ["start", "agent", "tools", "end", "model", "search", "price", "mcp"].map((id) => ({ id, kind: id === "end" ? "end" : "x" }));
const edges = [["start", "agent"], ["agent", "tools"], ["tools", "agent"], ["agent", "end"], ["agent", "model"], ["tools", "search"],
  ["tools", "price"], ["search", "mcp"], ["price", "mcp"]].map(([source, target]) => ({ source, target }));

describe("graph layout", () => {
  it("finds the edge that closes the agent <-> tools loop", () => {
    expect([...findBackEdges(nodes, edges, ["start"])]).toEqual(["tools->agent"]);
  });

  it("puts every node to the right of what leads to it, and the end last", () => {
    const back = findBackEdges(nodes, edges, ["start"]);
    const rank = rankNodes(nodes, edges, back);
    for (const edge of edges.filter((e) => !back.has(`${e.source}->${e.target}`))) {
      if (edge.target !== "end") expect(rank.get(edge.target)!).toBeGreaterThan(rank.get(edge.source)!);
    }
    expect(rank.get("end")).toBe(Math.max(...rank.values()));
    expect(rank.get("start")).toBe(0);
  });

  it("gives each node its own spot", () => {
    const placed = layoutGraph(nodes, edges, { roots: ["start"] });
    expect(placed).toHaveLength(nodes.length);
    expect(new Set(placed.map((p) => `${p.x},${p.y}`)).size).toBe(nodes.length);
  });

  it("highlights only the path through a node", () => {
    const back = findBackEdges(nodes, edges, ["start"]);
    const around = pathAround("search", edges, back);
    expect(around).toEqual(new Set(["search", "tools", "agent", "start", "mcp"]));
    expect(around.has("price")).toBe(false);
  });

  it("copes with an empty graph and a single node", () => {
    expect(layoutGraph([], [])).toEqual([]);
    expect(layoutGraph([{ id: "a", kind: "x" }], [])).toEqual([{ id: "a", x: 0, y: 0, rank: 0 }]);
  });
});
