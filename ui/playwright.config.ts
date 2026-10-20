import { defineConfig } from "@playwright/test";

// The browser tests run against the REAL server serving the built UI, on a freshly seeded database.
// Needs the Python environment of the repository (override with OBSERGENT_PYTHON).
const python = process.env.OBSERGENT_PYTHON ?? "../.venv/bin/python";
const port = 7399;
const db = ".e2e/e2e.db";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false, // the tests share one database, and some of them change it (dismissing findings)
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" },
  webServer: {
    command: `npm run build && rm -rf .e2e && mkdir -p .e2e && OBSERGENT_DB=${db} ${python} e2e/seed_test_db.py && `
      + `OBSERGENT_DB=${db} OBSERGENT_PORT=${port} OBSERGENT_TOKEN_BUDGET=2000 ${python} -m obsergent.cli up`,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
