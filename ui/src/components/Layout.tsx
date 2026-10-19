// The frame around every page: navigation rail on the left, a top bar with the global controls.
// useQuery loads data from the API and keeps it fresh.
import { useQuery } from "@tanstack/react-query";
// Icons.
import { Activity, GitCompare, Info, LayoutDashboard, MessagesSquare, Moon, Wallet, Network, Radio, Search, ShieldAlert, Sun, Waypoints, Wrench } from "lucide-react";
// State and side-effect hooks.
import { useEffect, useState } from "react";
// Router pieces: links, the slot where the current page appears, and navigate().
import { NavLink, Outlet, useNavigate } from "react-router-dom";
// The API functions.
import { api } from "../api/client";
// Shared settings.
import { useSettings } from "../lib/state";
// The Ctrl/Cmd+K search box.
import { CommandPalette } from "./CommandPalette";
// The 1h/6h/24h/7d switch.
import { PAGES } from "../lib/words";
import { Segmented } from "./ui";

// The left menu: URL, label and icon.
const NAV = [
  { to: "/", label: PAGES.overview.title, icon: LayoutDashboard, end: true },
  { to: "/runs", label: PAGES.runs.title, icon: Activity },
  { to: "/sessions", label: PAGES.sessions.title, icon: MessagesSquare },
  { to: "/servers", label: PAGES.servers.title, icon: Wrench },
  { to: "/spending", label: PAGES.spending.title, icon: Wallet },
  { to: "/findings", label: PAGES.findings.title, icon: ShieldAlert, badge: true },
  { to: "/gateway", label: PAGES.gateway.title, icon: Network },
  { to: "/map", label: PAGES.map.title, icon: Waypoints },
  { to: "/compare", label: PAGES.compare.title, icon: GitCompare },
  { to: "/about", label: PAGES.about.title, icon: Info },
];

// "g" then a letter jumps to a page (like GitHub). Ignored while typing in a field.
const GO_KEYS: Record<string, string> = { o: "/", r: "/runs", s: "/sessions", t: "/servers", f: "/findings", w: "/gateway", m: "/map" };

// The frame around every page; <Outlet/> is where the page goes.
export function Layout() {
  // Read the shared settings.
  const { live, setLive, hours, setHours, theme, setTheme, detailed, setDetailed } = useSettings();
  // Function that changes the URL.
  const navigate = useNavigate();
  // Is the search box open?
  const [palette, setPalette] = useState(false);
  // Ask /health every 10 s to show "server connected".
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 10_000, retry: false });
  // Overview numbers (for the Findings badge); refresh faster in live mode.
  const overview = useQuery({ queryKey: ["overview", hours], queryFn: () => api.overview(hours), refetchInterval: live ? 2000 : 30_000 });

  // { => Install the keyboard shortcuts once.
  useEffect(() => {
    // True right after "g" was pressed.
    let waitingForSecondKey = false;
    // Runs on every key press.
    const onKey = (event: KeyboardEvent) => {
      // Ignore shortcuts while the user types in a field.
      const typing = ["INPUT", "SELECT", "TEXTAREA"].includes((event.target as HTMLElement).tagName);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        // Stop the browser's own Ctrl+K action.
        event.preventDefault();
        setPalette((open) => !open);
      } else if (!typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        if (waitingForSecondKey && GO_KEYS[event.key]) navigate(GO_KEYS[event.key]);
        waitingForSecondKey = event.key === "g";
      }
    };
    // Start listening.
    window.addEventListener("keydown", onKey);
    // window.removeEventListener => Cleanup when the component goes away.
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  // Number of open findings for the badge.
  const open = overview.data?.open_findings ?? 0;
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand"><svg width="22" height="22" viewBox="0 0 32 32"><path d="M4 20h6l4-11 5 17 4-11h5" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>AgentTrace</div>
        {NAV.map(({ to, label, icon: Icon, end, badge }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <Icon size={17} />{label}
            {badge && open > 0 && <span className="nav-badge" aria-label={`${open} things to check`}>{open}</span>}
          </NavLink>
        ))}
        <div className="rail-foot">
          <div className="row"><span className={`dot`} style={{ background: health.isError ? "var(--bad)" : "var(--ok)" }} />{health.isError ? "server unreachable" : "server connected"}</div>
          <div style={{ marginTop: 6 }}><kbd>⌘K</kbd> search · <kbd>g</kbd> <kbd>r</kbd> go to</div>
        </div>
      </nav>
      <div className="main">
        <header className="topbar">
          <button onClick={() => setPalette(true)} aria-label="Open command palette"><Search size={14} /> Search <kbd>⌘K</kbd></button>
          <div className="grow" />
          <Segmented value={detailed ? "detailed" : "simple"} onChange={(mode) => setDetailed(mode === "detailed")}
            options={[{ id: "simple", label: "Simple" }, { id: "detailed", label: "Detailed" }]} />
          <Segmented value={hours} onChange={setHours} options={[{ id: 1, label: "1h" }, { id: 6, label: "6h" }, { id: 24, label: "24h" }, { id: 168, label: "7d" }]} />
          <button onClick={() => setLive(!live)} aria-pressed={live} title="Refresh every 2 seconds"><span className={`live-dot${live ? " on" : ""}`} /><Radio size={14} /> Live</button>
          <button className="icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Switch theme">{theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}</button>
        </header>
        <main className="content"><Outlet /></main>
      </div>
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
    </div>
  );
}
