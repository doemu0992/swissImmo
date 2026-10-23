"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, KanbanSquare, List, MessageSquare, Plus, Search } from "lucide-react";
import { PersonAvatar } from "@/components/shared/person-avatar";
import { PageTitle, pageMain } from "@/components/shared/page-title";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CURRENT_USER, TICKETS, TICKET_COLUMNS, type Ticket, type TicketStatus } from "@/lib/tickets-data";
import { cn } from "@/lib/utils";
import { ContactTenantDialog, NewTicketDialog, type NewTicketInput } from "./ticket-dialogs";
import { TicketCard } from "./ticket-card";
import { AgeHint, PriorityBadge, SlaHint, StatusMenu } from "./ticket-parts";

type FilterId = "mine" | "notfall" | "overdue";
const FILTERS: { id: FilterId; label: string }[] = [
  { id: "mine", label: "Meine Tickets" },
  { id: "notfall", label: "Notfall" },
  { id: "overdue", label: "Überfällig" },
];

export function TicketsView() {
  const [tickets, setTickets] = useState<Ticket[]>(TICKETS);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<FilterId[]>([]);
  const [view, setView] = useState<"board" | "list">("board");
  const [newOpen, setNewOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [notice, setNotice] = useState("");

  const setStatus = (id: string, status: TicketStatus) => setTickets((ts) => ts.map((t) => (t.id === id ? { ...t, status, slaDays: status === "erledigt" ? null : t.slaDays ?? 3 } : t)));

  const create = (i: NewTicketInput) => {
    const n = 2042 + (tickets.length - TICKETS.length);
    setTickets((ts) => [{ id: `T-${n}`, title: i.title, property: i.property.split(",")[0], priority: i.priority, status: "neu", assignee: CURRENT_USER, ageDays: 0, slaDays: i.priority === "Notfall" ? 0 : i.priority === "Hoch" ? 2 : 5 }, ...ts]);
    setNotice(`Ticket «${i.title}» wurde in der Spalte «Neu» angelegt.`);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return tickets.filter((t) => {
      if (q && !`${t.id} ${t.title} ${t.property} ${t.assignee}`.toLowerCase().includes(q)) return false;
      if (active.includes("mine") && t.assignee !== CURRENT_USER) return false;
      if (active.includes("notfall") && t.priority !== "Notfall") return false;
      if (active.includes("overdue") && !(t.slaDays !== null && t.slaDays < 0)) return false;
      return true;
    });
  }, [tickets, query, active]);

  const toggle = (id: FilterId) => setActive((a) => (a.includes(id) ? a.filter((x) => x !== id) : [...a, id]));
  const open = tickets.filter((t) => t.status !== "erledigt").length;
  const overdue = tickets.filter((t) => t.slaDays !== null && t.slaDays < 0).length;

  return (
    <main className={pageMain}>
      <PageTitle
        role="Bewirtschafter"
        title="Tickets"
        subtitle={`${open} offene Tickets, davon ${overdue} mit überschrittener SLA-Frist.`}
        actions={
          <>
            <Button variant="outline" onClick={() => setContactOpen(true)}><MessageSquare /> Mieter kontaktieren</Button>
            <Button onClick={() => setNewOpen(true)}><Plus strokeWidth={2.6} /> Neues Ticket</Button>
          </>
        }
      />

      {notice && (
        <div role="status" className="flex items-center gap-2.5 rounded-2xl border border-success/40 bg-success/10 px-4 py-3 text-sm font-medium">
          <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden="true" />
          <span className="min-w-0 flex-1">{notice}</span>
          <button className="rounded-lg px-2 py-1 text-xs font-bold text-muted-foreground hover:bg-accent" onClick={() => setNotice("")}>Schliessen</button>
        </div>
      )}

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <label className="relative w-full lg:max-w-sm">
          <span className="sr-only">Tickets durchsuchen</span>
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ticket, Objekt oder Person suchen …" className="pl-10" />
        </label>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter">
          {FILTERS.map((f) => {
            const on = active.includes(f.id);
            return (
              <button
                key={f.id}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(f.id)}
                className={cn("h-10 rounded-full border px-4 text-sm font-semibold transition-colors", on ? "border-primary bg-primary/15 text-primary" : "bg-card/60 text-muted-foreground hover:bg-accent hover:text-foreground")}
              >
                {f.label}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-3 lg:ml-auto">
          <span className="text-sm text-muted-foreground" aria-live="polite">{filtered.length} von {tickets.length}</span>
          <Tabs value={view} onValueChange={(v) => setView(v as "board" | "list")}>
            <TabsList aria-label="Ansicht">
              <TabsTrigger value="board" className="inline-flex items-center gap-1.5"><KanbanSquare className="size-4" aria-hidden="true" /> Board</TabsTrigger>
              <TabsTrigger value="list" className="inline-flex items-center gap-1.5"><List className="size-4" aria-hidden="true" /> Liste</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>

      {view === "board" ? (
        <div className="relative -mx-4 flex snap-x gap-4 overflow-x-auto px-4 pb-3 sm:-mx-6 sm:px-6 lg:mx-0 lg:px-0" role="region" aria-label="Ticket-Board" tabIndex={0}>
          {TICKET_COLUMNS.map((col) => {
            const items = filtered.filter((t) => t.status === col.id);
            return (
              <section key={col.id} aria-labelledby={`col-${col.id}`} className="flex min-w-0 shrink-0 basis-[86%] snap-start flex-col gap-3 rounded-3xl border bg-secondary/40 p-3.5 sm:basis-[46%] lg:min-w-[250px] lg:flex-1 lg:basis-0">
                <header className="flex items-center justify-between gap-2 px-1.5 pt-1">
                  <h3 id={`col-${col.id}`} className="text-sm font-extrabold">{col.label}</h3>
                  <Badge variant="secondary" className="tabular">{items.length}</Badge>
                </header>
                <ul className="flex flex-col gap-3">
                  {items.map((t) => <TicketCard key={t.id} ticket={t} onStatus={(s) => setStatus(t.id, s)} />)}
                </ul>
                {items.length === 0 && <p className="rounded-2xl border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">Keine Tickets</p>}
              </section>
            );
          })}
        </div>
      ) : (
        <Card className="overflow-hidden">
          <Table label="Ticketliste" className="min-w-[980px]">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Ticket</TableHead>
                <TableHead>Objekt</TableHead>
                <TableHead>Priorität</TableHead>
                <TableHead>SLA</TableHead>
                <TableHead>Zuständig</TableHead>
                <TableHead>Alter</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="max-w-[280px]">
                    <div className="tabular text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{t.id}</div>
                    <div className="font-bold">{t.title}</div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{t.property}</TableCell>
                  <TableCell><PriorityBadge priority={t.priority} /></TableCell>
                  <TableCell className="whitespace-nowrap"><SlaHint days={t.slaDays} /></TableCell>
                  <TableCell>
                    <span className="flex items-center gap-2 whitespace-nowrap"><PersonAvatar name={t.assignee} className="size-7" /><span className="text-xs">{t.assignee}</span></span>
                  </TableCell>
                  <TableCell className="whitespace-nowrap"><AgeHint days={t.ageDays} /></TableCell>
                  <TableCell><StatusMenu ticket={t} variant="pill" onChange={(s) => setStatus(t.id, s)} /></TableCell>
                </TableRow>
              ))}
              {filtered.length === 0 && (
                <TableRow><TableCell colSpan={7} className="py-12 text-center text-muted-foreground">Keine Tickets für diese Filter.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
      )}

      <NewTicketDialog open={newOpen} onOpenChange={setNewOpen} onCreate={create} />
      <ContactTenantDialog open={contactOpen} onOpenChange={setContactOpen} onSend={(to) => setNotice(`Nachricht an ${to} wurde im Mieterdossier abgelegt (Mockup, nichts versendet).`)} />
    </main>
  );
}
