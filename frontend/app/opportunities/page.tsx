import type { Metadata } from "next";
import { DashboardPage } from "@/components/dashboard";
export const metadata: Metadata = { title: "Opportunities" };
export default function Page() { return <DashboardPage page="opportunities" />; }
