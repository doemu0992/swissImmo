import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/shared/placeholder-page";

export const metadata: Metadata = { title: "Mieter — immoswiss" };

export default function Page() {
  return <PlaceholderPage title="Mieter" description="Mieterstamm, Mietverträge und Korrespondenz folgen in einer späteren Ausbaustufe." />;
}
