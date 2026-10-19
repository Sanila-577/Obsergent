// "What did this conversation cost?": one segment per model call, as wide as that call's cost. Hover for details, click to jump to the step.
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Generation } from "../api/types";
import { colorFor } from "../lib/colors";
import { formatMoney, formatTime, formatTokens, moneyInWords } from "../lib/format";
import { CallCost, TotalCost, explainCost } from "./Money";
import { Card } from "./ui";

export function CostRibbon({ runId, onPick }: { runId: string; onPick: (spanId: string) => void }) {
  const query = useQuery({ queryKey: ["generations", runId], queryFn: () => api.generations(runId) });
  const data = query.data;
  if (!data || data.generations.length === 0 || data.summary.cost?.enabled === false) return null;
  const total = data.summary.cost;
  const models = [...new Set(data.generations.map((g) => g.model ?? "model"))];
  const paid = data.generations.filter((g) => (g.cost?.usd ?? 0) > 0);
  const sum = paid.reduce((acc, g) => acc + (g.cost?.usd ?? 0), 0);
  const label = (g: Generation, n: number) => `Step ${n}: ${g.model ?? "model"} at ${formatTime(g.start_ns)}\n${g.cost ? explainCost(g.cost) : ""}\n${formatTokens(g.prompt_tokens)} words in, ${formatTokens(g.completion_tokens)} out`;
  return (
    <Card title={<span className="row">What this conversation cost <TotalCost cost={total} /></span>}>
      {sum > 0 ? (
        <>
          <div className="ribbon" role="group" aria-label="Cost of each model call">
            {paid.map((g, index) => (
              <button key={g.span_id} className="ribbon-seg" style={{ flexGrow: g.cost?.usd ?? 0, background: colorFor(models, g.model ?? "model") }}
                title={label(g, data.generations.indexOf(g) + 1)} onClick={() => onPick(g.span_id)} aria-label={`Model call ${index + 1}: ${formatMoney(g.cost?.usd ?? 0)}`}>
                {formatMoney(g.cost?.usd ?? 0)}
              </button>))}
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>{paid.length} model call{paid.length === 1 ? "" : "s"} cost {moneyInWords(sum)} in total. Click a part to jump to that step.</p>
        </>
      ) : (
        <p style={{ margin: 0 }}>{data.generations.map((g) => <CallCost key={g.span_id} cost={g.cost} />).slice(0, 1)} {total && total.local > 0 ? "This conversation ran on your own computer, so it cost nothing." : "No price is known for the model used, so no cost is shown."}</p>
      )}
    </Card>
  );
}
