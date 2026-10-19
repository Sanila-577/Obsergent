// Sessions group what one proxy process saw: ideal for external apps (Claude Desktop, Cursor) that send no trace id.
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { JsonView } from "../components/JsonView";
import { FirstRun } from "../components/FirstRun";
import { Help } from "../components/Help";
import { Card, DecisionBadge, EmptyState, PageHead, QueryState } from "../components/ui";
import { formatMs, formatTime, shortId, timeAgo } from "../lib/format";
import { useLiveInterval, useSettings } from "../lib/state";
import { PAGES } from "../lib/words";

export function Sessions() {
  const { detailed } = useSettings();
  const navigate = useNavigate();
  const refetchInterval = useLiveInterval();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions, refetchInterval });
  return (
    <>
      <PageHead title={PAGES.sessions.title} about={PAGES.sessions.about} />
      <Card flush>
        <QueryState query={sessions} empty={{ when: (s) => s.length === 0, title: "No app activity yet",
          hint: <FirstRun kind="sessions" title="No app activity yet" /> }}>
          {(rows) => (
            <table>
              <thead><tr><th>Started<Help topic="session" /></th><th>Tool server</th>{detailed && <th>Command</th>}<th className="num">Requests</th><th className="num">Actions</th><th className="num">Problems</th>{detailed && <th>Session id</th>}</tr></thead>
              <tbody>{rows.map((s) => (
                <tr key={s.session_id} className="click" onClick={() => navigate(`/sessions/${s.session_id}`)}>
                  <td className="nowrap">{formatTime(s.start_ns)}<div className="muted" style={{ fontSize: 12 }}>{timeAgo(s.start_ns)}</div></td>
                  <td><strong>{s.server_name ?? "?"}</strong></td>
                  {detailed && <td className="mono truncate" style={{ maxWidth: 360 }} title={s.command ?? ""}>{s.command ?? "-"}</td>}
                  <td className="num">{s.span_count}</td><td className="num">{s.tool_calls ?? 0}</td>
                  <td className="num">{s.error_count ? <span className="badge error">{s.error_count}</span> : "-"}</td>
                  {detailed && <td className="mono muted">{shortId(s.session_id)}</td>}
                </tr>))}</tbody>
            </table>
          )}
        </QueryState>
      </Card>
    </>
  );
}

export function SessionDetail() {
  const { detailed } = useSettings();
  const { id = "" } = useParams();
  const timeline = useQuery({ queryKey: ["timeline", id], queryFn: () => api.timeline(id), refetchInterval: useLiveInterval() });
  return (
    <>
      <div className="row" style={{ marginBottom: 6 }}><Link to="/sessions"><ArrowLeft size={14} style={{ verticalAlign: "-2px" }} /> App activity</Link></div>
      <PageHead title="What the app did" sub={detailed ? <span className="mono">{shortId(id, 12)}</span> : undefined} about="Every request in the order it happened. Open one to see its details." />
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
                  {event.arguments && event.arguments !== "{}" && <details open><summary className="muted">what it asked for</summary><JsonView value={event.arguments} /></details>}
                  {event.result && <details><summary className="muted">what it got back</summary><JsonView value={event.result} /></details>}
                </div>
              ))}
              <EmptyState title="That is everything this app did" />
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
