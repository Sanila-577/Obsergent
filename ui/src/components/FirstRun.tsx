// Shown instead of an empty page: three steps to get data, and a live "waiting" light that becomes the data itself.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "../api/client";
import { CopyButton } from "./ui";

const WHAT: Record<string, string> = {
  runs: "conversations", sessions: "app activity", servers: "tools", gateway: "gateway activity", map: "connections",
  spending: "spending", overview: "activity",
};

export function FirstRun({ kind, title }: { kind: keyof typeof WHAT; title?: string }) {
  const client = useQueryClient();
  // Look for the first data every 3 seconds; when it arrives, every page reloads its data.
  const waiting = useQuery({ queryKey: ["first-run"], queryFn: () => api.overview(24 * 30), refetchInterval: 3000 });
  const arrived = (waiting.data?.counts.spans ?? 0) > 0;
  useEffect(() => { if (arrived) client.invalidateQueries(); }, [arrived, client]);
  const run = 'cd examples/bookshop\npython agent.py "Do you have a Python book in stock?"';
  return (
    <div className="first-run">
      <h3>{title ?? `No ${WHAT[kind]} yet`}</h3>
      <p className="muted">Three steps and this page fills itself:</p>
      <ol>
        <li><strong>The server is running</strong> <span className="badge ok">you are here</span></li>
        <li><strong>Run your agent or app</strong> so it reports to AgentTrace. For the example agent:
          <pre className="code mono">{run}</pre><CopyButton text={run} label="Copy" /></li>
        <li><strong>Watch it appear.</strong> This page checks every few seconds.</li>
      </ol>
      <p className={`waiting ${arrived ? "ok" : ""}`}><span className="live-dot on" /> {arrived ? "Data arrived! Loading it…" : "Waiting for the first data…"}</p>
    </div>
  );
}
