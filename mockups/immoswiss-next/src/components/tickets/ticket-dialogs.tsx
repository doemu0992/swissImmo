"use client";

import { useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, Select, Textarea } from "@/components/ui/select";
import { TENANTS, TICKET_PRIORITIES, TICKET_PROPERTIES, type TicketPriority } from "@/lib/tickets-data";

export type NewTicketInput = { title: string; property: string; priority: TicketPriority; description: string };

export function NewTicketDialog({ open, onOpenChange, onCreate }: { open: boolean; onOpenChange: (o: boolean) => void; onCreate: (t: NewTicketInput) => void }) {
  const [priority, setPriority] = useState<TicketPriority>("Mittel");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Neues Ticket</DialogTitle>
          <DialogDescription>Meldung erfassen und einer Liegenschaft zuordnen. Zuständig wird zunächst Dominik Gerber.</DialogDescription>
        </DialogHeader>
        <form
          className="mt-5 flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            onCreate({ title: String(f.get("title")), property: String(f.get("property")), priority, description: String(f.get("description")) });
            setPriority("Mittel");
            onOpenChange(false);
          }}
        >
          <Field label="Titel" htmlFor="nt-title">
            <Input id="nt-title" name="title" required placeholder="z. B. Wasserhahn tropft in der Küche" autoComplete="off" />
          </Field>
          <Field label="Liegenschaft" htmlFor="nt-property">
            <Select id="nt-property" name="property" required defaultValue={TICKET_PROPERTIES[0]}>
              {TICKET_PROPERTIES.map((p) => <option key={p}>{p}</option>)}
            </Select>
          </Field>
          <fieldset>
            <legend className="mb-1.5 text-sm font-semibold">Priorität</legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {TICKET_PRIORITIES.map((p) => (
                <label key={p} className="cursor-pointer">
                  <input type="radio" name="priority" value={p} checked={priority === p} onChange={() => setPriority(p)} className="peer sr-only" />
                  <span className="flex h-11 items-center justify-center rounded-xl border bg-background/60 text-sm font-semibold text-muted-foreground transition-colors hover:bg-accent peer-checked:border-primary peer-checked:bg-primary/15 peer-checked:text-primary peer-focus-visible:ring-2 peer-focus-visible:ring-ring">
                    {p}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <Field label="Beschreibung" htmlFor="nt-desc">
            <Textarea id="nt-desc" name="description" placeholder="Was ist passiert? Wo genau? Seit wann?" />
          </Field>
          <DialogFooter className="mt-2">
            <DialogClose asChild><Button type="button" variant="outline">Abbrechen</Button></DialogClose>
            <Button type="submit">Ticket erstellen</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ContactTenantDialog({ open, onOpenChange, onSend }: { open: boolean; onOpenChange: (o: boolean) => void; onSend: (to: string) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Mieter kontaktieren</DialogTitle>
          <DialogDescription>Die Nachricht wird im Mieterdossier abgelegt (Mockup: es wird nichts versendet).</DialogDescription>
        </DialogHeader>
        <form
          className="mt-5 flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            onSend(TENANTS.find((t) => t.id === f.get("to"))?.name ?? "");
            onOpenChange(false);
          }}
        >
          <Field label="Empfänger" htmlFor="ct-to">
            <Select id="ct-to" name="to" required defaultValue={TENANTS[0].id}>
              {TENANTS.map((t) => <option key={t.id} value={t.id}>{t.name} — {t.unit}</option>)}
            </Select>
          </Field>
          <Field label="Betreff" htmlFor="ct-subject">
            <Input id="ct-subject" name="subject" required defaultValue="Terminvorschlag Reparatur" autoComplete="off" />
          </Field>
          <Field label="Nachricht" htmlFor="ct-msg">
            <Textarea id="ct-msg" name="message" required className="min-h-[140px]" defaultValue={"Guten Tag\n\nGerne würden wir für die Reparatur einen Termin vereinbaren. Passt Ihnen Dienstag, 27. Oktober, zwischen 08:00 und 10:00 Uhr?\n\nFreundliche Grüsse\nDominik Gerber"} />
          </Field>
          <DialogFooter className="mt-2">
            <DialogClose asChild><Button type="button" variant="outline">Abbrechen</Button></DialogClose>
            <Button type="submit"><Send /> Senden</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
