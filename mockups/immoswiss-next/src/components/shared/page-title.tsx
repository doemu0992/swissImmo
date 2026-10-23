import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";

/** Seitenkopf der Rollen-Screens: Rolle, Titel, Untertitel, Aktionen rechts. */
export function PageTitle({ role, title, subtitle, actions }: { role: string; title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <Badge variant="default" className="uppercase tracking-widest">Rolle: {role}</Badge>
        <h1 className="mt-2 text-2xl font-extrabold tracking-tight sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2.5">{actions}</div>}
    </div>
  );
}

export const pageMain = "mx-auto flex w-full max-w-[1480px] flex-1 flex-col gap-6 px-4 pb-36 pt-7 sm:px-6 lg:gap-7 lg:px-8 lg:pb-14";
