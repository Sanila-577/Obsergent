// Left-to-right layout of a graph with loops (agent -> tools -> agent), without a layout library. Pure functions, no React.
//
//   1. Edges that close a loop (they point back to a node still being visited) are "back edges": they are drawn below the graph
//      and ignored when ranking, so the rest is a clean left-to-right flow.
//   2. A node's rank (column) is the longest chain of forward edges leading to it; "end" nodes go to the last column.
//   3. Inside a column, nodes are ordered by the average row of the nodes that lead to them (fewer crossing lines).

export interface LayoutNode {
  id: string;
  kind: string;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

export interface Placed {
  id: string;
  x: number;
  y: number;
  rank: number;
}

/** The edges that point back to a node that is still being visited (they close a loop). */
export function findBackEdges(nodes: LayoutNode[], edges: LayoutEdge[], roots: string[]): Set<string> {
  const out = new Map<string, string[]>();
  for (const edge of edges) out.set(edge.source, [...(out.get(edge.source) ?? []), edge.target]);
  const back = new Set<string>();
  const state = new Map<string, "visiting" | "done">();
  const visit = (id: string) => {
    state.set(id, "visiting");
    for (const next of out.get(id) ?? []) {
      if (state.get(next) === "visiting") back.add(`${id}->${next}`);
      else if (!state.has(next)) visit(next);
    }
    state.set(id, "done");
  };
  for (const root of [...roots, ...nodes.map((n) => n.id)]) if (!state.has(root)) visit(root);
  return back;
}

/** Column (rank) of every node: the longest forward chain to it; nodes whose kind is in `last` go to the final column. */
export function rankNodes(nodes: LayoutNode[], edges: LayoutEdge[], back: Set<string>, last: string[] = ["end"]): Map<string, number> {
  const forward = edges.filter((edge) => !back.has(`${edge.source}->${edge.target}`));
  const rank = new Map(nodes.map((node) => [node.id, 0]));
  // Relax edges repeatedly: at most `nodes.length` rounds are needed because the forward edges have no loop.
  for (let round = 0; round < nodes.length; round++) {
    let changed = false;
    for (const edge of forward) {
      const wanted = (rank.get(edge.source) ?? 0) + 1;
      if (wanted > (rank.get(edge.target) ?? 0)) { rank.set(edge.target, wanted); changed = true; }
    }
    if (!changed) break;
  }
  const max = Math.max(0, ...rank.values());
  for (const node of nodes) if (last.includes(node.kind)) rank.set(node.id, Math.max(max, rank.get(node.id) ?? 0));
  return rank;
}

/** Positions for every node: `columnGap` pixels between columns, `rowGap` between nodes of one column, columns centred. */
export function layoutGraph(nodes: LayoutNode[], edges: LayoutEdge[], options: { roots?: string[]; columnGap?: number; rowGap?: number; last?: string[] } = {}): Placed[] {
  const { roots = [], columnGap = 250, rowGap = 92, last = ["end"] } = options;
  const back = findBackEdges(nodes, edges, roots);
  const rank = rankNodes(nodes, edges, back, last);
  const columns = new Map<number, string[]>();
  for (const node of nodes) columns.set(rank.get(node.id) ?? 0, [...(columns.get(rank.get(node.id) ?? 0) ?? []), node.id]);
  const row = new Map<string, number>();
  const placed: Placed[] = [];
  for (const column of [...columns.keys()].sort((a, b) => a - b)) {
    const ids = columns.get(column)!;
    // Order by the average row of the predecessors that are already placed (stable for the first column).
    const score = (id: string) => {
      const before = edges.filter((edge) => edge.target === id && row.has(edge.source)).map((edge) => row.get(edge.source)!);
      return before.length ? before.reduce((a, b) => a + b, 0) / before.length : Number.MAX_SAFE_INTEGER;
    };
    ids.sort((a, b) => score(a) - score(b));
    const top = -((ids.length - 1) * rowGap) / 2;
    ids.forEach((id, index) => {
      row.set(id, top + index * rowGap);
      placed.push({ id, x: column * columnGap, y: top + index * rowGap, rank: column });
    });
  }
  return placed;
}

/** Every node on a path through `id` (what leads to it and what follows it), ignoring loop edges: used to dim the rest on hover. */
export function pathAround(id: string, edges: LayoutEdge[], back: Set<string>): Set<string> {
  const forward = edges.filter((edge) => !back.has(`${edge.source}->${edge.target}`));
  // Walk along the edges in one direction: downstream follows source -> target, upstream the other way round.
  const reach = (downstream: boolean) => {
    const seen = new Set([id]);
    const queue = [id];
    while (queue.length) {
      const current = queue.pop()!;
      for (const edge of forward) {
        const [near, far] = downstream ? [edge.source, edge.target] : [edge.target, edge.source];
        if (near === current && !seen.has(far)) { seen.add(far); queue.push(far); }
      }
    }
    return seen;
  };
  return new Set([...reach(true), ...reach(false)]);
}
