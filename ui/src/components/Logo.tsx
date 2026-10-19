// The Obsergent mark: a ring (the observer, also the O) with a gap, the agent inside, and the trail of a question leaving through it.
// `draw` plays a one-time draw-in (switched off for people who prefer reduced motion, see styles.css).
import { useId } from "react";

export function Logo({ size = 26, draw = false }: { size?: number; draw?: boolean }) {
  const id = useId();
  return (
    <svg className={`logo${draw ? " draw" : ""}`} width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Obsergent">
      <defs>
        <linearGradient id={`${id}-ring`} x1="8" y1="56" x2="56" y2="8" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#2dd4bf" /><stop offset="1" stopColor="#38bdf8" />
        </linearGradient>
      </defs>
      <circle className="logo-ring" cx="32" cy="32" r="22" fill="none" stroke={`url(#${id}-ring)`} strokeWidth="7" strokeLinecap="round"
        strokeDasharray="115 23.2" transform="rotate(-14 32 32)" />
      <circle className="logo-dot" cx="30" cy="34" r="5.2" fill={`url(#${id}-ring)`} />
      <circle className="logo-trail t1" cx="40" cy="24" r="3.6" fill="#f472b6" />
      <circle className="logo-trail t2" cx="48.5" cy="15.5" r="2.6" fill="#f472b6" opacity=".8" />
      <circle className="logo-trail t3" cx="55" cy="9" r="1.8" fill="#f472b6" opacity=".6" />
    </svg>
  );
}
