import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { CookieNotice } from "@/components/cookie-notice";
import { MotionRoot } from "@/components/motion-root";
import { DashboardProvider } from "@/lib/dashboard-context";

export const metadata: Metadata = {
  title: {
    default: "Command Center — Synthetix Alpha",
    template: "%s — Synthetix Alpha",
  },
  description:
    "Synthetix Alpha is an AI-assisted options paper-trading command center. Copilot mode only — no live brokerage submission from the dashboard.",
  applicationName: "Synthetix Alpha",
  keywords: ["options", "paper trading", "AI", "Synthetix Alpha", "risk-gated"],
  authors: [{ name: "Synthetix Alpha" }],
  robots: { index: false, follow: false },
  openGraph: {
    title: "Synthetix Alpha",
    description: "AI-assisted options paper-trading command center.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#050506",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <DashboardProvider>
          <MotionRoot>
            <AppShell>{children}</AppShell>
            <CookieNotice />
          </MotionRoot>
        </DashboardProvider>
      </body>
    </html>
  );
}
