// "Prices checked 2 hours ago" with a Check now button, plus (in Detailed mode) which lists were read and where they disagree.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { formatMoney, timeAgo } from "../lib/format";

const SOURCE_NAMES: Record<string, string> = { models_dev: "models.dev", openrouter: "OpenRouter", huggingface: "Hugging Face", litellm: "LiteLLM" };

export function PriceBadge({ detailed }: { detailed: boolean }) {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["prices"], queryFn: api.prices, refetchInterval: 60_000 });
  const refresh = useMutation({ mutationFn: api.refreshPrices, onSuccess: () => client.invalidateQueries() });
  const data = status.data;
  if (!data) return null;
  const errors = data.sources.filter((source) => source.error);
  const changes = data.changes ?? [];
  return (
    <div className="price-badge">
      <div className="row wrap" style={{ gap: 8 }}>
        <span className="muted">
          {!data.enabled ? "Cost calculation is switched off in config.yaml."
            : data.last_checked_ns ? `Prices checked ${timeAgo(data.last_checked_ns)}.` : "Prices have not been downloaded yet."}
        </span>
        {data.enabled && (
          <button className="small ghost" onClick={() => refresh.mutate()} disabled={refresh.isPending} aria-label="Check prices now">
            <RefreshCw size={13} /> {refresh.isPending ? "Checking…" : "Check now"}
          </button>
        )}
        {errors.length > 0 && <span className="badge medium" title={errors.map((e) => `${e.source}: ${e.error}`).join("\n")}>some price lists could not be reached</span>}
      </div>
      {changes.length > 0 && (
        <div className="notice" role="note" style={{ marginTop: 8 }}>
          <strong>Prices changed recently:</strong>{" "}
          {changes.slice(0, 3).map((c) => `${c.model}: ${formatMoney(c.old_input)} → ${formatMoney(c.new_input)} in, ${formatMoney(c.old_output)} → ${formatMoney(c.new_output)} out (per million words, ${timeAgo(c.effective_from_ns)})`).join("; ")}.
          Calls made before a change keep the price that was valid then.
        </div>
      )}
      {detailed && data.enabled && (
        <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
          Lists: {data.sources.map((s) => `${SOURCE_NAMES[s.source] ?? s.source} (${s.models.toLocaleString()} models, checked ${timeAgo(s.checked_ns)}, every ${data.refresh_minutes[s.source] ?? "?"} min)`).join("; ") || "none yet"}.
          {data.disagreements.length > 0 && ` ${data.disagreements.length} model(s) have different prices in different lists: ${data.disagreements.slice(0, 5).map((d) => d.model).join(", ")}…`}
        </div>
      )}
    </div>
  );
}
