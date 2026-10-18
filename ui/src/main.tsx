// React Query fetches and caches the data from the API.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
// StrictMode adds extra development-time checks.
import { StrictMode } from "react";
// createRoot attaches React to the page.
import { createRoot } from "react-dom/client";
// The router maps URLs (/runs, /gateway...) to pages.
import { BrowserRouter } from "react-router-dom";
// The app's route table.
import { App } from "./App";
// Shares live/hours/theme settings with all pages.
import { SettingsProvider } from "./lib/state";
// The stylesheet.
import "./styles.css";

// Data is cheap to refetch from a local server: keep it fresh, but don't retry failed calls for long.
// The shared data cache.
const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } } });

// Find <div id="root"> in index.html and draw the app inside it.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SettingsProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </SettingsProvider>
    </QueryClientProvider>
  </StrictMode>,
);
