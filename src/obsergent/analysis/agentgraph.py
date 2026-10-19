"""The shape of an agent: which steps it runs, which models and tools each step uses, and which MCP server serves the tools.

Rebuilt from the recorded spans of all the questions an agent answered (pure functions: no database, no network).
Frameworks that record a graph (LangGraph: a `LangGraph` span whose children are the nodes `agent`, `tools`...) give the
exact graph. For any other agent the model and tool calls are chained in the order they happened and the result is
marked `approximate`.

    nodes  start, end, step (a graph node), model, tool, mcp (an MCP server), gateway
    edges  start->agent, agent->tools, tools->agent, agent->end   (the order the steps ran in)
           agent->model, tools->tool, tool->mcp, mcp->gateway     (what happens inside a step)
Every edge carries how often it was used, the average time and the number of failures; the thickness in the UI is the count.
"""
# defaultdict creates missing entries on first use.
from collections import defaultdict

# Span kinds and the model-call test.
from obsergent.analysis.generations import LLM_KIND, SPAN_KIND, TOOL_KIND, is_generation
from obsergent.analysis.modelnames import display
from obsergent.models import Span

# The span a graph framework records around the whole run.
GRAPH_SPAN_NAMES = ("LangGraph",)


def framework_of(runs: list[list[Span]]) -> str:
    """Which agent framework recorded these runs ('LangGraph', or 'custom' when nothing says)."""
    return "LangGraph" if any(span.name in GRAPH_SPAN_NAMES for spans in runs for span in spans) else "custom"


class GraphBuilder:
    """Collects nodes and edges over many questions."""

    def __init__(self, costs: dict[str, float] | None = None):
        # span_id -> dollars (so model nodes can show their cost).
        self.costs = costs or {}
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str], dict] = {}

    def node(self, node_id: str, kind: str, label: str, span: Span | None = None, trace_id: str = "") -> None:
        """Count one more use of a node (and the time and failure of the span that used it)."""
        entry = self.nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label, "calls": 0, "total_ms": 0.0,
                                                "errors": 0, "cost_usd": 0.0, "traces": []})
        if span is not None:
            entry["calls"] += 1
            entry["total_ms"] += span.duration_ms
            entry["errors"] += span.status_code == "ERROR"
            entry["cost_usd"] += self.costs.get(span.span_id, 0.0)
        if trace_id and trace_id not in entry["traces"] and len(entry["traces"]) < 20:
            entry["traces"].append(trace_id)

    def edge(self, source: str, target: str, span: Span | None = None) -> None:
        """Count one more crossing of an edge (with the time of the span it leads to)."""
        entry = self.edges.setdefault((source, target), {"source": source, "target": target, "calls": 0, "total_ms": 0.0,
                                                         "errors": 0})
        entry["calls"] += 1
        if span is not None:
            entry["total_ms"] += span.duration_ms
            entry["errors"] += span.status_code == "ERROR"

    def result(self, framework: str, approximate: bool) -> dict:
        """The finished graph with averages instead of totals."""
        nodes = [node | {"avg_ms": node["total_ms"] / node["calls"] if node["calls"] else None} for node in self.nodes.values()]
        edges = [edge | {"avg_ms": edge["total_ms"] / edge["calls"] if edge["calls"] else None} for edge in self.edges.values()]
        return {"framework": framework, "approximate": approximate, "nodes": nodes, "edges": edges}


def descendants(span: Span, children: dict[str, list[Span]]) -> list[Span]:
    """Every span below `span`, in start order."""
    found, stack = [], list(children.get(span.span_id, []))
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(children.get(current.span_id, []))
    return sorted(found, key=lambda s: s.start_ns)


def add_step_contents(builder: GraphBuilder, step_id: str, step: Span, children: dict[str, list[Span]], trace_id: str) -> None:
    """What happens inside one graph step: its model calls, its tools, the MCP servers behind them, the gateway."""
    below = descendants(step, children)
    for span in below:
        if is_generation(span) and span.attributes.get(SPAN_KIND, LLM_KIND) == LLM_KIND:
            model_id = f"model:{display(span.attributes.get('llm.model_name') or span.attributes.get('gen_ai.request.model'))}"
            builder.node(model_id, "model", model_id.split(":", 1)[1], span, trace_id)
            builder.edge(step_id, model_id, span)
        elif span.attributes.get(SPAN_KIND) == TOOL_KIND:
            name = span.attributes.get("tool.name") or span.name
            tool_id = f"tool:{name}"
            builder.node(tool_id, "tool", name, span, trace_id)
            builder.edge(step_id, tool_id, span)
            add_tool_backend(builder, tool_id, span, children, trace_id)


def add_tool_backend(builder: GraphBuilder, tool_id: str, tool_span: Span, children: dict[str, list[Span]],
                     trace_id: str) -> None:
    """The MCP server that ran a tool (from the proxy's span below the tool step) and the gateway decision, if any."""
    for span in children.get(tool_span.span_id, []):
        server = span.attributes.get("mcp.server.name")
        if span.attributes.get("mcp.method.name") != "tools/call" or not server:
            continue
        server_id = f"mcp:{server}"
        builder.node(server_id, "mcp", server, span, trace_id)
        builder.edge(tool_id, server_id, span)
        if span.attributes.get("gateway.decision") is not None:
            builder.node("gateway", "gateway", "gateway", span, trace_id)
            builder.edge(server_id, "gateway", span)


def add_graph_run(builder: GraphBuilder, spans: list[Span], graph: Span, children: dict[str, list[Span]], trace_id: str) -> None:
    """One question of a LangGraph agent: the order the nodes ran in, and what each node used."""
    steps = [span for span in children.get(graph.span_id, []) if span.attributes.get(SPAN_KIND) in ("AGENT", "CHAIN", "TOOL")]
    previous = "start"
    builder.node("start", "start", "question", None, trace_id)
    for step in steps:
        step_id = f"step:{step.name}"
        builder.node(step_id, "step", step.name, step, trace_id)
        builder.edge(previous, step_id, step)
        add_step_contents(builder, step_id, step, children, trace_id)
        previous = step_id
    builder.node("end", "end", "answer", None, trace_id)
    builder.edge(previous, "end")


def add_plain_run(builder: GraphBuilder, spans: list[Span], children: dict[str, list[Span]], trace_id: str) -> None:
    """One question of an agent that records no graph: model calls and tools chained in the order they happened."""
    work = sorted((s for s in spans if is_generation(s) or s.attributes.get(SPAN_KIND) == TOOL_KIND), key=lambda s: s.start_ns)
    previous = "start"
    builder.node("start", "start", "question", None, trace_id)
    for span in work:
        if is_generation(span):
            node_id = f"model:{display(span.attributes.get('llm.model_name') or span.attributes.get('gen_ai.request.model'))}"
            builder.node(node_id, "model", node_id.split(":", 1)[1], span, trace_id)
        else:
            name = span.attributes.get("tool.name") or span.name
            node_id = f"tool:{name}"
            builder.node(node_id, "tool", name, span, trace_id)
            add_tool_backend(builder, node_id, span, children, trace_id)
        builder.edge(previous, node_id, span)
        previous = node_id
    builder.node("end", "end", "answer", None, trace_id)
    builder.edge(previous, "end")


def build_graph(runs: dict[str, list[Span]], costs: dict[str, float] | None = None) -> dict:
    """The aggregated graph of an agent: `runs` maps each question's trace id to its spans."""
    builder = GraphBuilder(costs)
    approximate = False
    for trace_id, spans in runs.items():
        children: dict[str, list[Span]] = defaultdict(list)
        for span in sorted(spans, key=lambda s: s.start_ns):
            if span.parent_span_id:
                children[span.parent_span_id].append(span)
        graph = next((span for span in spans if span.name in GRAPH_SPAN_NAMES), None)
        if graph:
            add_graph_run(builder, spans, graph, children, trace_id)
        else:
            approximate = True
            add_plain_run(builder, spans, children, trace_id)
    return builder.result(framework_of(list(runs.values())), approximate)
