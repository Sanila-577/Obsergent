import { expect, test, type Page } from "@playwright/test";

// The welcome tour would cover the page: every test starts as a returning visitor (one test below checks the tour itself).
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => { if (!sessionStorage.getItem("tour-test")) localStorage.setItem("obsergent.tour", "done"); });
});

test("the spending page says what the models cost and lets you dig in", async ({ page }) => {
  await page.goto("/spending?view=dollars");
  await expect(page.getByRole("heading", { name: "Usage & cost" })).toBeVisible();
  await expect(page.getByText(/You spent/)).toBeVisible();
  await expect(page.getByRole("img", { name: /Spending over time/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Where did the money go?" })).toBeVisible();
  await expect(page.locator(".share-row").filter({ hasText: "claude-sonnet-4-5" })).toContainText("$");
  await expect(page.locator(".share-row").filter({ hasText: "qwen2.5:7b" })).toContainText("free");
  await page.getByRole("tab", { name: "By action" }).click();
  await expect(page.locator(".share-row").first()).toBeVisible();
  await page.getByRole("tab", { name: "By model" }).click();
  await page.getByRole("button", { name: "gpt-4o-mini", exact: true }).click(); // the legend filters the conversations to that model
  await expect(page).toHaveURL(/model=gpt-4o-mini/);
  await expect(page.locator("tbody tr").first()).toBeVisible();
});

test("a cost the provider reported is marked exact and its share is stated", async ({ page }) => {
  await page.goto("/spending?view=dollars");
  await expect(page.getByText(/of this amount was reported by the provider/)).toBeVisible();
  await page.goto("/runs?model=openai/gpt-4o-mini");
  await expect(page.locator("tbody tr").first()).toContainText("$0.037"); // 3 model calls x $0.0123, reported by the provider
  await page.locator("tbody tr").first().click();
  await page.getByRole("tab", { name: "Model calls" }).click();
  await expect(page.locator(".exact-tag").first()).toBeVisible();
});

test("conversations show what they cost, and a conversation shows where the money went", async ({ page }) => {
  await page.goto("/runs?model=claude-sonnet-4-5");
  await expect(page.getByRole("columnheader", { name: "Cost" })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toContainText("$");
  await page.locator("tbody tr").first().click();
  await expect(page.getByText("What this conversation cost")).toBeVisible();
  await expect(page.getByRole("group", { name: "Cost of each model call" })).toBeVisible();
  await page.getByRole("tab", { name: "Model calls" }).click();
  await expect(page.getByRole("columnheader", { name: "Cost" })).toBeVisible();
  await page.goto("/runs?model=qwen2.5:7b");
  await expect(page.locator("tbody tr").first()).toContainText("free");
});

test("a time slot from the chart opens exactly those conversations", async ({ page }) => {
  const now = Math.floor(Date.now() / 1000);
  await page.goto(`/runs?from=${now - 3600}&to=${now + 60}`);
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear filters" })).toBeVisible();
});

/** Show everything (ids, raw data, protocol terms): the Detailed mode, remembered by the app in localStorage. */
async function detailed(page: Page) {
  await page.addInitScript(() => localStorage.setItem("obsergent.detailed", "true"));
}

// Every test starts from the same seeded data: ~48 runs (agent runs and gateway calls), a loop, a drifting server.

test("the overview shows four numbers, what needs attention and the questions chart", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.locator(".tile").filter({ hasText: "Discussions" })).toContainText("35");
  await expect(page.locator(".tile").filter({ hasText: "Steps" }).locator(".side-count")).toHaveCount(2);
  await expect(page.locator(".tile").filter({ hasText: "Tokens" })).toContainText(/\d+(\.\d)?k/);
  await expect(page.locator(".tile").filter({ hasText: "Cost" })).toContainText("$");
  await expect(page.locator(".tile")).toHaveCount(4);
  await expect(page.getByRole("list", { name: "Needs attention" }).getByText(/blocked by the gateway/)).toBeVisible();
  await expect(page.getByRole("img", { name: /Questions over time/ })).toBeVisible();
  await page.locator(".tile").filter({ hasText: "Tokens" }).click();
  await expect(page).toHaveURL(/\/spending\?view=tokens/);
});

test("find the slowest tool in a few clicks", async ({ page }) => {
  await page.goto("/mcps?server=bookshop");
  await page.getByRole("button", { name: "Slowest", exact: true }).click();
  await expect(page).toHaveURL(/sort=slow/);
  const tools = page.getByRole("list", { name: "Tools of bookshop" }).locator(".gcard");
  await tools.first().click();
  await expect(page.getByText("How it is used")).toBeVisible();
});

test("runs can be filtered, and the filter lives in the URL", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.locator("tbody tr").first()).toBeVisible(); // wait for the table before counting its rows
  const all = await page.locator("tbody tr").count();
  expect(all).toBeGreaterThan(10);
  await page.getByLabel("Problems only").check();
  await expect(page).toHaveURL(/errors_only=1/);
  await expect.poll(() => page.locator("tbody tr").count()).toBeLessThan(all);
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect.poll(() => page.locator("tbody tr").count()).toBe(all);
  await page.getByLabel("Gateway decision").selectOption("forbidden");
  await expect(page.locator("tbody .badge.forbidden").first()).toBeVisible(); // a row with that gateway decision
  await expect(page.locator("tbody tr")).not.toHaveCount(all);
  await page.goto("/runs?q=zzz-nothing-matches");
  await expect(page.getByText("No conversations match these filters")).toBeVisible();
});

test("a run opens as a timeline with an inspector, keyboard navigation and copy-as-curl", async ({ page }) => {
  await detailed(page);
  await page.goto("/runs?tool=get_price_and_stock&server=bookshop");
  await page.locator("tbody tr").first().click();
  await expect(page.getByRole("tree", { name: "Spans of this run" })).toBeVisible();
  await expect(page.getByText("Pick a step")).toBeVisible();
  await page.getByRole("treeitem").first().click();
  await page.keyboard.press("j");
  await expect(page.getByRole("treeitem", { selected: true })).toHaveCount(1);
  await page.getByRole("treeitem").filter({ hasText: "tools/call get_price_and_stock" }).click();
  await expect(page.getByRole("button", { name: "Copy as curl" })).toBeVisible();
  await page.getByRole("tab", { name: "Input" }).click();
  await expect(page.locator("pre.code")).toContainText("book_id");
  await expect(page).toHaveURL(/span=/);
});

test("the conversation links a model's tool call to the real MCP call", async ({ page }) => {
  await page.goto("/runs?model=qwen2.5:7b");
  await page.locator("tbody tr").first().click();
  await page.getByRole("tab", { name: "Chat" }).click();
  await expect(page.getByText("You are a helpful bookshop assistant")).toBeVisible();
  await page.getByRole("link", { name: "View the MCP call" }).first().click();
  await expect(page).toHaveURL(/span=/);
  await expect(page.getByRole("treeitem", { selected: true })).toContainText("tools/call");
});

test("findings can be dismissed and brought back", async ({ page }) => {
  await page.goto("/findings");
  await expect(page.locator(".finding strong", { hasText: "A tool changed after it was first seen" })).toBeVisible();
  await expect(page.locator(".finding strong", { hasText: "The agent repeated the same action" })).toBeVisible();
  const before = await page.locator(".finding").count();
  await page.getByRole("button", { name: /Dismiss/ }).first().click();
  await expect.poll(() => page.locator(".finding").count()).toBe(before - 1);
  await page.getByLabel("Show dismissed").check();
  await expect.poll(() => page.locator(".finding").count()).toBe(before);
  await page.getByRole("button", { name: /Restore/ }).click();
  await page.getByLabel("Show dismissed").uncheck();
  await expect.poll(() => page.locator(".finding").count()).toBe(before);
});

test("an MCP server's changed tool description is shown word by word", async ({ page }) => {
  await page.goto("/mcps?server=tickets&tab=changes");
  await expect(page.getByRole("heading", { name: "Has this MCP server changed?" })).toBeVisible();
  await expect(page.locator(".diff ins").first()).toContainText("Ignore previous instructions");
  await page.getByLabel("Compare with").selectOption("bookshop-upstream");
  await expect(page.getByText("Only in bookshop-upstream").or(page.getByText("Only in tickets")).first()).toBeVisible();
});

test("the gateway page explains what the gateway decided and where time went", async ({ page }) => {
  await detailed(page);
  await page.goto("/gateway");
  await expect(page.getByText("The gateway is reporting to Obsergent")).toBeVisible();
  await expect(page.locator(".tile").filter({ has: page.getByText("allowed", { exact: true }) })).toBeVisible();
  await expect(page.locator(".tile", { hasText: "blocked: not allowed" })).toBeVisible();
  await expect(page.getByText("Where the gateway spends its time")).toBeVisible();
  await page.locator("section", { hasText: "Latest requests through the gateway" }).locator("tbody tr.click").first().click();
  await expect(page.getByText("Gateway call id").first()).toBeVisible();
  await expect(page.getByText("Which tools should be allowed?")).toBeVisible();
  await page.getByLabel("Server", { exact: true }).selectOption("bookshop");
  await expect(page.getByText("Policy parameters")).toBeVisible();
  await expect(page.locator("pre.code").last()).toContainText('"mode": "deny"');
});

test("the connections graph is layered, hides tools until asked, and a click gives details", async ({ page }) => {
  await page.goto("/map");
  await expect(page.getByRole("group", { name: "Connections between apps, the gateway and MCP servers" })).toBeVisible();
  await expect(page.locator(".flow-node.gateway")).toHaveCount(1);
  await expect(page.locator(".flow-node.server").first()).toBeVisible();
  await expect(page.locator(".flow-node.tool")).toHaveCount(0); // tools stay hidden until a server is opened
  await page.locator(".flow-node.server", { hasText: "tickets" }).click();
  const panel = page.getByRole("complementary", { name: "Details of tickets" });
  await expect(panel).toBeVisible();
  await panel.getByRole("button", { name: /Show its/ }).click();
  await expect(page.locator(".flow-node.tool").first()).toBeVisible();
  await expect(panel.getByRole("link", { name: "Open the MCP page →" })).toHaveAttribute("href", /\/mcps\?server=tickets/);
  await page.getByRole("button", { name: "Reset view" }).click();
});

test("two runs can be compared, and the first difference is pointed out", async ({ page }) => {
  await page.goto("/runs?model=qwen2.5:7b");
  const boxes = page.getByRole("checkbox", { name: /Select .* to compare/ });
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await page.getByRole("button", { name: "Compare these 2" }).click();
  await expect(page).toHaveURL(/compare\?a=.*&b=/);
  await expect(page.getByText(/Both conversations used the same|first difference at action/)).toBeVisible();
});

test("sessions group an app's calls into a timeline", async ({ page }) => {
  await page.goto("/sessions");
  await page.locator("tbody tr").first().click();
  await expect(page.getByRole("heading", { name: "What the app did" })).toBeVisible();
  await expect(page.locator(".msg").first()).toBeVisible();
});

test("the command palette jumps anywhere", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Control+k");
  await page.getByLabel("Search", { exact: true }).fill("gateway");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/gateway/);
  await page.keyboard.press("g");
  await page.keyboard.press("n");
  await expect(page).toHaveURL(/\/map/);
  await page.keyboard.press("g");
  await page.keyboard.press("m");
  await expect(page).toHaveURL(/\/mcps/);
});

test("settings stay after a reload: theme, live tail and time window", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Switch theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Live" }).click();
  await page.getByRole("button", { name: "7 days" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Live" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
});

test("a deep link survives a reload, and an unknown page says so", async ({ page }) => {
  await page.goto("/runs");
  const href = await page.locator("tbody tr a").first().getAttribute("href");
  await page.goto(href!);
  await page.reload();
  await expect(page.getByRole("tree", { name: "Spans of this run" })).toBeVisible();
  await page.goto("/no/such/page");
  await expect(page.getByText("Page not found")).toBeVisible();
});

test("the about page explains Obsergent in a few words and its flow can be clicked", async ({ page }) => {
  await page.goto("/about");
  await expect(page.getByRole("heading", { name: "What is Obsergent?" })).toBeVisible();
  await expect(page.getByText("Langfuse")).toHaveCount(0);
  await page.getByRole("tab", { name: "The recorder" }).click();
  await expect(page.getByRole("tabpanel")).toContainText("proxy sits between");
  await expect(page.locator('.nav-link[data-nav="App activity"]')).toHaveClass(/lit/);
  await page.getByRole("tab", { name: "This dashboard" }).click();
  await expect(page.getByRole("tabpanel")).toContainText("one file on your computer");
  await page.getByRole("link", { name: /Read what was asked/ }).click();
  await expect(page).toHaveURL(/\/conversations/);
});

test("Simple mode hides technical columns and Detailed mode shows them", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Services" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Raw" })).toHaveCount(0);
  await page.getByRole("button", { name: "Detailed" }).click();
  await expect(page.getByRole("columnheader", { name: "Services" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Detailed" })).toHaveAttribute("aria-pressed", "true"); // remembered
});

test("an empty page guides you instead of showing a dead end", async ({ page }) => {
  await page.route("**/api/traces?*", (route) => route.fulfill({ json: [] }));
  await page.goto("/runs");
  await expect(page.getByText("Three steps and this page fills itself")).toBeVisible();
  await expect(page.getByText(/Waiting for the first data|Data arrived/)).toBeVisible();
});

test("the help bubbles explain words in plain language", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.locator("th .help").first().hover();
  await expect(page.locator("th .help .help-bubble").first()).toBeVisible();
});

// ------------------------------------------------------------------------- the question-first pages

test("the conversations page shows the questions as scrollable cards and opens each one's own thread", async ({ page }) => {
  await page.goto("/conversations");
  const cards = page.locator(".q-card");
  await expect(cards.first()).toBeVisible();
  for (const question of ["Which books by Eric Matthes do you sell?", "Is Fluent Python cheaper than Python Crash Course?", "What is the cheapest book you have?"]) {
    await expect(cards.filter({ hasText: question }).first()).toBeAttached();
  }
  // the strip scrolls with the arrow button
  const before = await page.locator(".q-strip").evaluate((el) => el.scrollLeft);
  await page.getByRole("button", { name: "Scroll questions right" }).click();
  await expect.poll(() => page.locator(".q-strip").evaluate((el) => el.scrollLeft)).toBeGreaterThan(before);
  // a click selects a question: its thread shows only that question, and the choice lives in the URL
  const cheapest = cards.filter({ hasText: "What is the cheapest book you have?" }).first();
  await cheapest.click();
  await expect(cheapest).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(/q=[0-9a-f]+/);
  await expect(page.locator(".bubble.question")).toHaveCount(1);
  await expect(page.locator(".bubble.question")).toContainText("What is the cheapest book you have?");
  await expect(page.locator(".bubble.answer")).toHaveCount(1);
  await expect(page.locator(".bubble.tool").first()).toBeVisible();
  // the keyboard moves between questions
  const url = page.url();
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => page.url()).not.toBe(url);
  await expect(page.locator(".bubble.question")).toHaveCount(1);
});

test("a thread shows each tool's input and result, and the timeline tab shows the events", async ({ page }) => {
  await page.goto("/conversations");
  await page.locator(".q-card").filter({ hasText: "Do you have a Python book" }).first().click();
  await expect(page.getByText(/Step 1 of \d+/)).toBeVisible();
  await page.locator(".thread-tool-head").first().click();
  await expect(page.getByRole("heading", { name: "Input" }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Result" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Open tools" }).click();
  await expect(page.getByRole("button", { name: "Close tools" })).toBeVisible();
  await expect(page.locator(".bubble.answer").getByRole("button", { name: "Copy" })).toBeVisible();
  await page.getByRole("tab", { name: "Timeline" }).click();
  await expect(page.getByRole("tree", { name: "Spans of this run" })).toBeVisible();
});

test("a point on the overview line chart shows the question, its steps and tokens, and opens it", async ({ page }) => {
  await page.goto("/");
  const dots = page.locator(".steps-chart .chart-dot");
  await expect(dots.first()).toBeVisible();
  await expect(page.locator(".steps-chart .recharts-line")).toHaveCount(1);
  await dots.nth(3).hover({ force: true });
  const tip = page.locator(".peaks-tip");
  await expect(tip).toBeVisible();
  await expect(tip).toContainText(/Python|Eric Matthes|cheaper|cheapest/);
  await expect(tip).toContainText(/\d+ steps/);
  await expect(tip).toContainText(/Tokens.*\d+.*in · \d+.*out/);
  const asked = (await tip.locator("strong").first().innerText()).trim();
  await dots.nth(3).click({ force: true });
  await expect(page).toHaveURL(/\/conversations\?q=[0-9a-f]+/);
  await expect(page.locator(".bubble.question")).toContainText(asked);
});

test("the chart can show tokens instead of steps, and the keyboard opens a point", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("group", { name: "What the line shows" }).getByRole("button", { name: "Tokens" }).click();
  const chart = page.locator(".steps-chart");
  await chart.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".chart-focus .peaks-tip")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/conversations\?q=/);
});

test("latest questions are interactive and open their thread", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Latest questions" })).toBeVisible();
  const first = page.locator(".latest-q").first();
  await expect(first.locator(".latest-q-answer")).toBeVisible();
  await expect(first).toContainText(/tokens/);
  await first.hover();
  await first.click();
  await expect(page).toHaveURL(/\/conversations\?q=/);
});

test("one entry per model: the dated and the undated name are shown once, everywhere", async ({ page }) => {
  await page.goto("/");
  const rows = page.locator("section", { hasText: "Models used" }).locator("tbody tr");
  await expect(rows.filter({ hasText: "gpt-4o-mini" })).toHaveCount(1);
  await expect(page.locator("section", { hasText: "Models used" })).not.toContainText("2024-07-18");
  await page.goto("/models");
  await expect(page.locator(".gcard", { hasText: "gpt-4o-mini" })).toHaveCount(1);
  await expect(page.locator(".gcard", { hasText: "2024-07-18" })).toHaveCount(0);
});

test("the models page lists providers, usage, price and what each model can do", async ({ page }) => {
  await page.goto("/models");
  await expect(page.getByRole("heading", { name: "Models" })).toBeVisible();
  const mini = page.locator(".gcard", { hasText: "gpt-4o-mini" });
  await expect(mini).toContainText("openai");
  await expect(mini).toContainText("per 1M tokens");
  await expect(mini).toContainText(/tokens/);
  await expect(mini.locator(".sparkline")).toBeVisible();
  await expect(page.locator(".gcard", { hasText: "qwen2.5:7b" })).toContainText("free");
  await mini.click();
  await expect(page.getByRole("heading", { name: "How it was used", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^What it cost/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What it can do", exact: true })).toBeVisible();
  await expect(page).toHaveURL(/model=gpt-4o-mini/);
  await expect(page.getByText(/you used .* in \+ .* out =/)).toBeVisible();
  const chart = page.getByRole("img", { name: "Tokens in and out over time" });
  await expect(chart).toBeVisible();
  await expect(chart.locator(".recharts-line")).toHaveCount(2);
  await page.getByRole("button", { name: "Compare all models" }).click();
  await expect(page.getByRole("img", { name: "Tokens of every model over time" }).locator(".recharts-line")).toHaveCount(3);
  await detailed(page);
  await page.reload();
  await expect(page.getByText(/Names recorded: .*gpt-4o-mini-2024-07-18/)).toBeVisible();
});

test("the agents page draws each agent's steps, models and tools as a graph", async ({ page }) => {
  await page.goto("/agents");
  await expect(page.getByRole("heading", { name: "Agents" })).toBeVisible();
  const card = page.locator(".gcard", { hasText: "bookshop-agent" });
  await expect(card).toContainText("LangGraph");
  await expect(page.getByText(/How\s+bookshop-agent\s+works/)).toBeVisible();
  const graph = page.getByRole("group", { name: "Steps of the agent bookshop-agent" });
  await expect(graph.locator(".flow-node.step", { hasText: "agent" }).first()).toBeVisible();
  await expect(graph.locator(".flow-node.step", { hasText: "tools" }).first()).toBeVisible();
  await expect(graph.locator(".flow-node.model").first()).toBeVisible();
  await expect(graph.locator(".flow-node.tool", { hasText: "search_books" })).toBeVisible();
  await expect(graph.locator(".flow-node.mcp", { hasText: "bookshop" }).first()).toBeVisible();
  await expect(graph.locator(".react-flow__edge").first()).toBeAttached();
  // hovering a tool dims the boxes that are not on its path
  await graph.locator(".flow-node.tool", { hasText: "search_books" }).hover();
  await expect(graph.locator(".flow-node.dimmed").first()).toBeAttached();
  // clicking a box shows its details
  await graph.locator(".flow-node.model").first().click();
  await expect(page.getByRole("complementary", { name: /Details of/ })).toContainText("Used");
});

test("the MCPs page lists servers with their tools as cards and shows a tool's inputs in words", async ({ page }) => {
  await page.goto("/mcps?server=bookshop");
  await expect(page.getByRole("heading", { name: "MCPs" })).toBeVisible();
  await expect(page.locator(".gcard[data-server]")).not.toHaveCount(0);
  const tools = page.getByRole("list", { name: "Tools of bookshop" });
  await expect(tools.locator(".gcard", { hasText: "search_books" })).toBeVisible();
  await expect(tools.locator(".gcard", { hasText: "get_price_and_stock" })).toBeVisible();
  await page.getByLabel("Search tools").fill("price");
  await expect(tools.locator(".gcard")).toHaveCount(1);
  await tools.locator(".gcard").click();
  await expect(page.getByText("What you give it")).toBeVisible();
  await expect(page.getByText("How it is used")).toBeVisible();
  await page.getByLabel("Search tools").fill("");
  await page.getByRole("tab", { name: /Changes/ }).click();
  await expect(page.getByRole("heading", { name: "Has this MCP server changed?" })).toBeVisible();
});

test("the old tools page address still works and a tool name finds its server", async ({ page }) => {
  await page.goto("/servers");
  await expect(page).toHaveURL(/\/mcps/);
  await page.goto("/mcps?tool=close_ticket");
  await expect(page.getByRole("list", { name: "Tools of tickets" })).toBeVisible();
});

test("the glass look is on, and text stays readable (contrast of at least 4.5:1) in both themes", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".card").first()).toBeVisible();
  const blur = await page.locator(".card").first().evaluate((el) => getComputedStyle(el).backdropFilter);
  expect(blur).toContain("blur");
  const ratio = async () => page.evaluate(() => {
    const parse = (value: string) => (value.match(/[\d.]+/g) ?? []).map(Number);
    const mix = (top: number[], bottom: number[]) => { const a = top[3] ?? 1; return [0, 1, 2].map((i) => top[i] * a + bottom[i] * (1 - a)); };
    const luminance = (rgb: number[]) => { const [r, g, b] = rgb.map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const style = getComputedStyle(document.documentElement);
    const bg = parse(style.getPropertyValue("--bg")) ;
    const read = (name: string) => { const probe = document.createElement("i"); probe.style.color = `var(${name})`; document.body.append(probe); const value = parse(getComputedStyle(probe).color); probe.remove(); return value; };
    const panel = mix(read("--glass"), read("--bg"));
    const contrast = (text: number[]) => { const a = luminance(mix(text, panel)) + 0.05, b = luminance(panel) + 0.05; return Math.max(a, b) / Math.min(a, b); };
    void bg;
    return { text: contrast(read("--text")), muted: contrast(read("--muted")), accent: contrast(read("--accent")) };
  });
  for (const theme of ["dark", "light"]) {
    await page.evaluate((t) => { document.documentElement.dataset.theme = t; }, theme);
    const { text, muted, accent } = await ratio();
    expect(text, `${theme} text`).toBeGreaterThanOrEqual(4.5);
    expect(muted, `${theme} muted text`).toBeGreaterThanOrEqual(4.5);
    expect(accent, `${theme} links`).toBeGreaterThanOrEqual(4.5);
  }
});

test("less motion switches the animated arrows off", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/agents");
  const edge = page.locator(".react-flow__edge.flow-edge-animated .react-flow__edge-path").first();
  await page.locator(".flow-node.tool").first().hover();
  if (await edge.count()) expect(await edge.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
});

test("the layout fits a phone: no sideways scrolling of the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  for (const path of ["/", "/conversations", "/models", "/mcps"]) {
    await page.goto(path);
    await expect(page.locator(".content")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, path).toBeLessThanOrEqual(1);
  }
});

// ------------------------------------------------------------------------- steps, sides and tokens

test("a question shows you on the right and the AI on the left, and the two sides add up to its steps", async ({ page }) => {
  await page.goto("/conversations");
  await page.locator(".q-card").filter({ hasText: "What is the cheapest book you have?" }).first().click();
  const human = page.locator(".bubble-row.human");
  const ai = page.locator(".bubble-row.ai");
  await expect(human).toHaveCount(1);
  const aiCount = await ai.count();
  expect(aiCount).toBeGreaterThan(1);
  const box = async (locator: ReturnType<Page["locator"]>) => (await locator.boundingBox())!;
  expect((await box(human.locator(".bubble"))).x).toBeGreaterThan((await box(ai.first().locator(".bubble"))).x); // right vs left
  await expect(page.locator(".sides-total")).toHaveText(`${aiCount + 1} steps`);
  await expect(page.locator(".sides-end.ai strong")).toHaveText(String(aiCount));
  await expect(page.locator(".sides-end.human strong")).toHaveText("1");
  // every step shows its tokens: exact for the model, ≈ for your question and the tool results
  await expect(page.locator(".bubble.model .token-tag, .bubble.answer .token-tag").first()).toContainText(/tokens \(\d/);
  await expect(page.locator(".bubble.question .token-tag")).toContainText("≈");
  await expect(page.locator(".bubble.tool .token-tag").first()).toContainText("≈");
  await page.getByRole("button", { name: "By tokens" }).click();
  await expect(page.locator(".q-card.on")).toContainText(/\d+ steps/);
});

test("questions can be sorted by tokens and filtered with one click", async ({ page }) => {
  await page.goto("/conversations");
  await page.getByRole("button", { name: "Most tokens" }).click();
  await expect(page).toHaveURL(/sort=tokens/);
  const sizes = await page.locator(".q-card .badge.outline").allInnerTexts();
  const number = (text: string) => parseFloat(text) * (text.includes("k") ? 1000 : 1);
  expect(number(sizes[0])).toBeGreaterThanOrEqual(number(sizes[sizes.length - 1]));
  await page.getByRole("group", { name: "Quick filters" }).getByRole("button", { name: "gpt-4o-mini" }).click();
  await expect(page).toHaveURL(/filter=model/);
  const count = await page.locator(".q-card").count();
  expect(count).toBeGreaterThan(0);
  expect(count).toBeLessThan(35);
  await page.getByRole("group", { name: "Quick filters" }).getByRole("button", { name: /gpt-4o-mini/ }).click();
  await expect(page).not.toHaveURL(/filter=/);
});

test("the usage page shows tokens: total, trend, where they went and the warnings", async ({ page }) => {
  await page.goto("/spending");
  await expect(page.getByRole("button", { name: "Tokens" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".headline .big")).toContainText("tokens");
  await expect(page.getByRole("img", { name: "Tokens over time, coloured by model" })).toBeVisible();
  for (const tab of ["By model", "By agent", "By tool", "Heaviest questions"]) {
    await page.getByRole("tab", { name: tab }).click();
    await expect(page.locator(".share-row").first()).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: /Hidden overhead/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Heavy questions" })).toBeVisible();
  await page.locator(".share-row").first().click();
  await expect(page).toHaveURL(/\/conversations\?q=/);
  await page.goto("/spending");
  await page.getByRole("button", { name: "Dollars" }).click();
  await expect(page.getByText(/You spent/)).toBeVisible();
  await expect(page.locator(".share-row").first()).toContainText("tokens");
});

test("the daily token budget warns on the overview and in things to check", async ({ page }) => {
  // The test server runs with OBSERGENT_TOKEN_BUDGET=2000 (playwright.config.ts): today's tokens are far over it.
  await page.goto("/");
  await expect(page.locator(".budget-ring.over")).toBeVisible();
  await page.getByRole("list", { name: "Needs attention" }).getByText(/of today's token budget/).click();
  await expect(page).toHaveURL(/view=tokens/);
  await expect(page.locator(".budget-bar.over")).toBeVisible();
  await page.goto("/findings");
  await expect(page.locator(".finding strong", { hasText: "Today's tokens are close to your budget" })).toBeVisible();
});

test("tokens are shown wherever a model appears", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("section", { hasText: "Models used" }).getByRole("columnheader", { name: "Tokens" })).toBeVisible();
  await page.goto("/agents");
  await expect(page.locator(".gcard", { hasText: "bookshop-agent" })).toContainText("tokens");
  await expect(page.locator(".flow-node.model").first()).toContainText("tokens");
  await page.goto("/conversations");
  await page.locator(".summary-big").getByText("Tokens").isVisible();
  await page.locator(".thread-side .badge.model").first().hover();
  await expect(page.locator(".hovercard").first()).toContainText(/tokens · \d+ calls/);
});

test("the word 'exchanges' is gone and every page header is short", async ({ page }) => {
  for (const path of ["/", "/conversations", "/agents", "/mcps", "/models", "/spending", "/findings", "/gateway", "/map", "/about"]) {
    await page.goto(path);
    await expect(page.locator(".page-head h1")).toBeVisible();
    const header = `${await page.locator(".page-head").innerText()} ${await page.locator(".page-about").innerText()}`;
    expect(header.split(/\s+/).filter(Boolean).length, path).toBeLessThanOrEqual(15);
    expect(await page.locator("body").innerText(), path).not.toMatch(/exchanges?/i);
  }
});

test("the welcome tour runs once on the first visit and can be skipped", async ({ page }) => {
  await page.addInitScript(() => { sessionStorage.setItem("tour-test", "1"); localStorage.removeItem("obsergent.tour"); });
  await page.goto("/");
  const tour = page.getByRole("dialog", { name: "Welcome tour" });
  await expect(tour).toContainText("Every point is a question");
  await tour.getByRole("button", { name: "Next" }).click();
  await expect(tour).toContainText("Your latest questions");
  await tour.getByRole("button", { name: "Skip" }).click();
  await expect(tour).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("obsergent.tour"))).toBe("done");
});

test("the ? key shows the shortcuts, and numbers do not animate when less motion is asked", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator(".tile").filter({ hasText: "Discussions" })).toContainText("35"); // shown at once, no count-up
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toContainText("Usage & cost");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toHaveCount(0);
});
