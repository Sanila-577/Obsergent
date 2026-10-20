// The `?` sheet: every keyboard shortcut on one card.
import { X } from "lucide-react";

const SHORTCUTS: [string[], string][] = [
  [["⌘", "K"], "Search anything"],
  [["g", "o"], "Overview"], [["g", "c"], "Conversations"], [["g", "a"], "Agents"], [["g", "m"], "MCPs"],
  [["g", "d"], "Models"], [["g", "s"], "Usage & cost"], [["g", "f"], "Things to check"], [["g", "n"], "Connections"],
  [["←", "→"], "Previous / next question (or chart point)"], [["Enter"], "Open the highlighted point"],
  [["j", "k"], "Next / previous event in a timeline"], [["Esc"], "Close"], [["?"], "This sheet"],
];

export function ShortcutSheet({ onClose }: { onClose: () => void }) {
  return (
    <div className="palette-overlay" onMouseDown={onClose} role="dialog" aria-label="Keyboard shortcuts" onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <div className="palette sheet" onMouseDown={(e) => e.stopPropagation()}>
        <div className="row spread"><h2 style={{ margin: 0 }}>Shortcuts</h2><button className="icon ghost" onClick={onClose} aria-label="Close" autoFocus><X size={16} /></button></div>
        <dl className="sheet-list">{SHORTCUTS.map(([keys, what]) => (
          <div key={what}><dt>{keys.map((key) => <kbd key={key}>{key}</kbd>)}</dt><dd>{what}</dd></div>))}</dl>
      </div>
    </div>
  );
}
