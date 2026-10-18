// Shapes returned by the AgentTrace REST API (src/agenttrace/server/app.py). Kept in one place so a change in
// the backend shows up as a type error here, not as a blank screen.

export type Attributes = Record<string, unknown>;

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
  model: string;
  provider: string | null;
  calls: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  avg_ms: number;
  max_ms: number;
  p95_ms: number;
}

export interface Overview {
  window_hours: number;
  counts: { runs: number; spans: number; tool_calls: number; errors: number; llm_calls: number; tokens: number };
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
  kind: "client" | "server" | "tool";
  label: string;
  via_gateway: boolean;
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
}

export interface Conversation {
  trace_id: string;
  summary: GenerationSummary;
  messages: Message[];
}

export interface Generation {
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
  before_ns?: number;
  limit?: number;
}
