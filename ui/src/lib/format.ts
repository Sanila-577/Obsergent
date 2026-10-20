// Small display helpers shared by every page.

/** 0.4 -> "0.40 ms", 12.34 -> "12.3 ms", 340 -> "340 ms", 1520 -> "1.52 s". */
// Milliseconds in a readable unit.
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "-";
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 100) return `${ms.toFixed(1)} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.floor(ms / 60_000)} m ${Math.round((ms % 60_000) / 1000)} s`;
}

// Big numbers as 12.3k.
export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  return n >= 10_000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString();
}

// 0.05 -> "5.0%".
export function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(fraction > 0 && fraction < 0.001 ? 2 : 1)}%`;
}

// Nanoseconds since 1970 -> JavaScript Date (which uses milliseconds).
const nsToDate = (ns: number) => new Date(ns / 1_000_000);

/** "14:05:09" for today, "17 Oct 14:05:09" otherwise. */
// Time of day, with the date if it is not today.
export function formatTime(ns: number): string {
  const date = nsToDate(ns);
  const time = date.toLocaleTimeString([], { hour12: false });
  return date.toDateString() === new Date().toDateString()
    ? time
    : `${date.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

/** "12 s ago", "3 min ago", "2 h ago", "4 d ago". */
// "3 min ago".
export function timeAgo(ns: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - ns / 1_000_000) / 1000));
  if (seconds < 60) return `${seconds} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86_400)} d ago`;
}

// First characters of an id for display.
export const shortId = (id: string, length = 8) => id.slice(0, length);

/** Comma-separated list from the API ("a,b") -> array without empties. */
// "a,b" -> ["a","b"].
export function splitList(value: string | null | undefined): string[] {
  return value ? value.split(",").filter(Boolean) : [];
}

/** Pretty-print JSON text; anything that is not JSON is returned unchanged. */
// Indent JSON text; return other text unchanged.
export function prettyJson(text: string): { pretty: string; isJson: boolean } {
  try {
    const parsed = JSON.parse(text);
    if (parsed !== null && typeof parsed === "object") return { pretty: JSON.stringify(parsed, null, 2), isJson: true };
  } catch {
    /* not JSON */
  }
  return { pretty: text, isJson: false };
}

/**
 * Dollars, always in dollars (never cents), with enough decimals to show two significant digits of small amounts:
 * 0 -> "$0", 0.00021 -> "$0.00021", 0.0369 -> "$0.037", 0.42 -> "$0.42", 12.5 -> "$12.50", 2400 -> "$2,400". Missing -> "-".
 */
export function formatMoney(usd: number | null | undefined): string {
  if (usd === null || usd === undefined || Number.isNaN(usd)) return "-";
  if (usd === 0) return "$0";
  if (usd >= 1000) return `$${Math.round(usd).toLocaleString()}`;
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  const decimals = Math.min(10, Math.max(2, -Math.floor(Math.log10(usd)) + 1));
  return `$${usd.toFixed(decimals)}`;
}

/** The same amount in a sentence: always dollars, e.g. "$0.00021", "$0.42", "$1.20". */
export function moneyInWords(usd: number | null | undefined): string {
  if (usd === null || usd === undefined || Number.isNaN(usd)) return "an unknown amount";
  if (usd === 0) return "nothing";
  return formatMoney(usd);
}

/** Tokens, short: 850 -> "850", 1234 -> "1.2k", 157600 -> "158k", 2_400_000 -> "2.4M". Missing -> "-". */
export function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  if (n < 1000) return String(Math.round(n));
  if (n < 100_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** "3.4k tokens (3.1k in · 300 out)": the total with its two parts. */
export function tokensInOut(tokens: { input: number; output: number } | null | undefined): string {
  if (!tokens) return "-";
  return `${formatTokens(tokens.input + tokens.output)} tokens (${formatTokens(tokens.input)} in · ${formatTokens(tokens.output)} out)`;
}

/** +0.12 -> "↑ 12%", -0.3 -> "↓ 30%", null -> "" (nothing to compare with). */
export function formatChange(change: number | null | undefined): string {
  if (change === null || change === undefined || !Number.isFinite(change)) return "";
  const percent = Math.round(Math.abs(change) * 100);
  return percent === 0 ? "same as before" : `${change > 0 ? "↑" : "↓"} ${percent}%`;
}
