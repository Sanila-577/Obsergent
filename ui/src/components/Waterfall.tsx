// A run drawn as a timeline: one row per span, indented by parent, coloured by layer.
// Icons.
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
// React hooks: effects, cached calculations, element references, state.
import { useEffect, useMemo, useRef, useState } from "react";
// Types only.
import type { Smell, Span } from "../api/types";
// Duration formatter.
import { formatMs } from "../lib/format";
// Tree/row helpers from lib/trace.ts.
import { LAYER_LABEL, buildTree, flatten, layerOf, smellIndex, type Layer } from "../lib/trace";

// What the parent passes in.
interface Props {
  spans: Span[];
  smells: Smell[];
  selectedId: string | null;
  onSelect: (spanId: string) => void;
}

// Legend order.
const LAYERS: Layer[] = ["agent", "model", "proxy", "gateway", "server"];

// The timeline component.
export function Waterfall({ spans, smells, selectedId, onSelect }: Props) {
  // Span ids whose children are hidden.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  // The search text.
  const [query, setQuery] = useState("");
  // Handle on the search box (so "/" can focus it).
  const search = useRef<HTMLInputElement>(null);
  // Build the tree only when the spans change.
  const tree = useMemo(() => buildTree(spans), [spans]);
  // span id -> findings, for the warning icon.
  const flagged = useMemo(() => smellIndex(smells), [smells]);
  // Lower-cased search text.
  const needle = query.trim().toLowerCase();
  // The visible rows (after collapse + search).
  const rows = useMemo(
    () => flatten(tree, collapsed, needle ? (span) => `${span.name} ${span.service} ${JSON.stringify(span.attributes)}`.toLowerCase().includes(needle) : undefined),
    [tree, collapsed, needle],
  );
  // Layers that occur in this run (for the legend).
  const present = new Set(spans.map(layerOf));

  // j / k move through the rows, "/" jumps to the search box (like the shortcuts in many dev tools)
  // { => Keyboard shortcuts: j/k move, / searches.
  useEffect(() => {
    // Runs on every key press.
    const onKey = (event: KeyboardEvent) => {
      // Where the key was pressed.
      const target = event.target as HTMLElement;
      // Ignore while typing in a field.
      if (["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName) || event.metaKey || event.ctrlKey) return;
      // Focus the search box.
      if (event.key === "/") { event.preventDefault(); search.current?.focus(); return; }
      // Other keys: ignore.
      if (event.key !== "j" && event.key !== "k") return;
      // Index of the selected row.
      const position = rows.findIndex((row) => row.node.span.span_id === selectedId);
      // The row above or below, kept inside the list.
      const next = rows[Math.min(rows.length - 1, Math.max(0, position + (event.key === "j" ? 1 : -1)))];
      // Select it.
      if (next) onSelect(next.node.span.span_id);
    };
    // Start listening.
    window.addEventListener("keydown", onKey);
    // window.removeEventListener => Stop listening on cleanup.
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, selectedId, onSelect]);

  // Collapse or expand one node.
  const toggle = (id: string) => setCollapsed((now) => {
    // Copy the set (React needs a new object to notice a change).
    const next = new Set(now);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  // Ids of spans that have children (for "Collapse all").
  const allIds = spans.filter((s) => spans.some((c) => c.parent_span_id === s.span_id)).map((s) => s.span_id);

  return (
    <div>
      <div className="wf-toolbar">
        <input ref={search} type="search" placeholder="Search in this run…  ( / )" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search in this run" style={{ minWidth: 200 }} />
        <button className="small" onClick={() => setCollapsed(new Set(allIds))}>Collapse all</button>
        <button className="small" onClick={() => setCollapsed(new Set())}>Expand all</button>
        <div className="grow" />
        <div className="legend">
          {LAYERS.filter((layer) => present.has(layer)).map((layer) => <span key={layer}><i className="dot" style={{ background: `var(--${layer})` }} />{LAYER_LABEL[layer]}</span>)}
          <span><i className="dot" style={{ background: "transparent", boxShadow: "0 0 0 1.5px var(--text)" }} />slowest path</span>
        </div>
      </div>
      <div role="tree" aria-label="Spans of this run">
        {rows.map(({ node, left, width }) => {
          const { span } = node;
          const layer = layerOf(span);
          const issues = flagged.get(span.span_id);
          const hasChildren = node.children.length > 0;
          return (
            <div key={span.span_id} role="treeitem" aria-selected={span.span_id === selectedId} data-span={span.span_id}
              className={`wf-row${span.span_id === selectedId ? " selected" : ""}`} onClick={() => onSelect(span.span_id)}>
              <div className="wf-name" style={{ paddingLeft: 8 + node.depth * 14 }}>
                {hasChildren
                  ? <button className="twisty" aria-label={collapsed.has(span.span_id) ? "Expand" : "Collapse"} onClick={(e) => { e.stopPropagation(); toggle(span.span_id); }}>{collapsed.has(span.span_id) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}</button>
                  : <span className="twisty" />}
                <i className="dot" style={{ background: `var(--${layer})` }} />
                <span className="label" title={span.name}>{span.name}</span>
                {issues && <span title={issues.map((i) => i.message).join("\n")} style={{ color: "var(--warn)", display: "inline-flex" }}><AlertTriangle size={13} /></span>}
              </div>
              <div className="wf-track">
                <div className={`wf-bar${node.critical ? " critical" : ""}${span.status_code === "ERROR" ? " err" : ""}`}
                  style={{ left: `${left * 100}%`, width: `${Math.min(width, 1 - left) * 100}%`, background: span.status_code === "ERROR" ? "var(--bad)" : `var(--${layer})` }}
                  title={`${span.name}\n${formatMs(span.duration_ms)}${span.status_message ? `\n${span.status_message}` : ""}`} />
              </div>
              <div className="wf-dur">{formatMs(span.duration_ms)}</div>
            </div>
          );
        })}
        {rows.length === 0 && <div className="empty">No span matches “{query}”.</div>}
      </div>
    </div>
  );
}
