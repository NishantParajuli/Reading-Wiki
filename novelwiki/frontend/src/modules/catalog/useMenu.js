/* ============================================================
   Menu semantics for the catalog's popover menus (sort, filters, shelf, ⋯).
   The trigger announces a menu; the panel is role="menu" with roving focus:
   opening focuses the checked item (or the first; ArrowUp on the trigger opens
   on the last), arrows move and wrap, Home/End jump, a letter jumps to the
   next item starting with it, Escape closes, and Tab closes and carries on
   from the trigger. Items are MenuItem buttons given role menuitem or
   menuitemradio (with aria-checked) and tabIndex -1.
   ============================================================ */
import { useEffect, useId, useRef } from "react";

const ITEM = '[role^="menuitem"]:not([disabled]):not([aria-disabled="true"])';

/** `label` names the menu (its visible heading, if any, is aria-hidden). */
export function useMenu(open, setOpen, label) {
  const id = useId();
  const menuId = `${id}menu`;
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const start = useRef("checked");   // which item takes focus when the menu opens

  const items = () => (menuRef.current ? [...menuRef.current.querySelectorAll(ITEM)] : []);
  const leave = () => {
    if (triggerRef.current) triggerRef.current.focus({ preventScroll: true });
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const list = items();
    const from = start.current;
    start.current = "checked";
    const pick = from === "last" ? list[list.length - 1]
      : from === "first" ? list[0]
      : list.find(el => el.getAttribute("aria-checked") === "true") || list[0];
    if (pick) pick.focus({ preventScroll: true });
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  function onTriggerKeyDown(e) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    start.current = e.key === "ArrowUp" ? "last" : "first";
    if (!open) { setOpen(true); return; }
    const list = items();
    const pick = e.key === "ArrowUp" ? list[list.length - 1] : list[0];
    if (pick) pick.focus();
  }

  function onMenuKeyDown(e) {
    const list = items();
    if (!list.length) return;
    const at = list.indexOf(document.activeElement);
    const go = (i) => { e.preventDefault(); list[(i + list.length) % list.length].focus(); };
    switch (e.key) {
      case "ArrowDown": go(at + 1); return;
      case "ArrowUp": go(at < 0 ? list.length - 1 : at - 1); return;
      case "Home": case "PageUp": go(0); return;
      case "End": case "PageDown": go(list.length - 1); return;
      case "Escape": e.preventDefault(); leave(); return;
      case "Tab": leave(); return;   // the default Tab then moves on from the trigger
      default:
        if (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
          const ch = e.key.toLowerCase();
          const next = [...list.slice(at + 1), ...list.slice(0, at + 1)]
            .find(el => el.textContent.trim().toLowerCase().startsWith(ch));
          if (next) { e.preventDefault(); next.focus(); }
        }
    }
  }

  return {
    /** Close and hand focus back to the trigger (after choosing an item). */
    close: leave,
    triggerProps: {
      ref: triggerRef, "aria-haspopup": "menu", "aria-expanded": open,
      "aria-controls": open ? menuId : undefined, onKeyDown: onTriggerKeyDown,
    },
    menuProps: { ref: menuRef, id: menuId, role: "menu", "aria-label": label, onKeyDown: onMenuKeyDown },
  };
}

/** Props for one item: a choice (menuitemradio) when `checked` is a boolean. */
export function menuItemProps(checked) {
  return typeof checked === "boolean"
    ? { role: "menuitemradio", "aria-checked": checked, tabIndex: -1 }
    : { role: "menuitem", tabIndex: -1 };
}
