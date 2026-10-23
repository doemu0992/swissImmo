/* DUMMY-DATEN Tickets (Rolle Bewirtschafter). Stichtag: Freitag, 23.10.2026. */

export type TicketStatus = "neu" | "bearbeitung" | "wartet" | "erledigt";
export type TicketPriority = "Notfall" | "Hoch" | "Mittel" | "Tief";

export type Ticket = {
  id: string;
  title: string;
  property: string;
  priority: TicketPriority;
  status: TicketStatus;
  /** Zuständige Person (Initialen-Avatar) */
  assignee: string;
  /** Alter in Tagen */
  ageDays: number;
  /** Tage bis SLA-Frist; negativ = überfällig; null = keine Frist (erledigt) */
  slaDays: number | null;
};

export const TICKET_COLUMNS: { id: TicketStatus; label: string; hint: string }[] = [
  { id: "neu", label: "Neu", hint: "Noch nicht zugewiesen oder gesichtet" },
  { id: "bearbeitung", label: "In Bearbeitung", hint: "Aktiv in Klärung" },
  { id: "wartet", label: "Wartet auf Dritte", hint: "Handwerker, Mieter oder Versicherung" },
  { id: "erledigt", label: "Erledigt", hint: "Abgeschlossen in den letzten 30 Tagen" },
];

export const TICKET_PRIORITIES: TicketPriority[] = ["Notfall", "Hoch", "Mittel", "Tief"];
export const CURRENT_USER = "Dominik Gerber";
export const TICKET_ASSIGNEES = ["Dominik Gerber", "Rossi Luca", "Bianchi Sara", "Keller Anna"];

export const TICKET_PROPERTIES = [
  "Seefeldstrasse 12, 8008 Zürich",
  "Rebbergweg 8, 8708 Männedorf",
  "Bahnhofstrasse 4, 8001 Zürich",
  "Seestrasse 41, 8700 Küsnacht",
  "Lindenhof 3, 8001 Zürich",
];

export const TICKETS: Ticket[] = [
  { id: "T-2041", title: "Wasserschaden Decke Badezimmer", property: "Seefeldstrasse 12 · 3.5 Zi, 2. OG", priority: "Notfall", status: "neu", assignee: "Dominik Gerber", ageDays: 0, slaDays: 0 },
  { id: "T-2040", title: "Heizung fällt wiederholt aus", property: "Bahnhofstrasse 4 · Technikraum", priority: "Hoch", status: "neu", assignee: "Rossi Luca", ageDays: 1, slaDays: 2 },
  { id: "T-2038", title: "Schlüsselverlust Haupteingang", property: "Rebbergweg 8 · 2.5 Zi, DG", priority: "Mittel", status: "neu", assignee: "Bianchi Sara", ageDays: 2, slaDays: 5 },
  { id: "T-2036", title: "Lift steckt zwischen 2. und 3. OG", property: "Seestrasse 41 · Lift A", priority: "Notfall", status: "bearbeitung", assignee: "Dominik Gerber", ageDays: 3, slaDays: -2 },
  { id: "T-2033", title: "Geschirrspüler leckt (Garantiefall)", property: "Seefeldstrasse 12 · 4.5 Zi, 1. OG", priority: "Mittel", status: "bearbeitung", assignee: "Keller Anna", ageDays: 6, slaDays: 2 },
  { id: "T-2031", title: "Balkongeländer locker", property: "Lindenhof 3 · 3.5 Zi, 4. OG", priority: "Hoch", status: "bearbeitung", assignee: "Rossi Luca", ageDays: 8, slaDays: 3 },
  { id: "T-2029", title: "Lärmreklamation Nachbarschaft", property: "Rebbergweg 8 · 3.5 Zi, 1. OG", priority: "Tief", status: "bearbeitung", assignee: "Bianchi Sara", ageDays: 12, slaDays: 9 },
  { id: "T-2027", title: "Offerte Dachsanierung einholen", property: "Seestrasse 41 · Dach", priority: "Mittel", status: "wartet", assignee: "Dominik Gerber", ageDays: 15, slaDays: -4 },
  { id: "T-2024", title: "Kaminfeger: Terminbestätigung offen", property: "Bahnhofstrasse 4 · Kamin", priority: "Tief", status: "wartet", assignee: "Keller Anna", ageDays: 11, slaDays: 6 },
  { id: "T-2022", title: "Schimmel Nordwand, Gutachten", property: "Lindenhof 3 · 2.5 Zi, EG", priority: "Hoch", status: "wartet", assignee: "Rossi Luca", ageDays: 19, slaDays: 2 },
  { id: "T-2019", title: "Waschmaschine Waschküche ersetzt", property: "Seefeldstrasse 12 · Waschküche", priority: "Mittel", status: "erledigt", assignee: "Keller Anna", ageDays: 21, slaDays: null },
  { id: "T-2016", title: "Briefkastenschloss getauscht", property: "Rebbergweg 8 · Eingang", priority: "Tief", status: "erledigt", assignee: "Bianchi Sara", ageDays: 17, slaDays: null },
  { id: "T-2012", title: "Treppenhauslicht Sensor defekt", property: "Bahnhofstrasse 4 · Treppenhaus", priority: "Tief", status: "erledigt", assignee: "Rossi Luca", ageDays: 24, slaDays: null },
];

export type Tenant = { id: string; name: string; unit: string };
export const TENANTS: Tenant[] = [
  { id: "m1", name: "Keller Maria", unit: "Seefeldstrasse 12 · 3.5 Zi, 2. OG" },
  { id: "m2", name: "Muster Hans", unit: "Seefeldstrasse 12 · 4.5 Zi, 1. OG" },
  { id: "m3", name: "Bianchi Sara", unit: "Rebbergweg 8 · 2.5 Zi, DG" },
  { id: "m4", name: "Schmid Peter", unit: "Bahnhofstrasse 4 · 3.5 Zi, 3. OG" },
  { id: "m5", name: "Rossi Luca", unit: "Seestrasse 41 · 4.5 Zi, 3. OG" },
];
