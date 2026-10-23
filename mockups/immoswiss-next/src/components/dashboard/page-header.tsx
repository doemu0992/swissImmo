import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

export function PageHeader() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="text-xs font-bold uppercase tracking-widest text-muted-foreground">Freitag, 23. Oktober 2026 · KW 43</div>
        <h1 className="mt-1 text-2xl font-extrabold tracking-tight sm:text-3xl">Guten Morgen, Dominik</h1>
        <p className="mt-1 text-sm text-muted-foreground">7 Forderungen sind überfällig, 3 Fristen laufen diese Woche ab.</p>
      </div>
      <div className="flex gap-2.5">
        <Button variant="outline">Bericht exportieren</Button>
        <Button><Plus strokeWidth={2.6} /> Neues Objekt</Button>
      </div>
    </div>
  );
}
