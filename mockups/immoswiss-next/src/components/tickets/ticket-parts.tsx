"use client";

import { AlertTriangle, CalendarClock, Check, ChevronDown, Clock, MoreHorizontal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { TICKET_COLUMNS, type Ticket, type TicketPriority, type TicketStatus } from "@/lib/tickets-data";
import { cn } from "@/lib/utils";

export const PRIORITY_VARIANT: Record<TicketPriority, "destructive" | "warning" | "default" | "secondary"> = {
  Notfall: "destructive",
  Hoch: "warning",
  Mittel: "default",
  Tief: "secondary",
};

export function PriorityBadge({ priority }: { priority: TicketPriority }) {
  return (
    <Badge variant={PRIORITY_VARIANT[priority]}>
      {priority === "Notfall" && <AlertTriangle className="size-3" strokeWidth={2.6} aria-hidden="true" />}
      <span className="sr-only">Priorität: </span>
      {priority}
    </Badge>
  );
}

export function slaText(days: number | null): { text: string; tone: "bad" | "warn" | "ok" | "done" } {
  if (days === null) return { text: "erledigt", tone: "done" };
  if (days < 0) return { text: `überfällig seit ${-days} ${-days === 1 ? "Tag" : "Tagen"}`, tone: "bad" };
  if (days === 0) return { text: "fällig heute", tone: "warn" };
  return { text: `fällig in ${days} ${days === 1 ? "Tag" : "Tagen"}`, tone: days <= 2 ? "warn" : "ok" };
}

export function SlaHint({ days, className }: { days: number | null; className?: string }) {
  const { text, tone } = slaText(days);
  const Icon = tone === "done" ? Check : tone === "bad" ? AlertTriangle : CalendarClock;
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-semibold", tone === "bad" && "text-destructive", tone === "warn" && "text-warning", tone === "ok" && "text-muted-foreground", tone === "done" && "text-success", className)}>
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="sr-only">SLA: </span>
      {text}
    </span>
  );
}

export const ageText = (d: number) => (d === 0 ? "heute" : d === 1 ? "1 Tag" : `${d} Tage`);

export function AgeHint({ days }: { days: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <Clock className="size-3.5" aria-hidden="true" />
      <span className="sr-only">Alter: </span>
      {ageText(days)}
    </span>
  );
}

/** Statuswechsel per Menü (Radix DropdownMenu) — Tastatur: Enter öffnen, Pfeile wählen. */
export function StatusMenu({ ticket, onChange, variant = "icon" }: { ticket: Ticket; onChange: (s: TicketStatus) => void; variant?: "icon" | "pill" }) {
  const current = TICKET_COLUMNS.find((c) => c.id === ticket.status)!;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {variant === "icon" ? (
          <Button variant="ghost" size="icon" className="size-9 shrink-0" aria-label={`Status ändern für ${ticket.id}, aktuell ${current.label}`}>
            <MoreHorizontal />
          </Button>
        ) : (
          <Button variant="outline" size="sm" aria-label={`Status ändern für ${ticket.id}, aktuell ${current.label}`}>
            {current.label}
            <ChevronDown />
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Status ändern</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={ticket.status} onValueChange={(v) => onChange(v as TicketStatus)}>
          {TICKET_COLUMNS.map((c) => (
            <DropdownMenuRadioItem key={c.id} value={c.id}>{c.label}</DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
