// The two sides of a question: what you typed (human) and what the AI side did (model replies and tools), adding up to its steps.
import { Bot, User, Wrench } from "lucide-react";

/** A round icon for a side: you (blue), the AI (teal) or a tool (violet). */
export function SideIcon({ side, size = 14 }: { side: "human" | "ai" | "tool"; size?: number }) {
  const Icon = side === "human" ? User : side === "ai" ? Bot : Wrench;
  const label = side === "human" ? "You" : side === "ai" ? "AI" : "Tool";
  return <span className={`side-icon ${side}`} role="img" aria-label={label} title={label}><Icon size={size} aria-hidden /></span>;
}

/** "🧑 1 · 🤖 6 · 7 steps" with icons. `compact` drops the word "steps". */
export function SideCounts({ human, ai, compact = false }: { human: number; ai: number; compact?: boolean }) {
  return (
    <span className="side-counts" aria-label={`${human + ai} steps: ${human} from you, ${ai} from the AI`}>
      <span className="side-count" title="Your messages"><SideIcon side="human" size={11} />{human}</span>
      <span className="side-count" title="AI messages: model replies and tools"><SideIcon side="ai" size={11} />{ai}</span>
      {!compact && <span className="side-total">{human + ai} steps</span>}
    </span>
  );
}
