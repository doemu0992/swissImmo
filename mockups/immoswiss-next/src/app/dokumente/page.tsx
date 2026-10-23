import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/shared/placeholder-page";

export const metadata: Metadata = { title: "Dokumente — immoswiss" };

export default function Page() {
  return <PlaceholderPage title="Dokumente" description="Die Dokumentenablage mit Verträgen, Abrechnungen und Protokollen ist noch in Arbeit." />;
}
