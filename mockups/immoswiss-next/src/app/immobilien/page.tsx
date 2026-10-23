import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/shared/placeholder-page";

export const metadata: Metadata = { title: "Immobilien — immoswiss" };

export default function Page() {
  return <PlaceholderPage title="Immobilien" description="Die Objektverwaltung mit Liegenschaften, Wohnungen und Zählerständen entsteht als nächster Screen." />;
}
