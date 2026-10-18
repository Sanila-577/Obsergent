// ⌘K / Ctrl+K: jump to any page, recent run, tool or server by typing a few letters.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { shortId, formatMs } from "../lib/format";
import { useSettings } from "../lib/state";

interface Item {
  group: string;
  label: string;
  hint?: string;
  to: string;
}

export const PAGES: Item[] = [
  { group: "Pages", label: "Overview", to: "/", hint: "g o" },
  { group: "Pages", label: "Runs", to: "/runs", hint: "g r" },
  { group: "Pages", label: "Sessions", to: "/sessions", hint: "g s" },
  { group: "Pages", label: "Servers & tools", to: "/servers", hint: "g t" },
  { group: "Pages", label: "Findings", to: "/findings", hint: "g f" },
  { group: "Pages", label: "Gateway (WSO2)", to: "/gateway", hint: "g w" },
  { group: "Pages", label: "Map", to: "/map", hint: "g m" },
  { group: "Pages", label: "Compare runs", to: "/compare" },
  { group: "Pages", label: "About: AgentTrace vs Langfuse", to: "/about" },
];

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const { hours } = useSettings();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const runs = useQuery({ queryKey: ["palette-runs"], queryFn: () => api.traces({ limit: 15 }) });
  const tools = useQuery({ queryKey: ["tools", hours], queryFn: () => api.tools(hours) });
  const servers = useQuery({ queryKey: ["servers"], queryFn: api.servers });

  useEffect(() => input.current?.focus(), []);

  const items = useMemo<Item[]>(() => {
    const all: Item[] = [
      ...PAGES,
      ...(runs.data ?? []).map((r) => ({ group: "Recent runs", label: r.root_name, hint: `${shortId(r.trace_id)} · ${formatMs(r.duration_ms)}`, to: `/runs/${r.trace_id}` })),
      ...(tools.data ?? []).map((t) => ({ group: "Tools", label: String(t.tool), hint: t.server ?? "", to: `/runs?tool=${t.tool}` })),
      ...(servers.data ?? []).map((s) => ({ group: "Servers", label: s.server_name, hint: `${s.versions} version(s)`, to: `/servers?server=${s.server_name}` })),
    ];
    const needle = text.trim().toLowerCase();
    return needle ? all.filter((item) => `${item.label} ${item.hint ?? ""} ${item.group}`.toLowerCase().includes(needle)) : all;
  }, [text, runs.data, tools.data, servers.data]);

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
        <input ref={input} value={text} placeholder="Jump to a page, run, tool or server…" onChange={(e) => { setText(e.target.value); setCursor(0); }} aria-label="Search" />
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
