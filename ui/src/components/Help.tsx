// A small (?) bubble that explains a word in plain language. Works with the mouse (hover) and the keyboard (focus).
import { CircleHelp } from "lucide-react";
import { HELP } from "../lib/words";

export function Help({ topic, text }: { topic?: keyof typeof HELP; text?: string }) {
  const message = text ?? (topic ? HELP[topic] : "");
  return (
    <span className="help" tabIndex={0} role="note" aria-label={message}>
      <CircleHelp size={13} aria-hidden="true" />
      <span className="help-bubble" aria-hidden="true">{message}</span>
    </span>
  );
}
