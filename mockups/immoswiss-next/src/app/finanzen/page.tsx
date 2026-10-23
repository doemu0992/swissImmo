import type { Metadata } from "next";
import { FinanceView } from "@/components/finance/finance-view";

export const metadata: Metadata = { title: "Finanzen — immoswiss" };
export default function FinancePage() {
  return <FinanceView />;
}
