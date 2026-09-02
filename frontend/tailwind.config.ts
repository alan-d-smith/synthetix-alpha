import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      screens: {
        tablet: "900px",
        desktop: "1280px",
      },
      colors: {
        canvas: "var(--canvas)", surface: "var(--surface-1)", raised: "var(--surface-2)",
        "surface-hover": "var(--surface-hover)", subtle: "var(--border-subtle)", strong: "var(--border-strong)",
        foreground: "var(--text-primary)", secondary: "var(--text-secondary)", muted: "var(--text-muted)",
        cyan: "var(--data-cyan)", violet: "var(--data-violet)", positive: "var(--positive)",
        negative: "var(--negative)", warning: "var(--warning)",
        "chart-label": "var(--chart-label)",
        "chart-tooltip-foreground": "var(--chart-tooltip-foreground)",
        "chart-tooltip-muted": "var(--chart-tooltip-muted)",
      },
      fontFamily: { display: ["Instrument Sans", "Inter", "sans-serif"], sans: ["Inter", "sans-serif"], mono: ["IBM Plex Mono", "ui-monospace", "monospace"] },
      borderRadius: { control: "6px", panel: "8px" },
      boxShadow: { overlay: "0 18px 48px rgba(0, 0, 0, 0.46)" },
      transitionDuration: { 160: "160ms", 180: "180ms" },
    },
  },
  plugins: [],
};

export default config;
