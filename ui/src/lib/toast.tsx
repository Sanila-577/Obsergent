// Small messages at the bottom of the screen ("Copied", "Prices checked"): one provider, one hook.
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

interface Toast {
  id: number;
  text: string;
}

const ToastContext = createContext<(text: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Show a message for two seconds.
  const show = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((now) => [...now.slice(-2), { id, text }]);
    setTimeout(() => setToasts((now) => now.filter((toast) => toast.id !== id)), 2000);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" role="status" aria-live="polite">{toasts.map((toast) => <div key={toast.id} className="toast">{toast.text}</div>)}</div>
    </ToastContext.Provider>
  );
}

/** `const toast = useToast(); toast("Copied")`. */
export function useToast(): (text: string) => void {
  return useContext(ToastContext);
}
