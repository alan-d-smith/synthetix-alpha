"use client";

import type { Transition, Variants } from "motion/react";
import { useReducedMotion } from "motion/react";

export const MOTION_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

export const MOTION_DURATION = 0.28;

export const MOTION_Y = 12;

export const motionTransition: Transition = {
  type: "tween",
  duration: MOTION_DURATION,
  ease: MOTION_EASE,
};

export const chartEnterTransition: Transition = {
  type: "tween",
  duration: 0.72,
  ease: MOTION_EASE,
};

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: MOTION_Y },
  show: { opacity: 1, y: 0, transition: motionTransition },
};

export const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: {
      staggerChildren: 0.055,
      delayChildren: 0.04,
    },
  },
};

export function usePrefersReducedMotion() {
  return Boolean(useReducedMotion());
}

export { useReducedMotion };
