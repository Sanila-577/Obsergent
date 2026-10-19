// Every label, description and help text of the app in one place, in plain words. Pages import from here, so a
// word is changed once. "Simple" mode (the default) shows these; "Detailed" mode adds ids, raw data and protocol terms.

/** Navigation labels and the one-line description under each page title. */
export const PAGES = {
  overview: { title: "Overview", about: "How everything is doing right now." },
  conversations: { title: "Conversations", about: "The questions you asked. Pick one to read everything that happened until it was answered." },
  agents: { title: "Agents", about: "The agents that answered your questions, and how each one works: its steps, models and tools." },
  mcps: { title: "MCPs", about: "The tool servers your agents use (MCP servers), the tools each one offers, and whether they changed." },
  models: { title: "Models", about: "The AI models that were used: who provides them, how much they were used, what they cost and what they can do." },
  runs: { title: "All activity", about: "Everything that was recorded, including gateway and app traffic that is not a question. Newest first." },
  sessions: { title: "App activity", about: "What apps like Claude Desktop or Cursor did with a tool server, in order." },
  spending: { title: "Spending", about: "What your AI models cost. Prices are looked up automatically." },
  findings: { title: "Things to check", about: "Problems found automatically: loops, failures, risky tools and blocked requests." },
  gateway: { title: "Gateway guard", about: "What the gateway in front of your tools allowed or blocked, and how long it took." },
  map: { title: "Connections", about: "Who talks to which tool server. Hover a box to follow its path, click it for details." },
  compare: { title: "Compare", about: "Put two conversations side by side and see where they first differ." },
  about: { title: "About", about: "What Obsergent is, in one minute." },
} as const;

/** Short explanations shown in the (?) bubbles. */
export const HELP = {
  conversation: "One request that was handled from start to finish, for example one question you asked your agent.",
  discussion: "One question you asked an agent, together with everything that happened until it answered.",
  exchange: "One message in a discussion: your question, a model's reply, or a tool being used with its result.",
  mcp: "MCP is the standard way for an AI agent to use tools. An MCP server is a program that offers some tools.",
  step: "One thing that happened inside a conversation: a model thinking, a tool being used, a request passing through the gateway.",
  action: "A tool your agent used, for example 'search_books'. Also called a tool call.",
  tool: "Something an agent can do, for example 'search_books'. Each MCP server offers a few tools.",
  tokens: "Models read and write text in small pieces called tokens (about three quarters of a word). Prices are per token.",
  cost: "An estimate: the words processed times the model's current price per word. Models on your own computer are free.",
  typical: "Half of the calls were faster than this.",
  slowest: "Only 1 in 20 calls was slower than this (the 95th percentile).",
  blocked: "The gateway refused the request: not logged in, not allowed, or stopped by a rule.",
  session: "Everything one app did with one tool server since it started.",
  drift: "A tool changed its name or description after it was first seen. That can be harmless, or a sign of tampering.",
  prices: "Prices come from public price lists (models.dev, OpenRouter, Hugging Face, LiteLLM) and are re-checked automatically.",
} as const;

/** Gateway decisions in plain words. */
export const DECISION_WORDS: Record<string, string> = {
  allowed: "allowed",
  unauthorized: "blocked: not logged in",
  forbidden: "blocked: not allowed",
  throttled: "blocked: too many requests",
  denied: "blocked by a rule",
  error: "failed",
};

/** What "Things to check" types mean, in plain words. */
export const FINDING_WORDS: Record<string, string> = {
  tool_changed: "A tool changed after it was first seen",
  tool_added: "A new tool appeared",
  tool_removed: "A tool disappeared",
  risky_tool: "A tool that can change or send data",
  prompt_injection: "Text that tries to give the model orders",
  loop: "The agent repeated the same action",
  tool_error: "An action failed",
  slow_tool: "An action was very slow",
  gateway_decision: "The gateway blocked a request",
};
