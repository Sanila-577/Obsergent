// A small amount cell used in lists: "$0.42", "free" for local models, "no price" when none is known.
import { formatMoney } from "../lib/format";

export function Money({ usd, status }: { usd: number | null; status?: string }) {
  if (status === "local") return <span className="money local" title="Runs on your own computer: free.">free</span>;
  if (status === "unpriced") return <span className="money unpriced" title="No price is known for this model.">no price</span>;
  return <span className="money">{formatMoney(usd)}</span>;
}
