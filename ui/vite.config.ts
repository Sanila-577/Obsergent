/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Obsergent server the dev server forwards API calls to (change with OBSERGENT_API=http://host:port).
const api = process.env.OBSERGENT_API ?? "http://127.0.0.1:7318";

export default defineConfig({
  plugins: [react()],
  // `npm run build` writes straight into the Python package, so `obsergent up` serves the UI.
  build: { outDir: "../src/obsergent/server/static", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": api, "/v1": api, "/health": api },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});
