/* ============================================================
   Overlays — Dialog, ConfirmDialog, CostConfirmDialog, Popover, Menu, Drawer.
   All trap focus, close on Escape/backdrop, and restore focus on close.
   ============================================================ */
import React, { useEffect, useState } from "react";
import { Icon } from "./Icon.jsx";
import { Button } from "./ui.jsx";
import { useDismissable, useFocusTrap } from "../lib/hooks.js";
import { experienceApi } from "../modules/experience/api.js";

export function Dialog({ title, icon, danger, wide, onClose, children, busy }) {
  const trapRef = useFocusTrap(true);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);
  return (
    <div className="modal-scrim" onClick={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div ref={trapRef} className={"card modal-card" + (wide ? " wide" : "")} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
        {(title || icon) && (
          <div className="row" style={{ alignItems: "flex-start", marginBottom: 12 }}>
            {icon && <span className={danger ? "modal-danger-icon" : "modal-accent-icon"}><Icon name={icon} size={19} /></span>}
            <h3 className="modal-title grow">{title}</h3>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

/* Destructive-action guard: two deliberate clicks; `requireText` adds
   type-to-confirm for the scariest actions. */
export function ConfirmDialog({ title, body, confirmLabel = "Delete", cancelLabel = "Cancel",
                                requireText = null, busy = false, onConfirm, onCancel, danger = true }) {
  const [typed, setTyped] = useState("");
  const armed = !requireText || typed.trim() === String(requireText).trim();
  return (
    <Dialog title={title} icon="alert" danger={danger} onClose={onCancel} busy={busy}>
      {typeof body === "string"
        ? <p className="muted" style={{ fontSize: "var(--text-sm)", lineHeight: 1.55, margin: "0 0 4px" }}>{body}</p>
        : body}
      {requireText && (
        <label className="field" style={{ marginTop: 12 }}>
          <span>Type <b>{requireText}</b> to confirm</span>
          <input value={typed} onChange={e => setTyped(e.target.value)} autoFocus placeholder={requireText} spellCheck={false} />
        </label>
      )}
      <div className="row" style={{ gap: 10, marginTop: 18, justifyContent: "flex-end" }}>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>{cancelLabel}</Button>
        <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy || !armed} loading={busy}>
          {confirmLabel}
        </Button>
      </div>
    </Dialog>
  );
}

const COST_KIND_LABEL = {
  codex_builds: "codex build", translated_chapters: "chapters", tts_chapters: "chapters", ocr_pages: "pages",
};

/* Pre-flight cost confirmation for expensive actions (codex build, batch
   translation, whole-book narration). Never charges — the action does. */
export function CostConfirmDialog({ novelId, action, params, title, actionLabel = "Confirm", onConfirm, onCancel }) {
  const [est, setEst] = useState(null);   // null = loading, false = error
  const [busy, setBusy] = useState(false);
  const paramsKey = JSON.stringify(params || {});

  useEffect(() => {
    let cancel = false;
    setEst(null);
    experienceApi.costEstimate(novelId, action, params || {})
      .then(e => { if (!cancel) setEst(e); })
      .catch(() => { if (!cancel) setEst(false); });
    return () => { cancel = true; };
  }, [novelId, action, paramsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const units = est && est.estimated_units;
  const unit = est ? (COST_KIND_LABEL[est.quota_kind] || "units") : "";
  const over = est && !est.unlimited && !est.allowed;
  const nothing = est && est.estimated_units === 0;

  async function go() {
    setBusy(true);
    try { await onConfirm(); }
    finally { setBusy(false); }
  }

  const canGo = est === false || (est != null && !(over && !est.spend_allowed));
  return (
    <Dialog title={title || "Confirm"} icon="sparkles" onClose={onCancel} busy={busy}>
      <div className="col" style={{ gap: 8 }}>
        {est === null && <p className="muted" style={{ margin: 0 }}>Estimating cost…</p>}
        {est === false && <p className="muted" style={{ margin: 0 }}>Couldn't estimate the cost. You can still proceed.</p>}
        {est && (
          <>
            <div className="cost-figure">
              <b className="cost-num">{nothing ? "0" : `~${units}`}</b>
              <span className="muted"> {unit}</span>
              {nothing && <span className="muted" style={{ marginLeft: 8 }}>— nothing new to do</span>}
            </div>
            <div className="muted" style={{ fontSize: "var(--text-sm)" }}>
              {est.unlimited
                ? "Your account has unlimited usage."
                : `Quota this month: ${est.remaining}/${est.limit} ${unit} remaining.`}
            </div>
            {over && (
              <div className="cost-warn">
                <Icon name="alert" size={14} />
                {est.spend_allowed
                  ? " This exceeds your remaining quota — it may stop partway."
                  : " Verify your email to use this feature."}
              </div>
            )}
          </>
        )}
      </div>
      <div className="row" style={{ gap: 10, marginTop: 18, justifyContent: "flex-end" }}>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
        <Button variant="primary" onClick={go} disabled={busy || !canGo} loading={busy}>{actionLabel}</Button>
      </div>
    </Dialog>
  );
}

/* Anchored popover: relative-positioned wrapper + absolutely-positioned card.
   Dismisses on outside click / Escape. `align` = left|right. */
export function Popover({ open, onClose, trigger, align = "right", className = "", children, style }) {
  const ref = useDismissable(open, onClose);
  return (
    <div className="usermenu" ref={ref} style={{ position: "relative", display: "inline-block" }}>
      {trigger}
      {open && (
        <div className={["popover", className].filter(Boolean).join(" ")}
             style={{ top: "calc(100% + 8px)", [align]: 0, ...style }}>
          {children}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ icon, danger, selected, children, ...rest }) {
  return (
    <button type="button"
            className={["menu-item", danger ? "is-danger" : "", selected ? "selected" : ""].filter(Boolean).join(" ")}
            {...rest}>
      {icon && <Icon name={icon} size={15} />}
      <span className="grow truncate">{children}</span>
      {selected && <Icon name="check" size={14} />}
    </button>
  );
}

export function Drawer({ onClose, title, children }) {
  const trapRef = useFocusTrap(true);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="drawer-scrim" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={trapRef} className="drawer" role="dialog" aria-modal="true" aria-label={title} onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <b>{title}</b>
          <button className="icon-btn plain" aria-label="Close" onClick={onClose}><Icon name="x" size={16} /></button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
}
