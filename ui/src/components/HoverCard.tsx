// A card that appears when the pointer rests on (or the keyboard focuses) a chip: a short summary and a way to open it.
// ModelChip, ToolChip and AgentChip use it, so a model, tool or agent can be looked up wherever its name appears.
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { formatMoney, formatTokens } from "../lib/format";

export function HoverCard({ trigger, children }: { trigger: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="hovercard-wrap" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}>
      {trigger}
      {open && <span className="hovercard" role="tooltip">{children}</span>}
    </span>
  );
}

/** A model's name; resting on it shows its tokens, calls and cost. */
export function ModelChip({ name }: { name: string }) {
  const models = useQuery({ queryKey: ["models"], queryFn: () => api.models(), staleTime: 30_000 });
  const model = models.data?.find((m) => m.model === name);
  return (
    <HoverCard trigger={<Link className="badge model" to={`/models?model=${encodeURIComponent(name)}`}>{name}</Link>}>
      <strong>{model?.display ?? name}</strong>
      {model ? <span>{formatTokens(model.tokens.total)} tokens · {model.calls} calls · {model.status === "local" ? "free" : formatMoney(model.usd)}</span>
        : <span className="muted">loading…</span>}
      <span className="muted">{model?.provider || ""}</span>
    </HoverCard>
  );
}

/** A tool's name; resting on it shows its server, inputs and use. */
export function ToolChip({ name }: { name: string }) {
  const mcps = useQuery({ queryKey: ["mcps"], queryFn: api.mcps, staleTime: 30_000 });
  const server = mcps.data?.find((s) => s.tools.some((t) => t.name === name));
  const tool = server?.tools.find((t) => t.name === name);
  return (
    <HoverCard trigger={<Link className="badge proxy" to={`/mcps?tool=${encodeURIComponent(name)}`}>{name}</Link>}>
      <strong>{name}</strong>
      {tool ? <span>{tool.calls} calls on {server?.name} · needs {tool.parameters.filter((p) => p.required).map((p) => p.name).join(", ") || "nothing"}</span>
        : <span className="muted">no tool list recorded</span>}
      {tool?.description && <span className="muted">{tool.description.slice(0, 90)}</span>}
    </HoverCard>
  );
}

/** An agent's name; resting on it shows its questions and tokens. */
export function AgentChip({ name }: { name: string }) {
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents, staleTime: 30_000 });
  const agent = agents.data?.find((a) => a.name === name);
  return (
    <HoverCard trigger={<Link className="badge agent" to={`/agents?agent=${encodeURIComponent(name)}`}>{name}</Link>}>
      <strong>{name}</strong>
      {agent ? <span>{agent.questions} questions · {formatTokens(agent.tokens.total)} tokens · {formatMoney(agent.usd)}</span> : <span className="muted">loading…</span>}
      <span className="muted">{agent?.framework}</span>
    </HoverCard>
  );
}
