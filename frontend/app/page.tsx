import type { Metadata } from "next";
import { DashboardPage } from "@/components/dashboard";

export const metadata: Metadata = { title: "Command Center — Synthetix Alpha" };

export default function Page() {
  return <DashboardPage page="command" />;
}
