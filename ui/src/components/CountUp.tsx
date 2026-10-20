// A number that counts up once when it first appears (not at all when the system asks for less motion).
import { useEffect, useRef, useState } from "react";

const DURATION_MS = 650;

function reducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export function CountUp({ value, format }: { value: number; format: (n: number) => string }) {
  const [shown, setShown] = useState(() => (reducedMotion() ? value : 0));
  const first = useRef(true);
  useEffect(() => {
    // Later changes (live updates) jump straight to the new value; only the first appearance is animated.
    if (!first.current || reducedMotion()) { setShown(value); return; }
    first.current = false;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / DURATION_MS);
      setShown(value * (1 - (1 - progress) ** 3));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <span aria-label={format(value)}>{format(Number.isInteger(value) ? Math.round(shown) : shown)}</span>;
}
