/* ============================================================
   Motion vocabulary — the one place screens import animation from.

   Physics:   springs.snappy (controls) · smooth (surfaces) · gentle (heroes)
              · bouncy (celebrations). CSS mirrors these as --ease-spring.
   Variants:  `rise` (content arriving), `stagger(n)` containers, `pop`
              (floating surfaces), `sheet` (bottom sheets).
   Rule of thumb: interactive feedback ≤ 240ms, surfaces ≤ 420ms, heroes
   ≤ 1.1s. Everything respects prefers-reduced-motion via <MotionConfig
   reducedMotion="user"> at the root (transforms collapse, opacity stays).
   ============================================================ */
export {
  motion, AnimatePresence, LayoutGroup, MotionConfig, useReducedMotion,
  useMotionValue, useSpring, useTransform, useScroll, useInView, animate,
  useAnimate, useMotionValueEvent, stagger as staggerDelay,
} from "motion/react";

export const springs = {
  snappy: { type: "spring", stiffness: 520, damping: 40, mass: 0.8 },
  smooth: { type: "spring", stiffness: 280, damping: 32 },
  gentle: { type: "spring", stiffness: 150, damping: 24 },
  bouncy: { type: "spring", stiffness: 430, damping: 17 },
  layout: { type: "spring", stiffness: 420, damping: 38, mass: 0.9 },
};

export const ease = {
  out: [0.16, 1, 0.3, 1],
  inOut: [0.65, 0, 0.35, 1],
  in: [0.55, 0, 1, 0.45],
};

/* Content arriving: rise from below out of a soft blur. */
export const rise = {
  hidden: { opacity: 0, y: 18, filter: "blur(8px)" },
  show: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.7, ease: ease.out } },
  exit: { opacity: 0, y: -8, filter: "blur(4px)", transition: { duration: 0.22, ease: ease.in } },
};

/* Parent that staggers `rise`-style children. */
export function stagger(step = 0.055, delay = 0) {
  return {
    hidden: {},
    show: { transition: { staggerChildren: step, delayChildren: delay } },
    exit: { transition: { staggerChildren: step / 2, staggerDirection: -1 } },
  };
}

/* Floating surfaces (menus, popovers, palettes). */
export const pop = {
  hidden: { opacity: 0, y: -6, scale: 0.96, filter: "blur(6px)" },
  show: { opacity: 1, y: 0, scale: 1, filter: "blur(0px)", transition: springs.smooth },
  exit: { opacity: 0, y: -4, scale: 0.98, filter: "blur(4px)", transition: { duration: 0.16, ease: ease.in } },
};

/* Bottom sheets / drawers. */
export const sheet = {
  hidden: { y: "100%" },
  show: { y: 0, transition: springs.smooth },
  exit: { y: "100%", transition: { duration: 0.26, ease: ease.in } },
};

export const fade = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.3, ease: ease.out } },
  exit: { opacity: 0, transition: { duration: 0.18 } },
};
