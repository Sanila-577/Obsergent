/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The AgentTrace server the dev server forwards API calls to (change with AGENTTRACE_API=http://host:port).
const api = process.env.AGENTTRACE_API ?? "http://127.0.0.1:7318";

export default defineConfig({
  plugins: [react()],
  // `npm run build` writes straight into the Python package, so `agenttrace up` serves the UI.
  build: { outDir: "../src/agenttrace/server/static", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": api, "/v1": api, "/health": api },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});
