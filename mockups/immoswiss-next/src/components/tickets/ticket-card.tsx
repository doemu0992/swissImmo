import { Building2 } from "lucide-react";
import { PersonAvatar } from "@/components/shared/person-avatar";
import type { Ticket, TicketStatus } from "@/lib/tickets-data";
import { cn } from "@/lib/utils";
import { AgeHint, PriorityBadge, SlaHint, StatusMenu } from "./ticket-parts";

export function TicketCard({ ticket, onStatus }: { ticket: Ticket; onStatus: (s: TicketStatus) => void }) {
  const critical = ticket.priority === "Notfall" && ticket.status !== "erledigt";
  return (
    <li className={cn("rounded-2xl border bg-background/60 p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40", critical && "border-destructive/40")}>
      <article aria-label={`${ticket.id}: ${ticket.title}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="tabular text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{ticket.id}</div>
            <h4 className="mt-0.5 text-sm font-bold leading-snug">{ticket.title}</h4>
          </div>
          <StatusMenu ticket={ticket} onChange={onStatus} />
        </div>
        <div className="mt-2 flex min-w-0 items-start gap-1.5 text-xs text-muted-foreground">
          <Building2 className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          <span className="min-w-0">{ticket.property}</span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
          <PriorityBadge priority={ticket.priority} />
          <SlaHint days={ticket.slaDays} />
        </div>
        <div className="mt-3 flex items-center justify-between gap-2 border-t pt-3">
          <div className="flex min-w-0 items-center gap-2">
            <PersonAvatar name={ticket.assignee} className="size-7" />
            <span className="sr-only">Zuständig: {ticket.assignee}</span>
          </div>
          <AgeHint days={ticket.ageDays} />
        </div>
      </article>
    </li>
  );
}
