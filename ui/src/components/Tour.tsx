// A three-step welcome tour on the first visit: it points at the chart, a question and the Usage page. Skippable and remembered.
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

const KEY = "obsergent.tour";
const STOPS = [
  { target: '[data-tour="chart"]', title: "Every point is a question", text: "Hover to see its steps, tokens and cost. Click to open it." },
  { target: '[data-tour="question"]', title: "Your latest questions", text: "Open one to read it step by step: you on the right, the AI on the left." },
  { target: '.nav-link[data-nav="Usage & cost"]', title: "Watch your tokens", text: "See where tokens and dollars go, and set a daily budget." },
];

function done(): boolean {
  try { return localStorage.getItem(KEY) === "done"; } catch { return true; }
}

export function Tour() {
  const location = useLocation();
  const [stop, setStop] = useState<number | null>(null);
  const [box, setBox] = useState<DOMRect | null>(null);
  // Start on the Overview once its chart is on screen.
  useEffect(() => {
    if (done() || location.pathname !== "/" || stop !== null) return;
    const timer = setInterval(() => { if (document.querySelector(STOPS[0].target)) { setStop(0); clearInterval(timer); } }, 400);
    return () => clearInterval(timer);
  }, [location.pathname, stop]);
  // Follow the element of the current stop.
  useEffect(() => {
    if (stop === null) return;
    const element = document.querySelector(STOPS[stop].target);
    element?.scrollIntoView({ block: "center", behavior: "smooth" });
    const measure = () => setBox(element?.getBoundingClientRect() ?? null);
    measure();
    const timer = setInterval(measure, 250);
    return () => clearInterval(timer);
  }, [stop]);
  if (stop === null) return null;
  const finish = () => { try { localStorage.setItem(KEY, "done"); } catch { /* storage blocked: the tour may show again */ } setStop(null); };
  const current = STOPS[stop];
  const top = box ? Math.min(window.innerHeight - 170, box.bottom + 12) : window.innerHeight / 3;
  const left = box ? Math.max(12, Math.min(window.innerWidth - 332, box.left)) : 24;
  return (
    <div className="tour" role="dialog" aria-label="Welcome tour">
      {box && <div className="tour-spot" style={{ top: box.top - 6, left: box.left - 6, width: box.width + 12, height: box.height + 12 }} />}
      <div className="tour-card" style={{ top, left }}>
        <div className="muted" style={{ fontSize: 12 }}>{stop + 1} of {STOPS.length}</div>
        <strong>{current.title}</strong>
        <p>{current.text}</p>
        <div className="row spread">
          <button className="small ghost" onClick={finish}>Skip</button>
          <button className="small primary" onClick={() => (stop + 1 < STOPS.length ? setStop(stop + 1) : finish())}>{stop + 1 < STOPS.length ? "Next" : "Done"}</button>
        </div>
      </div>
    </div>
  );
}
