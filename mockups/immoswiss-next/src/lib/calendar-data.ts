/* DUMMY-DATEN Kalender (Rolle Bewirtschafter). Stichtag: Freitag, 23.10.2026. */

export type EventKind = "Abnahme" | "Besichtigung" | "Handwerker" | "Übergabe" | "Frist";

export type CalendarEvent = {
  id: string;
  /** ISO-Datum YYYY-MM-DD */
  date: string;
  /** Uhrzeit HH:MM; leer bei ganztägigen Fristen */
  time: string;
  title: string;
  kind: EventKind;
  place: string;
};

export const EVENT_KINDS: EventKind[] = ["Abnahme", "Besichtigung", "Handwerker", "Übergabe", "Frist"];
export const TODAY_ISO = "2026-10-23";

export const CALENDAR_EVENTS: CalendarEvent[] = [
  { id: "e1", date: "2026-10-02", time: "09:00", title: "Wohnungsabnahme Muster", kind: "Abnahme", place: "Seefeldstrasse 12 · 4.5 Zi, 1. OG" },
  { id: "e2", date: "2026-10-06", time: "17:30", title: "Besichtigung 3.5 Zi", kind: "Besichtigung", place: "Bahnhofstrasse 4 · 3. OG" },
  { id: "e3", date: "2026-10-08", time: "08:00", title: "Liftservice Schindler", kind: "Handwerker", place: "Seestrasse 41 · Lift A" },
  { id: "e4", date: "2026-10-09", time: "", title: "Frist Kündigungsanfechtung", kind: "Frist", place: "Lindenhof 3 · 2.5 Zi, EG" },
  { id: "e5", date: "2026-10-13", time: "11:00", title: "Wohnungsübergabe Keller", kind: "Übergabe", place: "Rebbergweg 8 · 3.5 Zi, 1. OG" },
  { id: "e6", date: "2026-10-15", time: "14:00", title: "Besichtigung Neuvermietung", kind: "Besichtigung", place: "Seefeldstrasse 12 · 2.5 Zi, EG" },
  { id: "e7", date: "2026-10-15", time: "16:00", title: "Besichtigung Neuvermietung", kind: "Besichtigung", place: "Seefeldstrasse 12 · 2.5 Zi, EG" },
  { id: "e8", date: "2026-10-20", time: "08:30", title: "Dachinspektion Gebr. Frei", kind: "Handwerker", place: "Seestrasse 41 · Dach" },
  { id: "e9", date: "2026-10-22", time: "", title: "Frist Rückzahlung Kaution", kind: "Frist", place: "Rebbergweg 8 · 2.5 Zi, DG" },
  { id: "e10", date: "2026-10-23", time: "14:00", title: "Wohnungsabnahme", kind: "Abnahme", place: "Seefeldstrasse 12 · 3.5 Zi, 2. OG" },
  { id: "e11", date: "2026-10-23", time: "16:30", title: "Besichtigung Neuvermietung", kind: "Besichtigung", place: "Rebbergweg 8 · 2.5 Zi, DG" },
  { id: "e12", date: "2026-10-26", time: "13:30", title: "Besichtigung Gewerbefläche", kind: "Besichtigung", place: "Bahnhofstrasse 4 · EG" },
  { id: "e13", date: "2026-10-27", time: "08:00", title: "Heizungswartung Kälte Meier", kind: "Handwerker", place: "Bahnhofstrasse 4 · Technikraum" },
  { id: "e14", date: "2026-10-28", time: "", title: "Frist NK-Abrechnung versenden", kind: "Frist", place: "Alle Liegenschaften" },
  { id: "e15", date: "2026-10-29", time: "10:15", title: "Wohnungsübergabe Rossi", kind: "Übergabe", place: "Seestrasse 41 · 4.5 Zi, 3. OG" },
  { id: "e16", date: "2026-10-30", time: "09:30", title: "Wohnungsabnahme Schmid", kind: "Abnahme", place: "Bahnhofstrasse 4 · 3.5 Zi, 3. OG" },
  { id: "e17", date: "2026-10-31", time: "", title: "Frist Mietvertrag Schmid P.", kind: "Frist", place: "Bahnhofstrasse 4 · 3.5 Zi, 3. OG" },
  { id: "e18", date: "2026-11-02", time: "08:00", title: "Kaminfeger", kind: "Handwerker", place: "Bahnhofstrasse 4 · Kamin" },
  { id: "e19", date: "2026-11-03", time: "", title: "Frist Offerte Dachreparatur", kind: "Frist", place: "Seestrasse 41 · Dach" },
  { id: "e20", date: "2026-11-05", time: "15:00", title: "Besichtigung 2.5 Zi", kind: "Besichtigung", place: "Lindenhof 3 · EG" },
  { id: "e21", date: "2026-11-09", time: "10:00", title: "Wohnungsübergabe Neumieter", kind: "Übergabe", place: "Seefeldstrasse 12 · 3.5 Zi, 2. OG" },
  { id: "e22", date: "2026-11-12", time: "09:00", title: "Wohnungsabnahme Bianchi", kind: "Abnahme", place: "Rebbergweg 8 · 2.5 Zi, DG" },
  { id: "e23", date: "2026-11-16", time: "13:00", title: "Malerarbeiten Treppenhaus", kind: "Handwerker", place: "Seefeldstrasse 12 · Treppenhaus" },
  { id: "e24", date: "2026-11-20", time: "", title: "Frist Einsprache NK-Abrechnung", kind: "Frist", place: "Rebbergweg 8" },
  { id: "e25", date: "2026-11-24", time: "11:30", title: "Wohnungsübergabe", kind: "Übergabe", place: "Lindenhof 3 · 3.5 Zi, 4. OG" },
  { id: "e26", date: "2026-11-30", time: "", title: "Frist Auszahlung Eigentümer", kind: "Frist", place: "Alle Liegenschaften" },
];
