// What AgentTrace is, how it differs from Langfuse, and the keyboard shortcuts.
import { Card, PageHead } from "../components/ui";
import { PAGES } from "../lib/words";

const ROWS: [string, string, string][] = [
  ["Main subject", "LLM generations and traces: prompts, completions, cost", "MCP tool calls and the traffic between client, gateway and server"],
  ["Recording MCP", "Needs instrumentation in both the client and the server", "A proxy records it with no code change: Claude Desktop, Cursor, any language"],
  ["Calls inside your agent", "Yes: generations, tokens, cost, prompts, scores", "Yes: model calls, tokens, conversation, and each requested tool call linked to the real MCP call and gateway decision"],
  ["Apps you can't modify", "Not applicable", "Sessions group everything such an app did with one server"],
  ["Tool-description tampering", "Not a feature", "Drift detection per server, plus a gateway-vs-upstream comparison"],
  ["API gateway view", "None", "WSO2 API Platform MCP gateway: decisions, refused calls, time spent inside the gateway, access-policy suggestions"],
  ["Security findings", "Not its focus", "Drift, risky tools, injection-like text, refused calls"],
  ["Agent smells", "Build your own dashboards", "Built in: loops, ignored tool errors, slow tools"],
  ["Setup", "Self-hosting needs several services, or use the cloud", "pip install + one process + one SQLite file, localhost only"],
  ["Cost", "Yes: model costs, dashboards", "Yes: an estimate per call, conversation and model, from prices that are looked up automatically (see Spending)"],
  ["Not in AgentTrace (on purpose)", "-", "Prompt management, evaluations, datasets, scores, user and team accounts"],
];

export function About() {
  return (
    <>
      <PageHead title={PAGES.about.title} about="AgentTrace records what your AI agents and apps do, shows it, and warns about problems." />
      <div className="col" style={{ maxWidth: 1000 }}>
        <Card title="AgentTrace vs Langfuse">
          <p className="muted" style={{ marginTop: 0 }}>They overlap (both store traces) but aim at different things. The same OpenTelemetry data can feed both.</p>
          <table><thead><tr><th>Area</th><th>Langfuse</th><th>AgentTrace</th></tr></thead>
            <tbody>{ROWS.map(([area, langfuse, agenttrace]) => <tr key={area}><td><strong>{area}</strong></td><td className="muted">{langfuse}</td><td>{agenttrace}</td></tr>)}</tbody></table>
        </Card>
        <Card title="Keyboard shortcuts">
          <dl className="kv" style={{ gridTemplateColumns: "160px 1fr" }}>
            <dt><kbd>⌘</kbd> <kbd>K</kbd></dt><dd>Search pages, runs, tools and servers</dd>
            <dt><kbd>g</kbd> then <kbd>o r s t f w m</kbd></dt><dd>Go to Overview, Conversations, App activity, Tools, Things to check, Gateway guard, Connections</dd>
            <dt><kbd>j</kbd> / <kbd>k</kbd></dt><dd>Next / previous step in a conversation</dd>
            <dt><kbd>/</kbd></dt><dd>Search inside a conversation</dd>
          </dl>
        </Card>
      </div>
    </>
  );
}
