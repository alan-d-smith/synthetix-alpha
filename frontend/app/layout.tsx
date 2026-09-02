import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { MotionRoot } from "@/components/motion-root";
import { DashboardProvider } from "@/lib/dashboard-context";

export const metadata: Metadata = {
  title: {
    default: "Command Center — Synthetix Alpha",
    template: "%s",
  },
  description: "Autonomous, risk-gated options trading command center.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <DashboardProvider>
          <MotionRoot>
            <AppShell>{children}</AppShell>
          </MotionRoot>
        </DashboardProvider>
      </body>
    </html>
  );
}
