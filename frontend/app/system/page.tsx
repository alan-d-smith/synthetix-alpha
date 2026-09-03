import type { Metadata } from "next";
import { DashboardPage } from "@/components/dashboard";
export const metadata: Metadata = { title: "System" };
export default function Page() { return <DashboardPage page="system" />; }
