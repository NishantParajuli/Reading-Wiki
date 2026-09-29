/* Toast system — replaces every alert() and silent failure.
   useToast() → { toast } ; toast(message, { tone, action, duration }).
   Glass cards rise from the bottom on a spring, restack as others leave,
   show their remaining time as a draining tide line, and can be flicked
   away sideways. */
import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Icon } from "./Icon.jsx";
import { springs } from "../motion/index.js";

const ToastContext = createContext({ toast: () => {} });
export const useToast = () => useContext(ToastContext);

const TONE_ICON = { ok: "check", danger: "alert", info: "sparkles", neutral: "sparkles", warn: "alert" };

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const idRef = useRef(0);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts(ts => ts.filter(t => t.id !== id));
  }, []);

  const toast = useCallback((message, opts = {}) => {
    const id = ++idRef.current;
    const ms = opts.duration || 5000;
    const t = { id, message, tone: opts.tone || "neutral", action: opts.action || null, ms };
    setToasts(ts => [...ts.slice(-3), t]);
    timers.current.set(id, setTimeout(() => dismiss(id), ms));
    return id;
  }, [dismiss]);

  return (
    <ToastContext.Provider value={{ toast, dismiss }}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-atomic="false">
        <AnimatePresence initial={false}>
          {toasts.map(t => (
            <motion.div
              key={t.id}
              layout
              className={`toast ${t.tone}`}
              initial={{ opacity: 0, y: 28, scale: 0.92, filter: "blur(6px)" }}
              animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)", transition: springs.smooth }}
              exit={{ opacity: 0, scale: 0.94, y: 10, filter: "blur(4px)", transition: { duration: 0.2 } }}
              drag="x"
              dragSnapToOrigin
              dragElastic={0.5}
              onDragEnd={(_, info) => { if (Math.abs(info.offset.x) > 110 || Math.abs(info.velocity.x) > 600) dismiss(t.id); }}
              style={{ "--toast-ms": `${t.ms}ms` }}
            >
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
              <span className="toast-timer" aria-hidden="true" />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
