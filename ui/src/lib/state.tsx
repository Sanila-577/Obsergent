// App-wide settings kept in React context: live tail, the time window of the dashboards, light/dark theme.
// Each one is remembered in localStorage (wrapped in try/catch: storage can be blocked).
// React building blocks: context (shared values), state, effects, memoisation.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";

// A hook like useState that also saves the value in localStorage (the browser's small key-value store).
function useRemembered<T>(key: string, fallback: T): [T, (value: T) => void] {
  // Read the saved value, or use the default if nothing is saved or storage is blocked.
  const read = (): T => {
    try {
      const stored = localStorage.getItem(`obsergent.${key}`);
      return stored === null ? fallback : (JSON.parse(stored) as T);
    } catch {
      return fallback;
    }
  };
  // The value React tracks; changing it redraws the page.
  const [value, setValue] = useState<T>(read);
  // Update the value and store it.
  const save = (next: T) => {
    setValue(next);
    try {
      localStorage.setItem(`obsergent.${key}`, JSON.stringify(next));
    } catch {
      /* storage blocked: the setting just won't survive a reload */
    }
  };
  return [value, save];
}

// The two allowed themes.
export type Theme = "dark" | "light";

// The shape of the shared settings object.
interface Settings {
  live: boolean;
  setLive: (live: boolean) => void;
  hours: number;
  setHours: (hours: number) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  /** false = Simple (plain words, no ids or raw data); true = Detailed (everything). */
  detailed: boolean;
  setDetailed: (detailed: boolean) => void;
}

// The shared "box" every component can read from.
const SettingsContext = createContext<Settings | null>(null);

// Wraps the app and provides the settings.
export function SettingsProvider({ children }: { children: ReactNode }) {
  // Live tail on/off (default off).
  const [live, setLive] = useRemembered("live", false);
  // Time window of dashboards (default 24h).
  const [hours, setHours] = useRemembered("hours", 24);
  // Dark or light.
  const [theme, setTheme] = useRemembered<Theme>("theme", "dark");
  const [detailed, setDetailed] = useRemembered("detailed", false);
  // { => Whenever the theme changes, tag <html data-theme=...> so CSS can switch colors.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  // Rebuild the shared object only when something changed.
  const value = useMemo(() => ({ live, setLive, hours, setHours, theme, setTheme, detailed, setDetailed }), [live, hours, theme, detailed]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

// Hook for components to read the settings.
export function useSettings(): Settings {
  // Get the nearest provider's value.
  const settings = useContext(SettingsContext);
  // Using the hook outside the provider is a programming error.
  if (!settings) throw new Error("useSettings must be used inside <SettingsProvider>");
  return settings;
}

/** `refetchInterval` for react-query: a safety net only. New data reaches the pages through `useChangeWatcher` (within a
 * second); this regular reload (every 2 s with "Live" on, else every 15 s) also keeps relative times such as "3 min ago" fresh. */
export function useLiveInterval(): number {
  return useSettings().live ? 2000 : 15_000;
}

/** Ask the server every second whether anything new was stored; when the answer changes, reload every page's data at once. */
export function useChangeWatcher(): void {
  const client = useQueryClient();
  const version = useQuery({ queryKey: ["version"], queryFn: api.version, refetchInterval: 1000, refetchIntervalInBackground: false, retry: false });
  const last = useRef<string | null>(null);
  useEffect(() => {
    const now = version.data?.version;
    if (!now) return;
    if (last.current !== null && last.current !== now) {
      client.invalidateQueries({ predicate: (query) => !["version", "health"].includes(String(query.queryKey[0])) });
    }
    last.current = now;
  }, [version.data, client]);
}
