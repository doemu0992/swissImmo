import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/shared/placeholder-page";

export const metadata: Metadata = { title: "Einstellungen — immoswiss" };

export default function Page() {
  return <PlaceholderPage title="Einstellungen" description="Benutzer, Rollen und Mandanteneinstellungen sind noch in Arbeit." />;
}
