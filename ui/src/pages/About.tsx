// What Obsergent is, in one minute: two sentences, a flow you can click through, and where to go next.
import { Bot, Gauge, Keyboard, LayoutDashboard, Server } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Logo } from "../components/Logo";
import { Card, PageHead } from "../components/ui";
import { PAGES } from "../lib/words";

// The four stops of the flow; clicking one explains it and lights up where it appears in the menu.
const STEPS = [
  { id: "agent", icon: Bot, title: "Your agent", text: "Any AI agent or app that uses tools. Obsergent's small add-on records every model call and every tool it uses.", menu: "Agents" },
  { id: "recorder", icon: Gauge, title: "The recorder", text: "A proxy sits between the agent and its tools and writes down each request and answer, without changing your code. Secrets are hidden first.", menu: "App activity" },
  { id: "tools", icon: Server, title: "MCP servers and the gateway", text: "The tools themselves. If you use an API gateway such as WSO2, Obsergent also shows what it allowed or blocked and how long it took.", menu: "MCPs" },
  { id: "dashboard", icon: LayoutDashboard, title: "This dashboard", text: "Everything is kept in one file on your computer and shown here. Nothing leaves your machine, and nothing is sent to anyone.", menu: "Overview" },
] as const;

const DOORS = [
  { to: "/conversations", title: "Read what was asked", text: "Every question and the full thread behind it." },
  { to: "/agents", title: "See how an agent works", text: "Its steps, models and tools as a graph." },
  { to: "/spending", title: "Watch the cost", text: "What each model and question cost, in dollars." },
  { to: "/findings", title: "Catch problems early", text: "Loops, failures, risky or changed tools, blocked calls." },
] as const;

export function About() {
  const [step, setStep] = useState<(typeof STEPS)[number]["id"]>("agent");
  const current = STEPS.find((s) => s.id === step)!;
  // Light up the menu entry that belongs to the chosen step.
  useEffect(() => {
    const link = document.querySelector(`.nav-link[data-nav="${current.menu}"]`);
    link?.classList.add("lit");
    return () => link?.classList.remove("lit");
  }, [current.menu]);
  return (
    <>
      <PageHead title={PAGES.about.title} about={PAGES.about.about} help={PAGES.about.help} />
      <div className="col" style={{ maxWidth: 980, gap: 18 }}>
        <Card>
          <div className="about-hero">
            <Logo size={64} draw />
            <div style={{ flex: 1, minWidth: 260 }}>
              <h2 style={{ fontSize: 22, margin: "0 0 6px" }}>What is Obsergent?</h2>
              <p style={{ margin: 0, fontSize: 15.5 }}>Obsergent is a flight recorder for AI agents. It watches what your agents ask, which tools they use and what it costs, and warns you when something looks wrong.</p>
            </div>
          </div>
        </Card>

        <div>
          <h3>How it works: click a step</h3>
          <div className="about-flow" role="tablist" aria-label="How Obsergent works">
            {STEPS.map(({ id, icon: Icon, title }, index) => (
              <div key={id} className="about-flow-item">
                <button role="tab" aria-selected={id === step} className={`about-step${id === step ? " on" : ""}`} onClick={() => setStep(id)}><Icon size={22} /><span>{title}</span></button>
                {index < STEPS.length - 1 && <span className="about-arrow" aria-hidden>→</span>}
              </div>
            ))}
          </div>
          <Card><div role="tabpanel"><strong>{current.title}.</strong> {current.text} <span className="muted">Find it in the menu: <span className="badge accent">{current.menu}</span></span></div></Card>
        </div>

        <div>
          <h3>What you can do</h3>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
            {DOORS.map((door) => <Link key={door.to} to={door.to} className="gcard door"><strong>{door.title}</strong><span className="muted">{door.text}</span></Link>)}
          </div>
        </div>

        <Card title={<span className="row"><Keyboard size={16} /> Shortcuts</span>}>
          <dl className="kv" style={{ gridTemplateColumns: "190px 1fr" }}>
            <dt><kbd>⌘</kbd> <kbd>K</kbd></dt><dd>Search pages, questions, agents, models and tools</dd>
            <dt><kbd>g</kbd> then <kbd>o c a m d s</kbd></dt><dd>Go to Overview, Conversations, Agents, MCPs, Models, Spending</dd>
            <dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>Previous / next question on the Conversations page</dd>
            <dt><kbd>j</kbd> / <kbd>k</kbd></dt><dd>Next / previous step in a timeline</dd>
          </dl>
        </Card>
      </div>
    </>
  );
}
