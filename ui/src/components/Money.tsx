// A dollar amount for a run or a model call, with a plain-words tooltip about how sure we are.
import type { CostInfo, CostTotals } from "../api/types";
import { formatMoney } from "../lib/format";

const CONFIDENCE_TEXT: Record<string, string> = {
  confirmed: "price confirmed by more than one price list",
  one_source: "price from one list only",
  disagree: "the price lists disagree a little, so this is an approximation",
  exact: "reported by the provider itself",
  set_by_you: "uses a price you set",
};

/** The mark shown next to an amount: ✓ confirmed, ≈ lists disagree, nothing otherwise. */
export function confidenceMark(confidence: string | undefined): string {
  return confidence === "confirmed" || confidence === "exact" ? "✓" : confidence === "disagree" ? "≈" : "";
}

/** Plain-words explanation of one call's cost, for tooltips. */
export function explainCost(cost: CostInfo): string {
  if (cost.status === "local") return "This model runs on your own computer, so each call is free (electricity not counted).";
  if (cost.status === "unpriced") return `${cost.note || "No price is known for this model."} It is left out of the totals.`;
  if (cost.confidence === "exact") return `Exact: ${cost.note || "the provider reported this charge with the response."}`;
  const parts = [`Estimated from the price of ${cost.model} (${cost.source.replace("_", ".")}): ${CONFIDENCE_TEXT[cost.confidence] ?? "price found"}.`];
  const lines = (cost.breakdown ?? []).map((part) => `${part.label} ${formatMoney(part.usd)}`);
  if (lines.length) parts.push(`${lines.join(", ")}.`);
  if (cost.note) parts.push(`${cost.note}.`);
  if (cost.range_usd) parts.push(`Lists give ${formatMoney(cost.range_usd[0])} to ${formatMoney(cost.range_usd[1])} per million words.`);
  return parts.join(" ");
}

/** The cost of one model call. */
export function CallCost({ cost }: { cost: CostInfo | null | undefined }) {
  if (!cost) return <span className="muted">-</span>;
  if (cost.status === "local") return <span className="money local" title={explainCost(cost)}>free</span>;
  if (cost.status === "unpriced") return <span className="money unpriced" title={explainCost(cost)}>no price</span>;
  return (
    <span className="money" title={explainCost(cost)}>
      {formatMoney(cost.usd)}<span className={`conf ${cost.confidence}`}>{confidenceMark(cost.confidence)}</span>{cost.confidence === "exact" && <span className="exact-tag">exact</span>}
    </span>
  );
}

/** The cost of a whole run (or window): the total, and a note when some calls could not be priced. */
export function TotalCost({ cost }: { cost: CostTotals | undefined }) {
  if (!cost || cost.enabled === false || cost.calls === 0) return <span className="muted">-</span>;
  if (cost.priced === 0 && cost.local > 0 && cost.unpriced === 0) return <span className="money local" title="Runs on your own computer: free.">free</span>;
  if (cost.priced === 0) return <span className="money unpriced" title="No price is known for the models used.">no price</span>;
  const exact = cost.exact ?? 0;
  const note = cost.unpriced ? `${cost.unpriced} call(s) without a known price are not included.`
    : exact === cost.priced ? "Reported by the provider itself: exact."
    : exact > 0 ? `${exact} call(s) reported by the provider, the rest estimated from prices.`
    : "An estimate from the recorded words and the current price lists.";
  return <span className="money" title={note}>{formatMoney(cost.usd)}{cost.unpriced ? <span className="conf disagree">+</span> : null}</span>;
}
