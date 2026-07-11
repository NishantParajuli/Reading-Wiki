/* Toast system — replaces every alert() and silent failure.
   useToast() → { toast } ; toast(message, { tone, action, duration }). */
import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { Icon } from "./Icon.jsx";

const ToastContext = createContext({ toast: () => {} });
export const useToast = () => useContext(ToastContext);

const TONE_ICON = { ok: "check", danger: "alert", info: "sparkles", neutral: "sparkles" };

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id) => {
    setToasts(ts => ts.filter(t => t.id !== id));
  }, []);

  const toast = useCallback((message, opts = {}) => {
    const id = ++idRef.current;
    const t = { id, message, tone: opts.tone || "neutral", action: opts.action || null };
    setToasts(ts => [...ts.slice(-3), t]);
    const ms = opts.duration || 5000;
    setTimeout(() => dismiss(id), ms);
    return id;
  }, [dismiss]);

  return (
    <ToastContext.Provider value={{ toast, dismiss }}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-atomic="false">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <span className="toast-icon"><Icon name={TONE_ICON[t.tone] || "sparkles"} size={16} sw={2.2} /></span>
            <div className="toast-body">{t.message}</div>
            {t.action && (
              <button className="toast-action" onClick={() => { t.action.onClick(); dismiss(t.id); }}>
                {t.action.label}
              </button>
            )}
            <button className="toast-close" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
              <Icon name="x" size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
