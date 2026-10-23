import { cn } from "@/lib/utils";

/** Schweizer Kreuz (Wortmarke-Zusatz). */
export function SwissCross({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" className={cn("size-3.5", className)} role="img" aria-label="Schweiz">
      <rect width="20" height="20" rx="3" fill="#e5342d" />
      <path d="M8.5 4h3v4.5H16v3h-4.5V16h-3v-4.5H4v-3h4.5z" fill="#fff" />
    </svg>
  );
}

/** Haus aus einer Linie — nur das Zeichen (Telefon-Kopf). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-9", className)} fill="none" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 15L16 4l13 11M7 13v14h18V13" stroke="hsl(var(--primary))" />
      <path d="M12 27v-7h3v7M18 27v-9h3v9" stroke="hsl(var(--chart-2))" />
    </svg>
  );
}

export function Logo({ tenant = true }: { tenant?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <LogoMark />
      <div className="leading-tight">
        <span className="relative text-[22px] font-extrabold tracking-tight">
          immoswiss
          <span className="absolute -right-4 -top-1"><SwissCross /></span>
        </span>
        {tenant && <div className="mt-0.5 text-xs font-medium text-muted-foreground">Muster Verwaltung AG</div>}
      </div>
    </div>
  );
}
