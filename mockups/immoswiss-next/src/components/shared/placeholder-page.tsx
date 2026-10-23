import Link from "next/link";
import { Construction } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { pageMain } from "./page-title";

/** Schlichte «In Arbeit»-Seite für Navigationsziele ohne eigenen Screen (verhindert 404). */
export function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <main className={pageMain}>
      <Card className="mx-auto mt-6 flex w-full max-w-xl flex-col items-center gap-4 p-8 text-center sm:p-12">
        <span className="grid size-16 place-items-center rounded-2xl bg-secondary text-primary">
          <Construction className="size-8" strokeWidth={1.6} aria-hidden="true" />
        </span>
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground">In Arbeit</p>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight">{title}</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{description}</p>
        </div>
        <Button asChild><Link href="/">Zurück zum Dashboard</Link></Button>
      </Card>
    </main>
  );
}
