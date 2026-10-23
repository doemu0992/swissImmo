import { Bell, ChevronDown, Search, SlidersHorizontal } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LogoMark, SwissCross } from "./logo";

export function TopBar() {
  return (
    <header className="glass sticky top-0 z-20 border-b" style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
      <div className="flex items-center gap-3 px-4 py-3.5 sm:px-6 lg:px-8">
        <LogoMark className="size-10 lg:hidden" />
        <label className="relative max-w-xl flex-1">
          <span className="sr-only">Suche</span>
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground" />
          <Input type="search" placeholder="Suchen nach Immobilien, Mietern …" className="pl-10 pr-14" />
          <kbd className="absolute right-3 top-1/2 hidden -translate-y-1/2 rounded-md border bg-card px-1.5 py-0.5 text-[11px] font-semibold text-muted-foreground sm:block">⌘K</kbd>
        </label>
        <Button variant="outline" aria-label="Filter">
          <SlidersHorizontal />
          <span className="hidden sm:inline">Filtern</span>
          <span className="min-w-5 rounded-full bg-brand px-1.5 text-center text-[11px] font-bold text-brand-foreground">2</span>
        </Button>
        <Button variant="outline" size="icon" className="relative hidden sm:inline-flex" aria-label="Mitteilungen">
          <Bell />
          <span className="absolute right-3 top-2.5 size-2 rounded-full bg-destructive ring-2 ring-card" />
        </Button>
        <button className="flex h-11 items-center gap-3 rounded-xl pl-1.5 sm:border sm:bg-card/60 sm:pr-3" aria-label="Profil">
          <Avatar className="size-9"><AvatarFallback className="bg-gradient-to-br from-brand to-primary">DG</AvatarFallback></Avatar>
          <span className="hidden items-center gap-2 text-sm font-bold md:flex">
            Grüezi, Dominik <SwissCross />
            <ChevronDown className="size-4 text-muted-foreground" />
          </span>
        </button>
      </div>
    </header>
  );
}
