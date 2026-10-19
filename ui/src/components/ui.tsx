// Small reusable pieces. Pages are built from these so the whole app looks and behaves the same.
import { Check, Copy } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Decision, Severity } from "../api/types";
import { ApiError } from "../api/client";
import { LAYER_LABEL, type Layer } from "../lib/trace";
import { splitList } from "../lib/format";
import { DECISION_WORDS } from "../lib/words";

export function PageHead({ title, sub, about, children }: { title: string; sub?: ReactNode; about?: string; children?: ReactNode }) {
  return (
    <>
      <div className="page-head">
        <h1>{title}</h1>
        {sub && <span className="sub">{sub}</span>}
        <div className="grow" />
        {children}
      </div>
      {about && <p className="page-about">{about}</p>}
    </>
  );
}

export function Card({ title, actions, flush, children }: { title?: ReactNode; actions?: ReactNode; flush?: boolean; children: ReactNode }) {
  return (
    <section className={`card${flush ? " flush" : ""}`}>
      {(title || actions) && (
        <div className="card-head" style={flush ? { padding: "14px 16px 0" } : undefined}>
          {title && <h2 style={{ margin: 0 }}>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Tile({ label, value, hint, tone, to }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "bad" | "warn"; to?: string }) {
  const body = (
    <>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </>
  );
  return to ? (
    <Link className={`tile ${tone ?? ""}`} to={to}>{body}</Link>
  ) : (
    <div className={`tile ${tone ?? ""}`}>{body}</div>
  );
}

export function LayerBadge({ layer }: { layer: Layer }) {
  return <span className={`badge ${layer}`}>{LAYER_LABEL[layer]}</span>;
}

const DECISION_HELP: Record<string, string> = {
  allowed: "The gateway let the call through",
  unauthorized: "Missing or invalid token (HTTP 401)",
  forbidden: "Valid token, but not allowed to do this, e.g. the tool's scope is missing (HTTP 403)",
  throttled: "A rate limit was hit (HTTP 429)",
  denied: "An access-control policy blocked this tool",
  error: "Something else went wrong",
};

export function DecisionBadge({ decision }: { decision: Decision | string | null | undefined }) {
  if (!decision) return <span className="muted">-</span>;
  return <span className={`badge ${decision}`} title={DECISION_HELP[decision] ?? decision}>{DECISION_WORDS[decision] ?? decision}</span>;
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`badge ${severity}`}>{severity}</span>;
}

/** "a,b" from the API -> a row of small badges. */
export function ListBadges({ value, kind = "outline" }: { value: string | null | undefined; kind?: string }) {
  const items = splitList(value);
  if (!items.length) return <span className="muted">-</span>;
  return <span className="row wrap" style={{ gap: 4 }}>{items.map((item) => <span key={item} className={`badge ${kind}`}>{item}</span>)}</span>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof ApiError ? `${error.status}: ${error.message}` : error instanceof Error ? error.message : String(error);
  return <div className="error-box" role="alert"><strong>Could not load this.</strong> {message}<div className="muted">Is Obsergent running? Start it with <code>make up</code>.</div></div>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return <div className="col" aria-busy="true" aria-label="Loading">{Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />)}</div>;
}

/** Shows a skeleton while loading, an error box on failure, an empty state for empty data, otherwise the children. */
export function QueryState<T>({ query, empty, children }: {
  query: { data: T | undefined; error: unknown; isPending: boolean };
  empty?: { when: (data: T) => boolean; title: string; hint?: ReactNode };
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <Skeleton />;
  if (query.error) return <ErrorBox error={query.error} />;
  if (query.data === undefined) return null;
  if (empty?.when(query.data)) return <EmptyState title={empty.title}>{empty.hint}</EmptyState>;
  return <>{children(query.data)}</>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button key={tab.id} role="tab" aria-selected={tab.id === value} className={`tab${tab.id === value ? " on" : ""}`} onClick={() => onChange(tab.id)}>
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string | number>({ options, value, onChange }: { options: { id: T; label: string }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="seg" role="group">
      {options.map((option) => (
        <button key={String(option.id)} className={option.id === value ? "on" : ""} aria-pressed={option.id === value} onClick={() => onChange(option.id)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked (non-secure context): nothing to do */
    }
  };
  return <button className="small ghost" onClick={copy} aria-label={label}>{copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : label}</button>;
}

/** A stacked horizontal bar: one coloured segment per phase, width proportional to its time. */
export function StackBar({ parts }: { parts: Record<string, number> }) {
  const entries = Object.entries(parts).filter(([, ms]) => ms > 0);
  const total = entries.reduce((sum, [, ms]) => sum + ms, 0);
  if (!total) return <span className="muted">-</span>;
  return (
    <div className="stack-bar" title={entries.map(([name, ms]) => `${name}: ${ms.toFixed(2)} ms`).join("\n")}>
      {entries.map(([name, ms], index) => <span key={name} className={`phase-${index % 8}`} style={{ width: `${(ms / total) * 100}%` }} />)}
    </div>
  );
}
