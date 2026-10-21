// Thin typed wrappers around the Obsergent REST API. Every page talks to the server only through here.
// Only types (the shapes of API data); nothing is loaded at run time.
import type {
  AgentEntry, AgentGraph, McpServer, Usage, ModelEntry, QueryCard, QueryThread, QueryTimeline,
  Conversation, Finding, GatewayCall, GatewaySummary, Generations, Overview, PolicySuggestion, RunDiff,
  ServerInfo, Session, SnapshotsResponse, TimelineEvent, ToolListDiff, ToolStats, Topology, TraceDetail, TraceFilters,
  TraceSummary, Span, Spending, PriceStatus,
} from "./types";

// An error that remembers the HTTP status (404, 500...).
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Query-string values: text, numbers or booleans.
type Params = Record<string, string | number | boolean | undefined | null>;

// The one function that talks to the server: GET (or other method) and parse JSON.
async function request<T>(path: string, params?: Params, init?: RequestInit): Promise<T> {
  // Builds "?a=1&b=2".
  const query = new URLSearchParams();
  // Add each parameter that has a real value.
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "" && value !== false) query.set(key, String(value));
  }
  // Append the query string only if there is one.
  const url = query.size ? `${path}?${query}` : path;
  // Send the HTTP request to the server (same address as the page).
  const response = await fetch(url, init);
  // Status 400-599: turn it into an ApiError with the server's message.
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* the body was not JSON: keep the status text */
    }
    throw new ApiError(response.status, String(detail));
  }
  // Parse the JSON body into data.
  return response.json() as Promise<T>;
}

// One function per API route, each with the type of data it returns.
export const api = {
  health: () => request<{ status: string }>("/health"),
  version: () => request<{ version: string }>("/api/version"),
  overview: (hours: number) => request<Overview>("/api/stats/overview", { hours }),
  traces: (filters: TraceFilters = {}) => request<TraceSummary[]>("/api/traces", filters as Params),
  trace: (id: string) => request<TraceDetail>(`/api/traces/${id}`),
  conversation: (id: string) => request<Conversation>(`/api/traces/${id}/conversation`),
  generations: (id: string) => request<Generations>(`/api/traces/${id}/generations`),
  diff: (a: string, b: string) => request<RunDiff>("/api/diff", { a, b }),
  tools: (hours: number) => request<ToolStats[]>("/api/tools", { hours }),
  models: (hours?: number) => request<ModelEntry[]>("/api/models", { hours }),
  usage: (hours: number) => request<Usage>("/api/usage", { hours, buckets: hours <= 6 ? 12 : 24 }),
  topology: (hours: number, expand = "") => request<Topology>("/api/topology", { hours, expand }),
  queries: (params: { hours?: number; limit?: number; q?: string; before_ns?: number; since?: number; until?: number } = {}) => request<QueryCard[]>("/api/queries", params),
  query: (id: string) => request<QueryThread>(`/api/queries/${id}`),
  queriesTimeline: (hours: number) => request<QueryTimeline>("/api/queries/timeline", { hours }),
  agents: () => request<AgentEntry[]>("/api/agents"),
  agentGraph: (name: string) => request<AgentGraph>(`/api/agents/${encodeURIComponent(name)}/graph`),
  mcps: () => request<McpServer[]>("/api/mcps"),
  sessions: () => request<Session[]>("/api/sessions"),
  timeline: (id: string) => request<{ session_id: string; events: TimelineEvent[] }>(`/api/sessions/${id}/timeline`),
  servers: () => request<ServerInfo[]>("/api/servers"),
  snapshots: (name: string) => request<SnapshotsResponse>(`/api/servers/${encodeURIComponent(name)}/snapshots`),
  serverDiff: (name: string, fromId?: number, toId?: number) =>
    request<ToolListDiff>(`/api/servers/${encodeURIComponent(name)}/diff`, { from_id: fromId, to_id: toId }),
  serverCompare: (a: string, b: string) => request<ToolListDiff & { a: string; b: string }>("/api/servers/compare", { a, b }),
  findings: (params: { severity?: string; type?: string; include_acknowledged?: boolean } = {}) =>
    request<Finding[]>("/api/findings", params),
  acknowledge: (id: string) => request<{ id: string }>(`/api/findings/${id}/ack`, undefined, { method: "POST" }),
  unacknowledge: (id: string) => request<{ id: string }>(`/api/findings/${id}/ack`, undefined, { method: "DELETE" }),
  gateway: (hours: number) => request<GatewaySummary>("/api/gateway/summary", { hours }),
  gatewayCall: (activityId: string) =>
    request<{ call: GatewayCall | null; spans: Span[] }>(`/api/gateway/calls/${encodeURIComponent(activityId)}`),
  spending: (hours: number, buckets = 24, reprice?: string) => request<Spending>("/api/spending", { hours, buckets, reprice }),
  prices: () => request<PriceStatus>("/api/prices"),
  refreshPrices: () => request<PriceStatus>("/api/prices/refresh", undefined, { method: "POST" }),
  policy: (server: string) => request<PolicySuggestion>("/api/policy/suggestion", { server }),
};
