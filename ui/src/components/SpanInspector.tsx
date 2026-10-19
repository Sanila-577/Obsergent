// The side panel for one span: what it was, what went in, what came out, what the gateway did, the raw data.
import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import type { Span } from "../api/types";
import { formatMs, formatTime } from "../lib/format";
import { useSettings } from "../lib/state";
import { buildTree, findNode, layerOf, phasesBelow, reproduceCall } from "../lib/trace";
import { JsonView } from "./JsonView";
import { Card, CopyButton, DecisionBadge, LayerBadge, StackBar, Tabs } from "./ui";

type Tab = "overview" | "arguments" | "result" | "gateway" | "raw";

const SHOWN_IN_OVERVIEW: [string, string][] = [
  ["mcp.method.name", "MCP method"], ["gen_ai.tool.name", "Tool"], ["mcp.server.name", "MCP server"],
  ["llm.model_name", "Model"], ["llm.provider", "Provider"], ["llm.token_count.total", "Tokens"],
  ["obsergent.caller.application", "Caller application"], ["obsergent.caller.client_id", "Caller client id"],
  ["obsergent.caller.scopes", "Caller scopes"], ["http.response.status_code", "HTTP status"],
  ["gateway.decision", "Gateway decision"], ["gateway.activity_id", "Gateway activity id"], ["mcp.session.hash", "MCP session"],
];

export function SpanInspector({ span, allSpans, runStart }: { span: Span; allSpans: Span[]; runStart: number }) {
  const { detailed } = useSettings();
  const [tab, setTab] = useState<Tab>("overview");
  const layer = layerOf(span);
  const attrs = span.attributes;
  const tree = useMemo(() => buildTree(allSpans), [allSpans]);
  const node = findNode(tree, span.span_id);
  const phases = node ? phasesBelow(node) : {};
  const hasGateway = attrs["obsergent.layer"] === "gateway" || attrs["gateway.decision"] !== undefined;
  const reproduction = reproduceCall(span);

  // Arguments / result live under different names depending on who recorded the span.
  const args = attrs["mcp.tool.arguments"] ?? attrs["input.value"];
  const result = attrs["mcp.result"] ?? attrs["mcp.tools"] ?? attrs["output.value"];

  const tabs: { id: Tab; label: string }[] = [{ id: "overview", label: "Summary" }, { id: "arguments", label: "Input" }, { id: "result", label: "Output" },
    ...(hasGateway ? [{ id: "gateway" as Tab, label: "Gateway" }] : []), ...(detailed ? [{ id: "raw" as Tab, label: "Raw" }] : [])];
  const active = tabs.some((t) => t.id === tab) ? tab : "overview";

  return (
    <Card title={<span className="row" style={{ gap: 8 }}><LayerBadge layer={layer} /> <span className="truncate" title={span.name}>{span.name}</span></span>}>
      <Tabs tabs={tabs} value={active} onChange={setTab} />
      {active === "overview" && (
        <div className="col">
          <dl className="kv">
            <dt>Took</dt><dd>{formatMs(span.duration_ms)}</dd>
            <dt>Started</dt><dd>{formatTime(span.start_ns)} <span className="muted">(+{formatMs((span.start_ns - runStart) / 1e6)})</span></dd>
            {detailed && <><dt>Program</dt><dd>{span.service}</dd></>}
            <dt>Result</dt><dd>{span.status_code === "ERROR" ? <span className="badge error">problem</span> : span.status_code === "OK" ? "worked" : "no problem reported"}{span.status_message && <span className="muted"> {span.status_message}</span>}</dd>
            {SHOWN_IN_OVERVIEW.filter(([key]) => attrs[key] !== undefined).map(([key, label]) => (
              <><dt key={`${key}-k`}>{label}</dt><dd key={`${key}-v`}>{key === "gateway.decision" ? <DecisionBadge decision={String(attrs[key])} /> : String(attrs[key])}</dd></>
            ))}
            {detailed && <><dt>Step id</dt><dd className="mono">{span.span_id}</dd></>}
          </dl>
          {reproduction && detailed && (
            <div className="row wrap">
              <CopyButton text={reproduction.jsonRpc} label="Copy as JSON-RPC" />
              <CopyButton text={reproduction.curl} label="Copy as curl" />
            </div>
          )}
        </div>
      )}
      {active === "arguments" && <JsonView value={args} empty="No input was recorded for this span." />}
      {active === "result" && <JsonView value={result} empty="No output was recorded for this span." />}
      {active === "gateway" && (
        <div className="col">
          <dl className="kv">
            <dt>Gateway result</dt><dd><DecisionBadge decision={String(attrs["gateway.decision"] ?? "")} /></dd>
            <dt>Web status</dt><dd>{String(attrs["http.response.status_code"] ?? attrs["gateway.status"] ?? "-")}</dd>
            <dt>API</dt><dd>{String(attrs["gateway.api"] ?? "-")}</dd>
            {detailed && <><dt>Gateway call id</dt><dd className="mono">{String(attrs["gateway.activity_id"] ?? "-")}</dd></>}
          </dl>
          {Object.keys(phases).length > 0 && (
            <div className="col" style={{ gap: 6 }}>
              <h3>Where the gateway spent its time</h3>
              <StackBar parts={phases} />
              <table><tbody>{Object.entries(phases).map(([name, ms]) => <tr key={name}><td>{name.replaceAll("_", " ")}</td><td className="num">{formatMs(ms)}</td></tr>)}</tbody></table>
            </div>
          )}
          <Link to="/gateway">Open the Gateway guard page →</Link>
        </div>
      )}
      {active === "raw" && detailed && (
        <div className="col">
          <div><CopyButton text={JSON.stringify(span, null, 2)} label="Copy span JSON" /></div>
          <JsonView value={{ attributes: attrs, events: span.events, parent: span.parent_span_id, trace: span.trace_id }} />
        </div>
      )}
    </Card>
  );
}
