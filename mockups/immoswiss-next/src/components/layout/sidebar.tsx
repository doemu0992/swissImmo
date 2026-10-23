"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { NAV } from "@/lib/mock-data";
import { Logo } from "./logo";

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside aria-label="Hauptnavigation" className="glass fixed inset-y-0 left-0 z-30 hidden w-64 flex-col gap-8 border-r px-4 py-6 lg:flex">
      <Logo />
      <nav className="flex flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon, badge }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3.5 py-3 text-sm font-semibold transition-colors",
                active ? "bg-brand text-brand-foreground shadow-card" : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <Icon className="size-5" strokeWidth={1.8} />
              {label}
              {badge ? <span className="ml-auto rounded-full bg-destructive/15 px-2 py-0.5 text-[11px] font-bold text-destructive">{badge}</span> : null}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto rounded-2xl border bg-secondary/60 p-4">
        <div className="text-sm font-bold">Nebenkosten 2025</div>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">38 von 126 Abrechnungen sind noch nicht versendet. Einsprachefrist: 30 Tage.</p>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-background" role="progressbar" aria-valuenow={70} aria-valuemin={0} aria-valuemax={100} aria-label="Fortschritt Abrechnungen">
          <div className="h-full w-[70%] rounded-full bg-primary" />
        </div>
        <div className="tabular mt-1.5 text-xs text-muted-foreground">88 / 126 versendet</div>
      </div>
    </aside>
  );
}
