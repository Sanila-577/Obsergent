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
