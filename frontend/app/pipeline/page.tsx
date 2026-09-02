import type { Metadata } from "next";
import { DashboardPage } from "@/components/dashboard";
export const metadata: Metadata = { title: "Pipeline — Synthetix Alpha" };
export default function Page() { return <DashboardPage page="pipeline" />; }
