// Every label, description and help text of the app in one place, in plain words. Pages import from here, so a
// word is changed once. "Simple" mode (the default) shows these; "Detailed" mode adds ids, raw data and protocol terms.

/** Navigation labels and the one-line description under each page title. */
export const PAGES = {
  overview: { title: "Overview", about: "How everything is doing right now." },
  runs: { title: "Conversations", about: "Every time an agent or app did something, newest first. Click one to see what happened step by step." },
  sessions: { title: "App activity", about: "What apps like Claude Desktop or Cursor did with a tool server, in order." },
  servers: { title: "Tools", about: "The tools your agents can use, how often they are used, and whether they changed." },
  spending: { title: "Spending", about: "What your AI models cost. Prices are looked up automatically." },
  findings: { title: "Things to check", about: "Problems found automatically: loops, failures, risky tools and blocked requests." },
  gateway: { title: "Gateway guard", about: "What the gateway in front of your tools allowed or blocked, and how long it took." },
  map: { title: "Connections", about: "Who talks to which tool server. Click a circle to see its conversations." },
  compare: { title: "Compare", about: "Put two conversations side by side and see where they first differ." },
  about: { title: "About", about: "What AgentTrace is and how it differs from other tools." },
} as const;

/** Short explanations shown in the (?) bubbles. */
export const HELP = {
  conversation: "One request that was handled from start to finish, for example one question you asked your agent.",
  step: "One thing that happened inside a conversation: a model thinking, a tool being used, a request passing through the gateway.",
  action: "A tool your agent used, for example 'search_books'. Also called a tool call.",
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
