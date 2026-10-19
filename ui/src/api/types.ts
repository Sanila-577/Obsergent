// Shapes returned by the Obsergent REST API (src/obsergent/server/app.py). Kept in one place so a change in
// the backend shows up as a type error here, not as a blank screen.

export type Attributes = Record<string, unknown>;

/** The cost of one model call (dollars), or why there is none. Always an estimate unless confidence is "exact". */
export interface CostInfo {
  usd: number | null;
  status: "priced" | "local" | "unpriced";
  confidence: "confirmed" | "one_source" | "disagree" | "exact" | "set_by_you" | "";
  source: string;
  model: string;
  price_date_ns: number;
  input_usd: number;
  output_usd: number;
  cache_usd: number;
  note: string;
  range_usd: [number, number] | null;
  /** Where the money went, e.g. [{label: "input", usd: 0.0001}, ...]. */
  breakdown: { label: string; usd: number }[];
  /** batch / flex / priority when the call used a service tier. */
  tier: string;
}

/** Totals for a run or a time window. `enabled: false` when pricing is switched off. */
export interface CostTotals {
  enabled?: boolean;
  usd: number;
  /** The part of `usd` the provider reported itself (OpenRouter, xAI); the rest is estimated from prices. */
  exact_usd?: number;
  estimated_usd?: number;
  exact?: number;
  priced: number;
  local: number;
  unpriced: number;
  calls: number;
}

export interface Span {
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string;
  service: string;
  start_ns: number;
  end_ns: number;
  duration_ms: number;
  status_code: "UNSET" | "OK" | "ERROR";
  status_message: string;
  attributes: Attributes;
  events: { name: string; time_ns: number; attributes: Attributes }[];
}

export interface Smell {
  type: string;
  severity: Severity;
  message: string;
  span_id?: string;
}

export interface TraceDetail {
  trace_id: string;
  question: string;
  cost: CostTotals;
  spans: Span[];
  smells: Smell[];
}

export interface TraceSummary {
  trace_id: string;
  root_name: string;
  start_ns: number;
  end_ns: number;
  duration_ms: number;
  span_count: number;
  error_count: number;
  tool_calls: number;
  services: string;
  llm_calls: number;
  models: string | null;
  total_tokens: number | null;
  user_id: string | null;
  chat_session: string | null;
  servers: string | null;
  tools: string | null;
  decisions: string | null;
  smells_count: number;
  question: string;
  cost: CostTotals;
}

export type Severity = "high" | "medium" | "low";
export type Decision = "allowed" | "unauthorized" | "forbidden" | "throttled" | "denied" | "error";

export interface LatencySummary {
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
}

export interface ToolStats extends LatencySummary {
  server: string | null;
  tool: string | null;
  calls: number;
  errors: number;
  last_seen_ns: number;
  decisions: Record<string, number>;
}

export interface ModelUsage {
  cost_usd?: number | null;
  cost_status?: string | null;
  /** The one name shown for the model (no version date). */
  model: string;
  provider: string | null;
  calls: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  avg_ms: number;
  max_ms: number;
  p95_ms: number;
  /** The raw names recorded for this model (the dated and the undated one), shown in Detailed mode. */
  versions: string[];
}

/** What the price lists know about a model besides its price. */
export interface ModelInfo {
  name?: string | null;
  family?: string | null;
  context?: number | null;
  max_output?: number | null;
  input_modalities?: string[];
  output_modalities?: string[];
  tool_call?: boolean | null;
  reasoning?: boolean | null;
  open_weights?: boolean | null;
  release_date?: string | null;
  knowledge?: string | null;
  provider_name?: string | null;
}

/** One entry of the Models page (`GET /api/models`). */
export interface ModelEntry extends ModelUsage {
  display: string;
  cached_tokens: number;
  reasoning_tokens: number;
  usd: number;
  exact_usd: number;
  estimated_usd: number;
  unpriced: number;
  errors: number;
  error_rate: number;
  questions: number;
  first_ns: number;
  last_ns: number;
  status: "priced" | "local" | "unpriced";
  price: { input: number | null; output: number | null; cache_read: number | null; cache_write: number | null;
           source: string; confidence: string; since_ns: number } | null;
  info: ModelInfo;
}

/** A question someone asked an agent, as a card (`GET /api/queries`). */
export interface QueryCard {
  trace_id: string;
  question: string;
  answer: string;
  started_ns: number;
  duration_ms: number;
  agent: string;
  models: string[];
  tools: string[];
  model_calls: number;
  tool_calls: number;
  exchanges: number;
  status: "ok" | "problem";
  problem: string;
  user_id: string | null;
  session: string | null;
  root_name: string;
  cost: CostTotals;
}

/** One message of a question's thread. */
export interface ThreadItem {
  kind: "question" | "model" | "answer" | "tool";
  text?: string;
  step?: number;
  model?: string;
  raw_model?: string | null;
  provider?: string | null;
  start_ns: number;
  duration_ms?: number | null;
  span_id?: string | null;
  mcp_span_id?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  status?: string;
  message?: string;
  cost?: CostInfo | null;
  requests?: string[];
  name?: string;
  arguments?: string;
  result?: string;
  decision?: string | null;
  server?: string | null;
}

export interface QueryThread extends QueryCard {
  thread: ThreadItem[];
  tools_offered: string[];
}

/** The peaks chart: one point per question, or time slots when there are many. */
export interface QueryTimeline {
  mode: "questions" | "slots";
  window_hours?: number;
  points: {
    trace_id: string;
    start_ns: number;
    end_ns?: number;
    question: string;
    exchanges: number;
    model_calls?: number;
    tool_calls?: number;
    cost_usd?: number | null;
    duration_ms?: number;
    status?: string;
    count?: number;
    questions?: string[];
  }[];
}

export interface AgentEntry {
  name: string;
  framework: string;
  questions: number;
  model_calls: number;
  tool_calls: number;
  models: string[];
  tools: string[];
  usd: number;
  exchanges: number;
  avg_exchanges: number;
  problems: number;
  first_ns: number;
  last_ns: number;
  latest_question: string;
}

export interface GraphNode {
  id: string;
  kind: "start" | "end" | "step" | "model" | "tool" | "mcp" | "gateway";
  label: string;
  calls: number;
  total_ms: number;
  avg_ms: number | null;
  errors: number;
  cost_usd: number;
  traces: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  calls: number;
  total_ms: number;
  avg_ms: number | null;
  errors: number;
}

export interface AgentGraph {
  agent: string;
  framework: string;
  approximate: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface McpParameter {
  name: string;
  type: string;
  required: boolean;
  description: string;
  choices: string[];
}

export interface McpTool extends LatencySummary {
  name: string;
  description: string;
  parameters: McpParameter[];
  schema: unknown;
  risky: boolean;
  calls: number;
  errors: number;
  last_used_ns: number | null;
  used: boolean;
  changed: boolean;
  removed?: boolean;
  decisions: string[];
}

export interface McpServer {
  name: string;
  transport: "program" | "web";
  command: string | null;
  via_gateway: boolean;
  tools: McpTool[];
  tool_count: number;
  calls: number;
  errors: number;
  error_rate: number;
  last_seen_ns: number | null;
  versions: number;
  changes: number;
  changed: boolean;
}

export interface Overview {
  /** Questions asked in the window (agent runs with a model call). */
  discussions: number;
  /** MCP servers, and the distinct tools they offer. */
  mcps: number;
  tools_total: number;
  latest_queries: QueryCard[];
  timeline: QueryTimeline;
  window_hours: number;
  counts: { runs: number; spans: number; tool_calls: number; errors: number; llm_calls: number; tokens: number; questions: number };
  error_rate: number;
  tool_latency: LatencySummary;
  decisions: Record<string, number>;
  busiest_tools: ToolStats[];
  slowest_tools: ToolStats[];
  activity: { start_ns: number; calls: number; errors: number }[];
  open_findings: number;
  open_findings_high: number;
  servers: number;
  sessions: number;
  models: ModelUsage[];
  cost: Spending;
}

export interface Finding {
  id: string;
  type: string;
  severity: Severity;
  message: string;
  seen_ns: number;
  count: number;
  acknowledged: boolean;
  acknowledged_ns: number | null;
  trace_id?: string;
  span_id?: string | null;
  server?: string | null;
  tool?: string | null;
  decision?: string;
}

export interface Session {
  session_id: string;
  server_name: string | null;
  command: string | null;
  start_ns: number;
  end_ns: number;
  span_count: number;
  trace_count: number;
  tool_calls: number;
  error_count: number;
}

export interface TimelineEvent {
  span_id: string;
  trace_id: string;
  start_ns: number;
  duration_ms: number;
  method: string | null;
  tool: string | null;
  arguments: string | null;
  result: string | null;
  status: string;
  message: string;
  decision: string | null;
  http_status: number | null;
}

export interface ServerInfo {
  server_name: string;
  versions: number;
  first_seen_ns: number;
  last_change_ns: number;
}

export interface DiffSegment {
  op: "equal" | "insert" | "delete";
  text: string;
}

export interface ToolListDiff {
  same: boolean;
  added: string[];
  removed: string[];
  changed: {
    tool: string;
    description_changed: boolean;
    description: { before: string; after: string; diff: DiffSegment[] };
    schema_changed: boolean;
    schema: { before: unknown; after: unknown };
  }[];
  server?: string;
  from_id?: number;
  to_id?: number;
}

export interface Snapshot {
  id: number;
  fingerprint: string;
  first_seen_ns: number;
  tools: { name: string; description?: string; inputSchema?: unknown }[];
}

export interface SnapshotsResponse {
  server: string;
  snapshots: Snapshot[];
  drift: { type: string; severity: Severity; tool: string; message: string; snapshot_id: number; seen_ns: number }[];
}

export interface TopologyNode {
  id: string;
  kind: "client" | "gateway" | "server" | "tool";
  label: string;
  via_gateway: boolean;
  /** Servers only: how many tools were used on it, and whether they are drawn. */
  tool_count: number | null;
  expanded: boolean;
}

export interface Topology {
  nodes: TopologyNode[];
  edges: { source: string; target: string; calls: number; errors: number }[];
}

export interface GatewayCall {
  activity_id: string;
  trace_id: string;
  span_id: string;
  start_ns: number;
  api: string | null;
  status: number | null;
  decision: Decision | "unknown";
  consumer_key: string | null;
  gateway_ms: number;
  phases: Record<string, number>;
  proxy_span_id: string | null;
  tool: string | null;
  method: string | null;
  proxy_ms: number | null;
  caller: string | null;
  correlation: "trace" | "activity" | "none";
}

export interface GatewaySummary {
  receiving: boolean;
  last_seen_ns: number | null;
  calls_total: number;
  decisions: Record<string, number>;
  phases: Record<string, LatencySummary>;
  by_tool: Record<string, Record<string, number>>;
  by_caller: Record<string, Record<string, number>>;
  calls: GatewayCall[];
}

export interface PolicySuggestion {
  server: string;
  allow: { tool: string; calls: number }[];
  review: { tool: string; calls: number; reason: string }[];
  unused: { tool: string }[];
  policy: { tools: { mode: string; exceptions: string[] } };
  suggested_scopes: Record<string, string>;
  notes: string[];
}

export interface Message {
  role: string;
  content: string;
  name: string;
  tool_call_id: string;
  link: ToolLink | null;
  tool_calls: { id: string; name: string; arguments: string; link: ToolLink | null }[];
}

export interface ToolLink {
  tool_call_id: string;
  name: string;
  arguments: string;
  tool_span_id: string | null;
  mcp_span_id: string | null;
  mcp_status: string | null;
  gateway_decision: string | null;
}

export interface GenerationSummary {
  calls: number;
  models: string[];
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number;
  cost?: CostTotals;
}

export interface Conversation {
  trace_id: string;
  summary: GenerationSummary;
  messages: Message[];
}

export interface Generation {
  cost: CostInfo | null;
  cache_read_tokens: number;
  cache_write_tokens: number;
  reasoning_tokens: number;
  tool_definition_tokens: number;
  span_id: string;
  span_name: string;
  start_ns: number;
  model: string | null;
  provider: string | null;
  parameters: Record<string, unknown>;
  tools: string[];
  input_messages: { role: string; content: string }[];
  output_messages: { role: string; content: string; tool_calls: { name: string; arguments: string }[] }[];
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number;
  status_code: string;
  tool_links: ToolLink[];
}

export interface Generations {
  trace_id: string;
  summary: GenerationSummary;
  generations: Generation[];
}

export interface RunDiff {
  a: string;
  b: string;
  divergence: { same: boolean; step?: number; steps?: number; reason?: string; a?: unknown; b?: unknown };
  steps_a: [string, string][];
  steps_b: [string, string][];
}

export interface TraceFilters {
  q?: string;
  errors_only?: boolean;
  tool?: string;
  server?: string;
  decision?: string;
  model?: string;
  session_id?: string;
  since?: number;
  until?: number;
  before_ns?: number;
  limit?: number;
}

/** `GET /api/spending`: everything the Spending page shows. */
export interface Spending {
  enabled: boolean;
  totals: CostTotals;
  by_model: { provider: string; model: string; usd: number; calls: number; prompt_tokens: number; completion_tokens: number;
              status: string; confidence: string; note: string; source: string }[];
  by_tool: { tool: string; usd: number; calls: number }[];
  series: { start_ns: number; usd: number; by_model: Record<string, number> }[];
  top_runs: { trace_id: string; usd: number; calls: number; start_ns: number; question: string }[];
  reprice: string;
}

/** `GET /api/prices`: the badge "prices checked 2 hours ago" and the price-check panel. */
export interface PriceStatus {
  enabled: boolean;
  auto_refresh: boolean;
  exact_from_provider: boolean;
  refresh_minutes: Record<string, number>;
  changes: { provider: string; model: string; source: string; effective_from_ns: number; old_input: number | null;
             new_input: number | null; old_output: number | null; new_output: number | null }[];
  reprice: string;
  sources: { source: string; models: number; checked_ns: number; fetched_ns: number; error: string }[];
  last_checked_ns: number;
  disagreements: { provider: string; model: string; prices: Record<string, [number, number]> }[];
}
