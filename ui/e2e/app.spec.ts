import { expect, test } from "@playwright/test";

// Every test starts from the same seeded data: ~48 runs (agent runs and gateway calls), a loop, a drifting server.

test("the overview shows the numbers, the chart and the slowest tools", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Tool calls", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("img", { name: "Tool calls over time" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Slowest tools (p95)" })).toBeVisible();
  await expect(page.getByText("Refused by gateway")).toBeVisible();
});

test("find the slowest tool and see its runs in a few clicks", async ({ page }) => {
  await page.goto("/");
  const slowest = page.locator("section", { hasText: "Slowest tools (p95)" }).locator("tbody tr").first();
  const tool = (await slowest.locator("a").innerText()).trim();
  await slowest.locator("a").click();
  await expect(page).toHaveURL(new RegExp(`tool=${tool}`));
  await expect(page.locator("tbody tr").first()).toContainText(/tools\/call|agent\.run|BookshopMCP|tickets/);
});

test("runs can be filtered, and the filter lives in the URL", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.locator("tbody tr").first()).toBeVisible(); // wait for the table before counting its rows
  const all = await page.locator("tbody tr").count();
  expect(all).toBeGreaterThan(10);
  await page.getByLabel("Errors only").check();
  await expect(page).toHaveURL(/errors_only=1/);
  await expect.poll(() => page.locator("tbody tr").count()).toBeLessThan(all);
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect.poll(() => page.locator("tbody tr").count()).toBe(all);
  await page.getByLabel("Gateway decision").selectOption("forbidden");
  await expect(page.locator("tbody .badge.forbidden").first()).toBeVisible(); // a row with that gateway decision
  await expect(page.locator("tbody tr")).not.toHaveCount(all);
  await page.goto("/runs?q=zzz-nothing-matches");
  await expect(page.getByText("No runs match these filters")).toBeVisible();
});

test("a run opens as a timeline with an inspector, keyboard navigation and copy-as-curl", async ({ page }) => {
  await page.goto("/runs?tool=get_price_and_stock&server=bookshop");
  await page.locator("tbody tr").first().click();
  await expect(page.getByRole("tree", { name: "Spans of this run" })).toBeVisible();
  await expect(page.getByText("Pick a span")).toBeVisible();
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
  await page.goto("/runs?service=bookshop-agent");
  await page.locator("tbody tr").first().click();
  await page.getByRole("tab", { name: "Conversation" }).click();
  await expect(page.getByText("You are a helpful bookshop assistant")).toBeVisible();
  await page.getByRole("link", { name: "View the MCP call" }).first().click();
  await expect(page).toHaveURL(/span=/);
  await expect(page.getByRole("treeitem", { selected: true })).toContainText("tools/call");
});

test("findings can be dismissed and brought back", async ({ page }) => {
  await page.goto("/findings");
  await expect(page.locator(".finding strong", { hasText: "tool description changed" })).toBeVisible();
  await expect(page.locator(".finding strong", { hasText: /^loop$/ })).toBeVisible();
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
  await expect(page.getByRole("heading", { name: "Version history of the tool list" })).toBeVisible();
  await expect(page.locator(".diff ins").first()).toContainText("Ignore previous instructions");
  await page.getByLabel("Compare with").selectOption("bookshop-upstream");
  await expect(page.getByText("Only in bookshop-upstream").or(page.getByText("Only in tickets")).first()).toBeVisible();
});

test("the gateway page explains what the gateway decided and where time went", async ({ page }) => {
  await page.goto("/gateway");
  await expect(page.getByText("Gateway telemetry is arriving")).toBeVisible();
  await expect(page.locator(".tile", { hasText: "allowed" })).toBeVisible();
  await expect(page.locator(".tile", { hasText: "forbidden" })).toBeVisible();
  await expect(page.getByText("Where the gateway spends its time")).toBeVisible();
  await page.locator("section", { hasText: "Latest calls through the gateway" }).locator("tbody tr.click").first().click();
  await expect(page.getByText("Activity id").first()).toBeVisible();
  await expect(page.getByText("Access-control assistant")).toBeVisible();
  await page.getByLabel("Server", { exact: true }).selectOption("bookshop");
  await expect(page.getByText("Policy parameters")).toBeVisible();
  await expect(page.locator("pre.code").last()).toContainText('"mode": "deny"');
});

test("the map draws who calls what and a click filters the runs", async ({ page }) => {
  await page.goto("/map");
  await expect(page.getByLabel("MCP topology graph")).toBeVisible();
  await expect(page.getByText("via gateway")).toBeVisible();
  await page.locator(".map-node.server", { hasText: "tickets" }).click();
  await expect(page).toHaveURL(/runs\?server=tickets/);
});

test("two runs can be compared, and the first difference is pointed out", async ({ page }) => {
  await page.goto("/runs?service=bookshop-agent");
  const boxes = page.getByRole("checkbox", { name: /Select .* to compare/ });
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await page.getByRole("button", { name: "Compare 2 runs" }).click();
  await expect(page).toHaveURL(/compare\?a=.*&b=/);
  await expect(page.getByText(/Both runs made the same|diverged at step/)).toBeVisible();
});

test("sessions group an app's calls into a timeline", async ({ page }) => {
  await page.goto("/sessions");
  await page.locator("tbody tr").first().click();
  await expect(page.getByRole("heading", { name: "Session timeline" })).toBeVisible();
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
