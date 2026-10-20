// The frame around every page: navigation rail on the left, a top bar with the global controls.
// useQuery loads data from the API and keeps it fresh.
import { useQuery } from "@tanstack/react-query";
// Icons.
import { Activity, Bot, ChevronDown, Cpu, GitCompare, Info, Keyboard, LayoutDashboard, List, MessagesSquare, Moon, Network, Plug, Radio, Search, ShieldAlert, Sun, Wallet, Waypoints } from "lucide-react";
// State and side-effect hooks.
import { useEffect, useState } from "react";
// Router pieces: links, the slot where the current page appears, and navigate().
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
// The API functions.
import { api } from "../api/client";
// Shared settings.
import { useSettings } from "../lib/state";
// The Ctrl/Cmd+K search box.
import { CommandPalette } from "./CommandPalette";
import { Logo } from "./Logo";
import { ShortcutSheet } from "./ShortcutSheet";
import { Tour } from "./Tour";
// The 1h/6h/24h/7d switch.
import { PAGES } from "../lib/words";
import { Segmented } from "./ui";

// The left menu: URL, label and icon.
const NAV = [
  { group: "Ask & answer", items: [
    { to: "/", label: PAGES.overview.title, icon: LayoutDashboard, end: true },
    { to: "/conversations", label: PAGES.conversations.title, icon: MessagesSquare },
    { to: "/agents", label: PAGES.agents.title, icon: Bot },
  ] },
  { group: "Tools & models", items: [
    { to: "/mcps", label: PAGES.mcps.title, icon: Plug },
    { to: "/models", label: PAGES.models.title, icon: Cpu },
    { to: "/spending", label: PAGES.spending.title, icon: Wallet },
  ] },
  { group: "Safety", items: [
    { to: "/findings", label: PAGES.findings.title, icon: ShieldAlert, badge: true },
    { to: "/gateway", label: PAGES.gateway.title, icon: Network },
    { to: "/map", label: PAGES.map.title, icon: Waypoints },
  ] },
  { group: "More", collapsible: true, items: [
    { to: "/sessions", label: PAGES.sessions.title, icon: Activity },
    { to: "/runs", label: PAGES.runs.title, icon: List, detailedOnly: true },
    { to: "/compare", label: PAGES.compare.title, icon: GitCompare },
    { to: "/about", label: PAGES.about.title, icon: Info },
  ] },
];
const MORE_PATHS = ["/sessions", "/runs", "/compare", "/about"];

// "g" then a letter jumps to a page (like GitHub). Ignored while typing in a field.
const GO_KEYS: Record<string, string> = { o: "/", c: "/conversations", a: "/agents", m: "/mcps", d: "/models", s: "/spending", f: "/findings", w: "/gateway", n: "/map", r: "/runs" };

// The frame around every page; <Outlet/> is where the page goes.
export function Layout() {
  // Read the shared settings.
  const { live, setLive, hours, setHours, theme, setTheme, detailed, setDetailed } = useSettings();
  // Function that changes the URL.
  const navigate = useNavigate();
  // Is the search box open? The shortcut sheet? The "More" group of the menu?
  const [palette, setPalette] = useState(false);
  const [sheet, setSheet] = useState(false);
  const location = useLocation();
  const [more, setMore] = useState(() => MORE_PATHS.some((path) => location.pathname.startsWith(path)));
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
      } else if (!typing && event.key === "?") {
        setSheet((open) => !open);
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
  const openFindings = overview.data?.open_findings ?? 0;
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand"><Logo size={26} />Obsergent</div>
        {NAV.map(({ group, items, collapsible }) => {
          const shown = items.filter((item) => !("detailedOnly" in item && item.detailedOnly) || detailed);
          const open = !collapsible || more;
          return (
            <div key={group} className="nav-group">
              {collapsible ? <button className="nav-heading toggle" aria-expanded={open} onClick={() => setMore(!more)}>{group}<ChevronDown size={13} className={open ? "turned" : ""} /></button>
                : <div className="nav-heading">{group}</div>}
              {open && shown.map(({ to, label, icon: Icon, ...rest }) => (
                <NavLink key={to} to={to} end={"end" in rest ? rest.end : undefined} data-nav={label} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
                  <Icon size={17} />{label}
                  {"badge" in rest && rest.badge && openFindings > 0 && <span className="nav-badge" aria-label={`${openFindings} things to check`}>{openFindings}</span>}
                </NavLink>
              ))}
            </div>
          );
        })}
        <div className="rail-foot">
          <div className="row"><span className={`dot`} style={{ background: health.isError ? "var(--bad)" : "var(--ok)" }} />{health.isError ? "server unreachable" : "server connected"}</div>
          <div style={{ marginTop: 6 }}><kbd>⌘K</kbd> search · <button className="link-button" onClick={() => setSheet(true)}><Keyboard size={12} /> <kbd>?</kbd> shortcuts</button></div>
        </div>
      </nav>
      <div className="main">
        <header className="topbar">
          <button onClick={() => setPalette(true)} aria-label="Open command palette"><Search size={14} /> Search <kbd>⌘K</kbd></button>
          <div className="grow" />
          <Segmented value={detailed ? "detailed" : "simple"} onChange={(mode) => setDetailed(mode === "detailed")}
            options={[{ id: "simple", label: "Simple" }, { id: "detailed", label: "Detailed" }]} />
          <Segmented value={hours} onChange={setHours} options={[{ id: 1, label: "Last hour" }, { id: 24, label: "Today" }, { id: 168, label: "7 days" }]} />
          <button onClick={() => setLive(!live)} aria-pressed={live} title="Refresh every 2 seconds"><span className={`live-dot${live ? " on" : ""}`} /><Radio size={14} /> Live</button>
          <button className="icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Switch theme">{theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}</button>
        </header>
        <main className="content"><Outlet /></main>
      </div>
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
      {sheet && <ShortcutSheet onClose={() => setSheet(false)} />}
      <Tour />
    </div>
  );
}
