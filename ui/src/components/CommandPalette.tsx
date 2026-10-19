// ⌘K / Ctrl+K: jump to any page, recent run, tool or server by typing a few letters.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { shortId, formatMs } from "../lib/format";

interface Item {
  group: string;
  label: string;
  hint?: string;
  to: string;
}

export const PAGES: Item[] = [
  { group: "Pages", label: "Overview", to: "/", hint: "g o" },
  { group: "Pages", label: "Conversations: the questions you asked", to: "/conversations", hint: "g c" },
  { group: "Pages", label: "Agents", to: "/agents", hint: "g a" },
  { group: "Pages", label: "MCPs: tool servers and their tools", to: "/mcps", hint: "g m" },
  { group: "Pages", label: "Models: the AI models used", to: "/models", hint: "g d" },
  { group: "Pages", label: "Spending: what the models cost", to: "/spending", hint: "g s" },
  { group: "Pages", label: "Things to check", to: "/findings", hint: "g f" },
  { group: "Pages", label: "Gateway guard", to: "/gateway", hint: "g w" },
  { group: "Pages", label: "Connections", to: "/map", hint: "g n" },
  { group: "Pages", label: "App activity", to: "/sessions" },
  { group: "Pages", label: "All activity", to: "/runs", hint: "g r" },
  { group: "Pages", label: "Compare two conversations", to: "/compare" },
  { group: "Pages", label: "About Obsergent", to: "/about" },
];

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const questions = useQuery({ queryKey: ["palette-questions"], queryFn: () => api.queries({ limit: 15 }) });
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const mcps = useQuery({ queryKey: ["mcps"], queryFn: api.mcps });

  useEffect(() => input.current?.focus(), []);

  const items = useMemo<Item[]>(() => {
    const all: Item[] = [
      ...PAGES,
      ...(questions.data ?? []).map((q) => ({ group: "Questions", label: q.question || q.root_name, hint: `${shortId(q.trace_id)} · ${formatMs(q.duration_ms)}`, to: `/conversations?q=${q.trace_id}` })),
      ...(agents.data ?? []).map((a) => ({ group: "Agents", label: a.name, hint: `${a.questions} question(s)`, to: `/agents?agent=${encodeURIComponent(a.name)}` })),
      ...(models.data ?? []).map((m) => ({ group: "Models", label: m.model, hint: m.provider ?? "", to: `/models?model=${encodeURIComponent(m.model)}` })),
      ...(mcps.data ?? []).map((s) => ({ group: "MCP servers", label: s.name, hint: `${s.tool_count} tool(s)`, to: `/mcps?server=${encodeURIComponent(s.name)}` })),
      ...(mcps.data ?? []).flatMap((s) => s.tools.map((t) => ({ group: "Tools", label: t.name, hint: s.name, to: `/mcps?server=${encodeURIComponent(s.name)}&tool=${encodeURIComponent(t.name)}` }))),
    ];
    const needle = text.trim().toLowerCase();
    return needle ? all.filter((item) => `${item.label} ${item.hint ?? ""} ${item.group}`.toLowerCase().includes(needle)) : all;
  }, [text, questions.data, agents.data, models.data, mcps.data]);

  const go = (item: Item | undefined) => {
    if (!item) return;
    onClose();
    navigate(item.to);
  };

  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") onClose();
    else if (event.key === "ArrowDown") { event.preventDefault(); setCursor((c) => Math.min(c + 1, items.length - 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (event.key === "Enter") go(items[cursor]);
  };

  let lastGroup = "";
  return (
    <div className="palette-overlay" onMouseDown={onClose} role="dialog" aria-label="Command palette">
      <div className="palette" onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <input ref={input} value={text} placeholder="Jump to a page, question, agent, model or tool…" onChange={(e) => { setText(e.target.value); setCursor(0); }} aria-label="Search" />
        <ul role="listbox">
          {items.length === 0 && <li className="muted">Nothing matches “{text}”</li>}
          {items.slice(0, 40).map((item, index) => {
            const header = item.group !== lastGroup ? <div className="group">{item.group}</div> : null;
            lastGroup = item.group;
            return (
              <div key={`${item.group}-${item.to}-${index}`}>
                {header}
                <li className={index === cursor ? "on" : ""} role="option" aria-selected={index === cursor} onMouseEnter={() => setCursor(index)} onClick={() => go(item)}>
                  <span className="grow truncate">{item.label}</span>
                  {item.hint && <span className="muted mono">{item.hint}</span>}
                </li>
              </div>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
