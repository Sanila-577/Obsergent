// Sessions group what one proxy process saw: ideal for external apps (Claude Desktop, Cursor) that send no trace id.
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { JsonView } from "../components/JsonView";
import { Card, DecisionBadge, EmptyState, PageHead, QueryState } from "../components/ui";
import { formatMs, formatTime, shortId, timeAgo } from "../lib/format";
import { useLiveInterval } from "../lib/state";

export function Sessions() {
  const navigate = useNavigate();
  const refetchInterval = useLiveInterval();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions, refetchInterval });
  return (
    <>
      <PageHead title="Sessions" sub="one per proxy process: everything an app did with one MCP server" />
      <Card flush>
        <QueryState query={sessions} empty={{ when: (s) => s.length === 0, title: "No sessions yet",
          hint: <p>Point Claude Desktop or Cursor at <code>agenttrace proxy</code> (see docs/closed-apps.md) and its calls are grouped here.</p> }}>
          {(rows) => (
            <table>
              <thead><tr><th>Started</th><th>MCP server</th><th>Command</th><th className="num">Requests</th><th className="num">Tool calls</th><th className="num">Errors</th><th>Session</th></tr></thead>
              <tbody>{rows.map((s) => (
                <tr key={s.session_id} className="click" onClick={() => navigate(`/sessions/${s.session_id}`)}>
                  <td className="nowrap">{formatTime(s.start_ns)}<div className="muted" style={{ fontSize: 12 }}>{timeAgo(s.start_ns)}</div></td>
                  <td><strong>{s.server_name ?? "?"}</strong></td>
                  <td className="mono truncate" style={{ maxWidth: 360 }} title={s.command ?? ""}>{s.command ?? "-"}</td>
                  <td className="num">{s.span_count}</td><td className="num">{s.tool_calls ?? 0}</td>
                  <td className="num">{s.error_count ? <span className="badge error">{s.error_count}</span> : "-"}</td>
                  <td className="mono muted">{shortId(s.session_id)}</td>
                </tr>))}</tbody>
            </table>
          )}
        </QueryState>
      </Card>
    </>
  );
}

export function SessionDetail() {
  const { id = "" } = useParams();
  const timeline = useQuery({ queryKey: ["timeline", id], queryFn: () => api.timeline(id), refetchInterval: useLiveInterval() });
  return (
    <>
      <div className="row" style={{ marginBottom: 6 }}><Link to="/sessions"><ArrowLeft size={14} style={{ verticalAlign: "-2px" }} /> Sessions</Link></div>
      <PageHead title="Session timeline" sub={<span className="mono">{shortId(id, 12)}</span>} />
      <QueryState query={timeline} empty={{ when: (t) => t.events.length === 0, title: "Nothing recorded in this session" }}>
        {({ events }) => {
          const start = events[0].start_ns;
          return (
            <div className="chat" style={{ maxWidth: 940 }}>
              {events.map((event) => (
                <div key={event.span_id} className={`msg ${event.method === "tools/call" ? "tool" : "system"}`}>
                  <div className="role">
                    <span>+{formatMs((event.start_ns - start) / 1e6)}</span><span className="badge proxy">{event.method}</span>
                    {event.tool && <strong style={{ color: "var(--text)" }}>{event.tool}</strong>}
                    <span className="grow" />
                    {event.decision && <DecisionBadge decision={event.decision} />}
                    {event.status === "ERROR" && <span className="badge error">failed</span>}
                    <span>{formatMs(event.duration_ms)}</span>
                    <Link to={`/runs/${event.trace_id}?span=${event.span_id}`}>open</Link>
                  </div>
                  {event.status === "ERROR" && event.message && <div className="muted" style={{ marginBottom: 4 }}>{event.message}</div>}
                  {event.arguments && event.arguments !== "{}" && <details open><summary className="muted">arguments</summary><JsonView value={event.arguments} /></details>}
                  {event.result && <details><summary className="muted">result</summary><JsonView value={event.result} /></details>}
                </div>
              ))}
              <EmptyState title="End of session" />
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
