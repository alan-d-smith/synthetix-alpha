"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "sx-cookie-notice-dismissed";

export function CookieNotice() {
  const reduced = usePrefersReducedMotion();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(STORAGE_KEY) !== "1") setVisible(true);
    } catch {
      setVisible(true);
    }
  }, []);

  function dismiss() {
    setVisible(false);
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // local-only dismissal; ignore storage failures
    }
  }

  return (
    <AnimatePresence>
      {visible ? (
        <motion.aside
          role="dialog"
          aria-labelledby="cookie-notice-title"
          aria-describedby="cookie-notice-body"
          className={cn(
            "fixed bottom-20 left-3 right-3 z-[var(--z-toast)] mx-auto max-w-md",
            "rounded-panel border border-subtle bg-raised p-4 shadow-overlay",
            "min-[900px]:bottom-6 min-[900px]:left-auto min-[900px]:right-6",
          )}
          initial={reduced ? false : { opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={reduced ? undefined : { opacity: 0, y: 12, scale: 0.98 }}
          transition={reduced ? { duration: 0 } : { duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        >
          <p id="cookie-notice-title" className="text-sm font-medium text-foreground">
            🍪 Cookie check
          </p>
          <p id="cookie-notice-body" className="mt-2 text-xs leading-5 text-secondary">
            We promise the only thing we&apos;re
            <br />
            tracking is whether the agent is behaving.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={dismiss}
              className="rounded-control border border-cyan/40 bg-cyan/10 px-3 py-2 text-xs font-medium text-cyan transition-colors hover:bg-cyan/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan"
              aria-label="Accept cookie notice and dismiss"
            >
              Accept
            </button>
            <button
              type="button"
              onClick={dismiss}
              className="rounded-control border border-subtle px-3 py-2 text-xs font-medium text-secondary transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan"
              aria-label="Reject cookie notice and dismiss"
            >
              Reject
            </button>
          </div>
        </motion.aside>
      ) : null}
    </AnimatePresence>
  );
}
