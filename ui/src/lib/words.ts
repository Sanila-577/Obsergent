// Every label, description and help text of the app in one place, in plain words. Pages import from here, so a
// word is changed once. "Simple" mode (the default) shows these; "Detailed" mode adds ids, raw data and protocol terms.

/** Navigation labels, a short line under each title (8 words at most) and the longer explanation behind its (?). */
export const PAGES = {
  overview: { title: "Overview", about: "How your agents are doing.", help: "Questions, steps, tokens and cost for the chosen period. Click any number or point to see what is behind it." },
  conversations: { title: "Conversations", about: "Every question, step by step.", help: "Pick a question to read everything that happened until it was answered: what you asked (right) and what the AI did (left)." },
  agents: { title: "Agents", about: "How each agent works.", help: "Each agent's steps, the models and tools it uses and the MCP servers behind them, drawn as a graph." },
  mcps: { title: "MCPs", about: "Tool servers and their tools.", help: "The MCP servers your agents use, the tools each offers, how they are used and whether they changed." },
  models: { title: "Models", about: "Models, tokens and prices.", help: "Every AI model that was used: provider, tokens, cost, speed, price and what it can do." },
  runs: { title: "All activity", about: "Everything recorded, newest first.", help: "Every recorded run, including gateway and app traffic that is not a question." },
  sessions: { title: "App activity", about: "What apps did with tool servers.", help: "What apps like Claude Desktop or Cursor did with a tool server, in order." },
  spending: { title: "Usage & cost", about: "Tokens and dollars, where they went.", help: "How many tokens your models used and what they cost. Prices are looked up automatically." },
  findings: { title: "Things to check", about: "Problems found for you.", help: "Loops, failures, risky or changed tools, blocked requests, token budget and heavy questions." },
  gateway: { title: "Gateway guard", about: "What the gateway allowed or blocked.", help: "What the gateway in front of your tools allowed or blocked, and how long it took." },
  map: { title: "Connections", about: "Who talks to which tool server.", help: "Hover a box to follow its path, click it for details." },
  compare: { title: "Compare", about: "Two conversations side by side.", help: "See where two conversations first differ." },
  about: { title: "About", about: "Obsergent in one minute.", help: "What Obsergent is and how it works." },
} as const;

/** Short explanations shown in the (?) bubbles. */
export const HELP = {
  conversation: "One request that was handled from start to finish, for example one question you asked your agent.",
  discussion: "One question you asked an agent, together with everything that happened until it answered.",
  step: "One message in a question: yours (human) or the AI's (a model reply or a tool it used).",
  human: "Messages you typed.",
  ai: "Messages from the AI side: each model reply and each tool it used.",
  event: "One recorded event inside a run: a model call, a tool call, a request through the gateway.",
  mcp: "MCP is the standard way for an AI agent to use tools. An MCP server is a program that offers some tools.",
  action: "A tool your agent used, for example 'search_books'. Also called a tool call.",
  tool: "Something an agent can do, for example 'search_books'. Each MCP server offers a few tools.",
  tokens: "Models read and write text in small pieces called tokens (about three quarters of a word). Providers bill per token.",
  tokensIn: "Tokens in: everything the model READ for a call: the instructions, your question, the chat so far, the tool results and the descriptions of the tools it may use. It grows with every step, because each model call re-reads the whole conversation.",
  tokensOut: "Tokens out: everything the model WROTE: its answer and its requests to use a tool. Usually much smaller than tokens in, but each one costs more (often 3 to 5 times an input token).",
  tokensInOut: "Each peak is one question, as high as the tokens it used (in + out). Tokens in = what the model read (instructions, your question, the chat so far, tool results). Tokens out = what it wrote (answers, tool requests). The counts come from the model provider itself (Ollama: prompt_eval_count and eval_count).",
  estimated: "Estimated from the text length (about 4 characters per token): it becomes part of the next model call's input.",
  budget: "A daily token limit you can set in config.yaml (usage.daily_token_budget). Obsergent warns before it is reached.",
  cost: "An estimate: the tokens used times the model's price per token. Models on your own computer are free.",
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
  token_budget: "Today's tokens are close to your budget",
  heavy_question: "A question used far more tokens than usual",
  gateway_decision: "The gateway blocked a request",
};
