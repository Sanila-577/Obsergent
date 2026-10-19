import { expect, test, type Page } from "@playwright/test";

test("the spending page says what the models cost and lets you dig in", async ({ page }) => {
  await page.goto("/spending");
  await expect(page.getByRole("heading", { name: "Spending" })).toBeVisible();
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
  await page.goto("/spending");
  await expect(page.getByText(/of this amount was reported by the provider/)).toBeVisible();
  await page.goto("/runs?model=openai/gpt-4o-mini");
  await expect(page.locator("tbody tr").first()).toContainText("$0.04"); // 3 model calls x $0.0123, reported by the provider
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
  await page.addInitScript(() => localStorage.setItem("agenttrace.detailed", "true"));
}

// Every test starts from the same seeded data: ~48 runs (agent runs and gateway calls), a loop, a drifting server.

test("the overview shows the numbers, the chart and the slowest tools", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Actions used", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("img", { name: "Actions over time" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Slowest actions (p95)" })).toBeVisible();
  await expect(page.getByText("Blocked by the gateway")).toBeVisible();
});

test("find the slowest tool and see its runs in a few clicks", async ({ page }) => {
  await page.goto("/");
  const slowest = page.locator("section", { hasText: "Slowest actions (p95)" }).locator("tbody tr").first();
  const tool = (await slowest.locator("a").innerText()).trim();
  await slowest.locator("a").click();
  await expect(page).toHaveURL(new RegExp(`tool=${tool}`));
  await expect(page.locator("tbody tr").first()).toBeVisible();
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

test("a server's changed tool description is shown word by word", async ({ page }) => {
  await page.goto("/servers?server=tickets");
  await expect(page.getByRole("heading", { name: "Has this tool server changed?" })).toBeVisible();
  await expect(page.locator(".diff ins").first()).toContainText("Ignore previous instructions");
  await page.getByLabel("Compare with").selectOption("bookshop-upstream");
  await expect(page.getByText("Only in bookshop-upstream").or(page.getByText("Only in tickets")).first()).toBeVisible();
});

test("the gateway page explains what the gateway decided and where time went", async ({ page }) => {
  await detailed(page);
  await page.goto("/gateway");
  await expect(page.getByText("The gateway is reporting to AgentTrace")).toBeVisible();
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

test("the map draws who calls what and a click filters the runs", async ({ page }) => {
  await page.goto("/map");
  await expect(page.getByLabel("Connections between apps, tool servers and tools")).toBeVisible();
  await expect(page.getByText("via gateway")).toBeVisible();
  await page.locator(".map-node.server", { hasText: "tickets" }).click();
  await expect(page).toHaveURL(/runs\?server=tickets/);
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
  await page.keyboard.press("m");
  await expect(page).toHaveURL(/\/map/);
});

test("settings stay after a reload: theme, live tail and time window", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Switch theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Live" }).click();
  await page.getByRole("button", { name: "7d" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Live" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "7d" })).toHaveAttribute("aria-pressed", "true");
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

test("the about page states how AgentTrace differs from Langfuse", async ({ page }) => {
  await page.goto("/about");
  await expect(page.getByRole("heading", { name: "AgentTrace vs Langfuse" })).toBeVisible();
  await expect(page.getByText("Prompt management, evaluations, datasets, scores")).toBeVisible();
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
  await expect(page.locator(".help-bubble").first()).toBeVisible();
});
