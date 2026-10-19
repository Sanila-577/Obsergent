// Pretty JSON with the parts Obsergent hid (***) highlighted and explained.
import { Fragment, type ReactNode } from "react";
import { prettyJson } from "../lib/format";

const TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|(\*\*\*)|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

/** Turn JSON text into coloured spans. Secrets that the proxy replaced with *** get their own style. */
export function highlight(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(TOKEN)) {
    const start = match.index ?? 0;
    if (start > last) parts.push(text.slice(last, start));
    const [whole, string, colon] = match;
    if (string && colon) {
      parts.push(<span key={index} className="json-key">{string}</span>, colon);
    } else if (string) {
      // a string value; if it contains ***, mark just that part
      const pieces = string.split("***");
      parts.push(
        <span key={index} className="json-str">
          {pieces.map((piece, i) => (
            <Fragment key={i}>
              {i > 0 && <span className="redacted" title="Hidden by Obsergent: this looked like a secret">***</span>}
              {piece}
            </Fragment>
          ))}
        </span>,
      );
    } else if (match[3]) {
      parts.push(<span key={index} className="redacted" title="Hidden by Obsergent: this looked like a secret">***</span>);
    } else {
      parts.push(<span key={index} className="json-num">{whole}</span>);
    }
    last = start + whole.length;
    index += 1;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function JsonView({ value, empty = "(nothing recorded)" }: { value: unknown; empty?: string }) {
  if (value === undefined || value === null || value === "") return <span className="muted">{empty}</span>;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const { pretty, isJson } = prettyJson(text);
  return <pre className="code mono">{isJson ? highlight(pretty) : pretty}</pre>;
}
