"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { NAV } from "@/lib/mock-data";

/** Schwebende Glas-Leiste unter 1024 px (ersetzt die Sidebar). Bei vielen Einträgen scrollt die Leiste in sich. */
export function MobileNav() {
  const pathname = usePathname();
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const nav = ref.current;
    const el = nav?.querySelector<HTMLElement>("[aria-current='page']");
    if (nav && el) nav.scrollLeft = el.offsetLeft - (nav.clientWidth - el.clientWidth) / 2;
  }, [pathname]);

  return (
    <nav
      ref={ref}
      aria-label="Hauptnavigation"
      className="glass fixed inset-x-3 z-30 flex overflow-x-auto rounded-3xl border p-1.5 shadow-pop [scrollbar-width:none] lg:hidden [&::-webkit-scrollbar]:hidden"
      style={{ bottom: "max(12px, env(safe-area-inset-bottom))" }}
    >
      {NAV.map(({ href, short, label, icon: Icon }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            aria-label={label}
            aria-current={active ? "page" : undefined}
            className={cn("flex min-w-[4.25rem] flex-1 flex-col items-center gap-0.5 rounded-2xl py-2 text-[10px] font-semibold", active ? "bg-brand text-brand-foreground" : "text-muted-foreground")}
          >
            <Icon className="size-5" strokeWidth={1.8} />
            <span className="max-w-full truncate px-0.5">{short}</span>
          </Link>
        );
      })}
    </nav>
  );
}
