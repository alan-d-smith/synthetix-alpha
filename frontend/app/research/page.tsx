import type { Metadata } from "next";
import { DashboardPage } from "@/components/dashboard";
export const metadata: Metadata = { title: "Research" };
export default function Page() { return <DashboardPage page="research" />; }
