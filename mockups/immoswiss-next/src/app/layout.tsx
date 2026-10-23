import type { Metadata, Viewport } from "next";
import "./globals.css";
import { MobileNav } from "@/components/layout/mobile-nav";
import { Sidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/topbar";

export const metadata: Metadata = {
  title: "immoswiss — Dashboard",
  description: "Mockup des Haupt-Dashboards der Immobilien-SaaS immoswiss (Dummy-Daten).",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover", themeColor: "#0c1424" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" />
      </head>
      <body className="font-sans">
        <Sidebar />
        <div className="flex min-h-screen flex-col lg:pl-64">
          <TopBar />
          {children}
        </div>
        <MobileNav />
      </body>
    </html>
  );
}
