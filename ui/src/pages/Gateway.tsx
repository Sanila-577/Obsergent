// The WSO2 API Platform MCP gateway, seen from AgentTrace: what it decided, where the time went, who is calling,
// and a suggested access-control policy based on what was really used.
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ShieldCheck } from "lucide-react";
import { Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { GatewayCall } from "../api/types";
import { JsonView } from "../components/JsonView";
import { Card, CopyButton, DecisionBadge, EmptyState, PageHead, QueryState, StackBar, Tile } from "../components/ui";
import { formatMs, formatTime, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";

const DECISION_ORDER = ["allowed", "unauthorized", "forbidden", "throttled", "denied", "error"];

const SETUP_SNIPPET = `# 1. AgentTrace: accept the gateway's OpenTelemetry (gRPC) and the proxy's spans
agenttrace up --grpc

# 2. WSO2 API Platform gateway: gateway/configs/config.toml, then docker compose restart
[tracing]
enabled = true
endpoint = "host.docker.internal:4317"
insecure = true

# 3. Put AgentTrace's HTTP proxy in front of the gateway's MCP endpoint
agenttrace proxy-http --name wso2 --url http://localhost:8080/<context>/mcp`;

function CallDetail({ call }: { call: GatewayCall }) {
  const detail = useQuery({ queryKey: ["gateway-call", call.activity_id], queryFn: () => api.gatewayCall(call.activity_id) });
  return (
    <QueryState query={detail}>{(d) => (
      <div className="col">
        <dl className="kv"><dt>Activity id</dt><dd className="mono">{call.activity_id}</dd><dt>Consumer key</dt><dd className="mono">{call.consumer_key ?? "-"}</dd>
          <dt>Correlated by</dt><dd>{call.correlation === "trace" ? "the shared trace (the gateway continued our trace id)" : call.correlation === "activity" ? "the gateway's activity id" : "nothing: this call did not go through AgentTrace's proxy"}</dd></dl>
        <table><thead><tr><th>Gateway span</th><th className="num">Duration</th></tr></thead>
          <tbody>{d.spans.map((s) => <tr key={s.span_id}><td>{s.name}</td><td className="num">{formatMs(s.duration_ms)}</td></tr>)}</tbody></table>
      </div>)}
    </QueryState>
  );
}

function PolicyAssistant() {
  const [params, setParams] = useSearchParams();
  const servers = useQuery({ queryKey: ["servers"], queryFn: api.servers });
  const names = (servers.data ?? []).map((s) => s.server_name);
  const server = params.get("server") ?? names[0] ?? "";
  const suggestion = useQuery({ queryKey: ["policy", server], queryFn: () => api.policy(server), enabled: !!server, retry: false });
  return (
    <Card title={<span className="row"><ShieldCheck size={17} /> Access-control assistant</span>} actions={
      <select value={server} onChange={(e) => setParams({ server: e.target.value })} aria-label="Server">{names.map((n) => <option key={n}>{n}</option>)}</select>}>
      <p className="muted" style={{ marginTop: 0 }}>A suggestion built from what this server offers and what was actually called. With <code>tools.mode = deny</code>, only the tools in <code>exceptions</code> get through the gateway. Review before applying.</p>
      {!server ? <EmptyState title="No MCP server recorded yet" />
        : suggestion.error ? <EmptyState title="No tool list recorded for this server yet">Call <code>tools/list</code> through the proxy once.</EmptyState>
        : <QueryState query={suggestion}>{(s) => (
          <div className="grid two">
            <div className="col">
              <div><h3>Allow ({s.allow.length})</h3>{s.allow.length ? s.allow.map((t) => <div key={t.tool} className="row"><span className="badge ok">allow</span><strong>{t.tool}</strong><span className="muted">{t.calls} calls seen</span></div>) : <span className="muted">nothing used yet</span>}</div>
              <div><h3>Review ({s.review.length})</h3>{s.review.length ? s.review.map((t) => <div key={t.tool} style={{ marginBottom: 6 }}><div className="row"><span className="badge medium">review</span><strong>{t.tool}</strong></div><div className="muted">{t.reason}</div><div className="muted">suggested scope: <code>{s.suggested_scopes[t.tool]}</code></div></div>) : <span className="muted">no risky tools found</span>}</div>
              <div><h3>Never called ({s.unused.length})</h3>{s.unused.length ? <div className="row wrap">{s.unused.map((t) => <span key={t.tool} className="badge outline">{t.tool}</span>)}</div> : <span className="muted">every tool was used</span>}</div>
            </div>
            <div className="col"><div className="row spread"><h3 style={{ margin: 0 }}>Policy parameters</h3><CopyButton text={JSON.stringify(s.policy, null, 2)} label="Copy" /></div><JsonView value={s.policy} />
              <ul className="muted" style={{ margin: 0, paddingLeft: 18 }}>{s.notes.map((n) => <li key={n}>{n}</li>)}</ul></div>
          </div>)}</QueryState>}
    </Card>
  );
}

export function Gateway() {
  const { hours } = useSettings();
  const summary = useQuery({ queryKey: ["gateway", hours], queryFn: () => api.gateway(hours), refetchInterval: useLiveInterval() });
  const [open, setOpen] = useState<string | null>(null);

  return (
    <>
      <PageHead title="Gateway" sub="WSO2 API Platform MCP gateway" />
      <QueryState query={summary}>{(g) => (
        <div className="col" style={{ gap: 16 }}>
          <Card>
            <div className="row wrap spread">
              <div className="row"><span className="dot" style={{ background: g.receiving ? "var(--ok)" : "var(--warn)" }} />
                <strong>{g.receiving ? "Gateway telemetry is arriving" : "No gateway telemetry received yet"}</strong>
                {g.last_seen_ns && <span className="muted">last span {timeAgo(g.last_seen_ns)}</span>}</div>
              <span className="muted">{g.calls_total} gateway call(s) in this window</span>
            </div>
            {!g.receiving && (
              <div className="col" style={{ marginTop: 12 }}>
                <p style={{ margin: 0 }}>AgentTrace can show what the gateway does with each call once the gateway sends its OpenTelemetry traces here and the proxy sits in front of it:</p>
                <pre className="code mono">{SETUP_SNIPPET}</pre><div><CopyButton text={SETUP_SNIPPET} label="Copy steps" /></div>
              </div>)}
          </Card>

          {g.calls_total > 0 && <>
            <div className="grid tiles">
              {DECISION_ORDER.filter((d) => g.decisions[d]).map((d) => <Tile key={d} label={d} value={g.decisions[d]} tone={d === "allowed" ? undefined : d === "error" || d === "forbidden" || d === "denied" ? "bad" : "warn"} to={`/runs?decision=${d}`} />)}
            </div>

            <div className="grid two">
              <Card title="Where the gateway spends its time" flush>
                <table><thead><tr><th>Phase</th><th>Share</th><th className="num">avg</th><th className="num">p95</th></tr></thead>
                  <tbody>{(() => { const entries = Object.entries(g.phases).filter(([, v]) => v.avg_ms !== null); const max = Math.max(...entries.map(([, v]) => v.avg_ms ?? 0), 0.0001);
                    return entries.map(([name, v]) => <tr key={name}><td>{name.replaceAll("_", " ")}</td><td style={{ width: "42%" }}><div className="stack-bar"><span className="phase-0" style={{ width: `${((v.avg_ms ?? 0) / max) * 100}%` }} /></div></td><td className="num">{formatMs(v.avg_ms)}</td><td className="num">{formatMs(v.p95_ms)}</td></tr>); })()}</tbody></table>
              </Card>
              <Card title="Decisions by tool and by caller" flush>
                <table><thead><tr><th>Tool</th><th>Decisions</th></tr></thead><tbody>{Object.entries(g.by_tool).map(([tool, counts]) => <tr key={tool}><td>{tool}</td><td><span className="row wrap" style={{ gap: 6 }}>{Object.entries(counts).map(([d, n]) => <span key={d}><DecisionBadge decision={d} /> {n}</span>)}</span></td></tr>)}</tbody></table>
                <table><thead><tr><th>Caller</th><th>Decisions</th></tr></thead><tbody>{Object.entries(g.by_caller).map(([caller, counts]) => <tr key={caller}><td className="mono truncate" style={{ maxWidth: 200 }}>{caller}</td><td><span className="row wrap" style={{ gap: 6 }}>{Object.entries(counts).map(([d, n]) => <span key={d}><DecisionBadge decision={d} /> {n}</span>)}</span></td></tr>)}</tbody></table>
              </Card>
            </div>

            <Card title="Latest calls through the gateway" flush>
              <table>
                <thead><tr><th style={{ width: 24 }} /><th>When</th><th>Call</th><th>Decision</th><th className="num">HTTP</th><th>Caller</th><th className="num">Agent waited</th><th className="num">Gateway</th><th>Inside the gateway</th><th /></tr></thead>
                <tbody>{g.calls.map((c) => (
                  <Fragment key={c.activity_id}>
                    <tr className="click" onClick={() => setOpen(open === c.activity_id ? null : c.activity_id)}>
                      <td>{open === c.activity_id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                      <td className="nowrap">{formatTime(c.start_ns)}</td>
                      <td>{c.tool ?? <span className="muted">{c.api ?? "call"}</span>}{c.method && c.method !== "tools/call" && <span className="muted"> {c.method}</span>}</td>
                      <td><DecisionBadge decision={c.decision} /></td><td className="num">{c.status ?? "-"}</td>
                      <td className="mono truncate" style={{ maxWidth: 130 }}>{c.caller ?? c.consumer_key ?? "-"}</td>
                      <td className="num">{formatMs(c.proxy_ms)}</td><td className="num">{formatMs(c.gateway_ms)}</td>
                      <td style={{ minWidth: 110 }}><StackBar parts={c.phases} /></td>
                      <td onClick={(e) => e.stopPropagation()}>{c.proxy_span_id ? <Link to={`/runs/${c.trace_id}?span=${c.proxy_span_id}`}>run</Link> : <Link to={`/runs/${c.trace_id}`}>trace</Link>}</td>
                    </tr>
                    {open === c.activity_id && <tr><td /><td colSpan={9}><CallDetail call={c} /></td></tr>}
                  </Fragment>))}</tbody>
              </table>
            </Card>
          </>}

          <PolicyAssistant />
        </div>)}
      </QueryState>
      <p className="muted" style={{ marginTop: 14 }}>Tool-level scopes and rate limits are configured on the MCP proxy in the gateway (policies mcp-acl-list, mcp-authz, mcp-ratelimit). See <Link to="/about">About</Link> and docs/wso2-integration.md.</p>
    </>
  );
}
