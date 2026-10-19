// One name per model: `gpt-4o-mini` and `gpt-4o-mini-2024-07-18` are the same model. The same rules as
// src/obsergent/analysis/modelnames.py; both are tested with tests/fixtures/model_names.json so they cannot drift apart.

/** The model's name without provider path, release date or ':latest', in lower case ("" and null become "unknown model"). */
export function displayModel(name: string | null | undefined): string {
  // The last part of a path: "openrouter/openai/gpt-4o-mini" -> "gpt-4o-mini".
  const last = (name ?? "").split("/").pop()?.trim().toLowerCase() ?? "";
  // "llama3.2:latest" -> "llama3.2"; "gpt-4o-mini-2024-07-18" and "claude-3-5-sonnet-20241022" lose their date.
  const cleaned = last.replace(/:latest$/, "").replace(/-(20\d{2}-\d{2}-\d{2}|20\d{6})$/, "");
  return cleaned || "unknown model";
}

/** Tokens-per-dollar style helper: the price of a million tokens as "$0.15" (dollars, never cents). */
export function perMillion(price: number | null | undefined): string {
  if (price === null || price === undefined) return "-";
  return price >= 1 ? `$${price.toFixed(2)}` : `$${price.toFixed(price < 0.1 ? 3 : 2)}`;
}
