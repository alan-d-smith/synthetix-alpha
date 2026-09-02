"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "motion/react";
import { X } from "lucide-react";
import { motionTransition, usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;

export function SheetContent({
  children,
  className,
  title,
  description,
}: {
  children: React.ReactNode;
  className?: string;
  title: string;
  description?: string;
}) {
  const reduced = usePrefersReducedMotion();
  const enter = reduced ? { duration: 0 } : motionTransition;
  return (
    <Dialog.Portal>
      <Dialog.Overlay asChild>
        <motion.div
          animate={{ opacity: 1 }}
          className="fixed inset-0 bg-black/55"
          initial={{ opacity: reduced ? 1 : 0 }}
          style={{ zIndex: "var(--z-backdrop)" }}
          transition={reduced ? { duration: 0 } : { ...motionTransition, duration: 0.16 }}
        />
      </Dialog.Overlay>
      <Dialog.Content asChild>
        <motion.div
          animate={{ opacity: 1, x: 0 }}
          className={cn(
            "fixed inset-y-0 right-0 flex w-full max-w-[480px] flex-col border-l border-strong bg-raised shadow-overlay outline-none max-[899px]:inset-0 max-[899px]:max-w-none max-[899px]:border-l-0",
            className,
          )}
          initial={{ opacity: reduced ? 1 : 0.78, x: reduced ? 0 : 16 }}
          style={{ zIndex: "var(--z-sheet)" }}
          transition={enter}
        >
          <div className="flex items-start justify-between border-b border-subtle px-5 py-4">
            <div>
              <Dialog.Title className="font-display text-base font-semibold">{title}</Dialog.Title>
              {description ? <Dialog.Description className="mt-1 text-xs text-muted">{description}</Dialog.Description> : null}
            </div>
            <Dialog.Close
              aria-label="Close inspector"
              className="rounded-control p-1.5 text-muted transition-colors duration-160 hover:bg-surface-hover hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
        </motion.div>
      </Dialog.Content>
    </Dialog.Portal>
  );
}
