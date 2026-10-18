// App-wide settings kept in React context: live tail, the time window of the dashboards, light/dark theme.
// Each one is remembered in localStorage (wrapped in try/catch: storage can be blocked).
// React building blocks: context (shared values), state, effects, memoisation.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

// A hook like useState that also saves the value in localStorage (the browser's small key-value store).
function useRemembered<T>(key: string, fallback: T): [T, (value: T) => void] {
  // Read the saved value, or use the default if nothing is saved or storage is blocked.
  const read = (): T => {
    try {
      const stored = localStorage.getItem(`agenttrace.${key}`);
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
      localStorage.setItem(`agenttrace.${key}`, JSON.stringify(next));
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
  // { => Whenever the theme changes, tag <html data-theme=...> so CSS can switch colors.
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  // Rebuild the shared object only when something changed.
  const value = useMemo(() => ({ live, setLive, hours, setHours, theme, setTheme }), [live, hours, theme]);
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

/** `refetchInterval` for react-query: poll every 2 s while "live" is on, otherwise never. */
// How often to refetch: every 2s in live mode, otherwise never.
export function useLiveInterval(): number | false {
  return useSettings().live ? 2000 : false;
}
