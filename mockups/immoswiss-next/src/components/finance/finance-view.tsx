"use client";

import { PageTitle, pageMain } from "@/components/shared/page-title";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dunning, Nka, Payables } from "./other-tabs";
import { Receivables } from "./receivables";

const TABS = [
  { id: "debitoren", label: "Debitoren" },
  { id: "kreditoren", label: "Kreditoren" },
  { id: "mahnwesen", label: "Mahnwesen" },
  { id: "nka", label: "Nebenkosten (NKA)" },
];

export function FinanceView() {
  return (
    <main className={pageMain}>
      <PageTitle role="Buchhalter" title="Finanzen" subtitle="Stand Freitag, 23. Oktober 2026 · Mandant Muster Verwaltung AG" actions={<Button variant="outline">Monatsabschluss</Button>} />
      <Tabs defaultValue="debitoren">
        <div className="relative -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <TabsList variant="underline" aria-label="Finanzbereiche" className="min-w-max">
            {TABS.map((t) => <TabsTrigger key={t.id} value={t.id} variant="underline">{t.label}</TabsTrigger>)}
          </TabsList>
        </div>
        <TabsContent value="debitoren"><Receivables /></TabsContent>
        <TabsContent value="kreditoren"><Payables /></TabsContent>
        <TabsContent value="mahnwesen"><Dunning /></TabsContent>
        <TabsContent value="nka"><Nka /></TabsContent>
      </Tabs>
    </main>
  );
}
