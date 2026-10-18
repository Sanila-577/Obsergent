// A run as a chat. The part Langfuse can't show: each tool call the model asked for is linked to the real MCP call
// (and what the gateway decided about it).
import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { Message, ToolLink } from "../api/types";
import { JsonView } from "./JsonView";
import { DecisionBadge } from "./ui";

function LinkLine({ link, runId }: { link: ToolLink | null; runId: string }) {
  if (!link) return <span className="muted">no matching MCP call was recorded</span>;
  if (!link.mcp_span_id) return <span className="muted">the agent ran this tool, but no MCP call was recorded for it</span>;
  return (
    <span className="row wrap" style={{ gap: 8 }}>
      <Link to={`/runs/${runId}?tab=timeline&span=${link.mcp_span_id}`}><ArrowUpRight size={13} style={{ verticalAlign: "-2px" }} /> View the MCP call</Link>
      {link.mcp_status === "ERROR" && <span className="badge error">failed</span>}
      {link.gateway_decision && <DecisionBadge decision={link.gateway_decision} />}
    </span>
  );
}

export function ConversationView({ messages, runId }: { messages: Message[]; runId: string }) {
  return (
    <div className="chat">
      {messages.map((message, index) => (
        <div key={index} className={`msg ${message.role}`}>
          <div className="role">{message.role}{message.name && <span className="badge outline">{message.name}</span>}</div>
          {message.role === "tool"
            ? <><JsonView value={message.content} empty="(empty result)" /><div style={{ marginTop: 6 }}><LinkLine link={message.link} runId={runId} /></div></>
            : message.content && <div style={{ whiteSpace: "pre-wrap" }}>{message.content}</div>}
          {message.tool_calls.map((call) => (
            <div key={call.id} className="toolcall">
              <div className="row spread"><strong>🔧 {call.name}</strong><LinkLine link={call.link} runId={runId} /></div>
              <JsonView value={call.arguments} empty="(no arguments)" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
