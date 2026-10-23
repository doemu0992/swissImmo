/* DUMMY-DATEN Finanzen (Rolle Buchhalter). Stichtag: Freitag, 23.10.2026. Beträge in CHF. */



/* ---------- Debitoren ---------- */

export type ReceivableStatus = "bezahlt" | "offen" | "ueberfaellig";
export type Receivable = {
  id: string;
  tenant: string;
  /** Kurzname der Liegenschaft (Filter) */
  property: string;
  unit: string;
  /** Fälligkeit, ISO */
  due: string;
  amount: number;
  status: ReceivableStatus;
  /** 0 = keine Mahnung */
  dunning: 0 | 1 | 2 | 3;
  /** Tage überfällig (nur Status ueberfaellig) */
  overdueDays?: number;
};

export const RECEIVABLE_PROPERTIES = ["Seefeldstrasse 12", "Rebbergweg 8", "Bahnhofstrasse 4", "Seestrasse 41", "Lindenhof 3"];

export const STATUS_META: Record<ReceivableStatus, { label: string; dot: string; variant: "success" | "warning" | "destructive" }> = {
  bezahlt: { label: "Bezahlt", dot: "bg-success", variant: "success" },
  offen: { label: "Offen", dot: "bg-warning", variant: "warning" },
  ueberfaellig: { label: "Überfällig", dot: "bg-destructive", variant: "destructive" },
};

export const RECEIVABLES: Receivable[] = [
  { id: "RE-2610-0412", tenant: "Keller Maria", property: "Seefeldstrasse 12", unit: "3.5 Zi, 2. OG", due: "2026-10-01", amount: 2450, status: "ueberfaellig", dunning: 2, overdueDays: 22 },
  { id: "RE-2610-0413", tenant: "Muster Hans", property: "Seefeldstrasse 12", unit: "4.5 Zi, 1. OG", due: "2026-10-01", amount: 3180, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0414", tenant: "Bianchi Sara", property: "Rebbergweg 8", unit: "2.5 Zi, DG", due: "2026-10-01", amount: 1890, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0415", tenant: "Schmid Peter", property: "Bahnhofstrasse 4", unit: "3.5 Zi, 3. OG", due: "2026-10-01", amount: 2760, status: "ueberfaellig", dunning: 1, overdueDays: 22 },
  { id: "RE-2610-0416", tenant: "Rossi Luca", property: "Seestrasse 41", unit: "4.5 Zi, 3. OG", due: "2026-10-01", amount: 3420, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0417", tenant: "Brunner Elena", property: "Lindenhof 3", unit: "2.5 Zi, EG", due: "2026-10-01", amount: 2120, status: "ueberfaellig", dunning: 3, overdueDays: 52 },
  { id: "RE-2610-0418", tenant: "Gerber Thomas", property: "Lindenhof 3", unit: "3.5 Zi, 4. OG", due: "2026-10-01", amount: 2590, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0419", tenant: "Meier Sabine", property: "Rebbergweg 8", unit: "3.5 Zi, 1. OG", due: "2026-10-01", amount: 2240, status: "ueberfaellig", dunning: 1, overdueDays: 22 },
  { id: "RE-2610-0420", tenant: "Fischer Andreas", property: "Seefeldstrasse 12", unit: "2.5 Zi, EG", due: "2026-10-01", amount: 1960, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0421", tenant: "Weber Nicole", property: "Seestrasse 41", unit: "3.5 Zi, 2. OG", due: "2026-10-01", amount: 2830, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0422", tenant: "Huber Markus", property: "Bahnhofstrasse 4", unit: "Gewerbe EG", due: "2026-10-15", amount: 5600, status: "ueberfaellig", dunning: 1, overdueDays: 8 },
  { id: "RE-2610-0423", tenant: "Steiner Claudia", property: "Seestrasse 41", unit: "2.5 Zi, 1. OG", due: "2026-10-01", amount: 1940, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0424", tenant: "Moser Daniel", property: "Lindenhof 3", unit: "4.5 Zi, 3. OG", due: "2026-10-01", amount: 3050, status: "ueberfaellig", dunning: 3, overdueDays: 61 },
  { id: "RE-2611-0501", tenant: "Keller Maria", property: "Seefeldstrasse 12", unit: "3.5 Zi, 2. OG", due: "2026-11-01", amount: 2450, status: "offen", dunning: 0 },
  { id: "RE-2611-0502", tenant: "Muster Hans", property: "Seefeldstrasse 12", unit: "4.5 Zi, 1. OG", due: "2026-11-01", amount: 3180, status: "offen", dunning: 0 },
  { id: "RE-2611-0503", tenant: "Bianchi Sara", property: "Rebbergweg 8", unit: "2.5 Zi, DG", due: "2026-11-01", amount: 1890, status: "offen", dunning: 0 },
  { id: "RE-2611-0504", tenant: "Rossi Luca", property: "Seestrasse 41", unit: "4.5 Zi, 3. OG", due: "2026-11-01", amount: 3420, status: "offen", dunning: 0 },
  { id: "RE-2611-0505", tenant: "Gerber Thomas", property: "Lindenhof 3", unit: "3.5 Zi, 4. OG", due: "2026-11-01", amount: 2590, status: "offen", dunning: 0 },
  { id: "RE-2611-0506", tenant: "Fischer Andreas", property: "Seefeldstrasse 12", unit: "2.5 Zi, EG", due: "2026-11-01", amount: 1960, status: "offen", dunning: 0 },
  { id: "RE-2610-0425", tenant: "Baumann Rita", property: "Rebbergweg 8", unit: "4.5 Zi, 2. OG", due: "2026-10-01", amount: 2980, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0426", tenant: "Frei Stefan", property: "Bahnhofstrasse 4", unit: "2.5 Zi, 1. OG", due: "2026-10-01", amount: 1870, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0427", tenant: "Zimmermann Lea", property: "Seestrasse 41", unit: "1.5 Zi, EG", due: "2026-10-01", amount: 1420, status: "bezahlt", dunning: 0 },
  { id: "RE-2610-0428", tenant: "Graf Beat", property: "Bahnhofstrasse 4", unit: "4.5 Zi, 2. OG", due: "2026-10-01", amount: 3110, status: "ueberfaellig", dunning: 2, overdueDays: 34 },
  { id: "RE-2610-0429", tenant: "Lüthi Corinne", property: "Lindenhof 3", unit: "1.5 Zi, DG", due: "2026-10-01", amount: 1380, status: "bezahlt", dunning: 0 },
];

/* ---------- Kreditoren / Rechnungs-Workflow ---------- */

export const INVOICE_STEPS = ["Erfasst", "Geprüft", "Freigegeben", "Bezahlt"] as const;
export type Payable = { id: string; supplier: string; subject: string; property: string; due: string; amount: number; step: 0 | 1 | 2 | 3 };

export const PAYABLES: Payable[] = [
  { id: "ER-3318", supplier: "Kälte Meier AG", subject: "Heizungswartung Q3", property: "Bahnhofstrasse 4", due: "2026-11-05", amount: 1840.5, step: 1 },
  { id: "ER-3317", supplier: "Schindler Aufzüge AG", subject: "Liftservice Oktober", property: "Seestrasse 41", due: "2026-11-02", amount: 960, step: 2 },
  { id: "ER-3315", supplier: "Gebr. Frei Dach GmbH", subject: "Dachinspektion", property: "Seestrasse 41", due: "2026-11-12", amount: 2480, step: 0 },
  { id: "ER-3312", supplier: "ewz Zürich", subject: "Allgemeinstrom September", property: "Seefeldstrasse 12", due: "2026-10-28", amount: 742.35, step: 2 },
  { id: "ER-3309", supplier: "Gebäudeversicherung Kt. ZH", subject: "Prämie 2026/27", property: "Lindenhof 3", due: "2026-10-20", amount: 5230, step: 3 },
  { id: "ER-3306", supplier: "Maler Brunner AG", subject: "Treppenhaus streichen", property: "Rebbergweg 8", due: "2026-11-15", amount: 7415, step: 1 },
];

/* ---------- Mahnwesen ---------- */

export type DunningCase = { id: string; tenant: string; property: string; level: 1 | 2 | 3; amount: number; fee: number; sentOn: string; next: string };
export const DUNNING_LEVELS = [
  { level: 1, label: "Zahlungserinnerung", note: "Freundlicher Hinweis, 10 Tage Frist" },
  { level: 2, label: "1. Mahnung", note: "Mahngebühr CHF 20.–, 10 Tage Frist" },
  { level: 3, label: "Letzte Mahnung", note: "Androhung Betreibung, CHF 40.–" },
] as const;

export const DUNNING_CASES: DunningCase[] = [
  { id: "MA-0231", tenant: "Brunner Elena", property: "Lindenhof 3", level: 3, amount: 2120, fee: 40, sentOn: "2026-10-12", next: "Betreibungsbegehren prüfen" },
  { id: "MA-0229", tenant: "Moser Daniel", property: "Lindenhof 3", level: 3, amount: 3050, fee: 40, sentOn: "2026-10-09", next: "Betreibungsbegehren prüfen" },
  { id: "MA-0233", tenant: "Keller Maria", property: "Seefeldstrasse 12", level: 2, amount: 2450, fee: 20, sentOn: "2026-10-16", next: "Letzte Mahnung ab 26.10." },
  { id: "MA-0234", tenant: "Graf Beat", property: "Bahnhofstrasse 4", level: 2, amount: 3110, fee: 20, sentOn: "2026-10-19", next: "Letzte Mahnung ab 29.10." },
  { id: "MA-0236", tenant: "Schmid Peter", property: "Bahnhofstrasse 4", level: 1, amount: 2760, fee: 0, sentOn: "2026-10-14", next: "1. Mahnung ab 24.10." },
  { id: "MA-0237", tenant: "Meier Sabine", property: "Rebbergweg 8", level: 1, amount: 2240, fee: 0, sentOn: "2026-10-14", next: "1. Mahnung ab 24.10." },
  { id: "MA-0240", tenant: "Huber Markus", property: "Bahnhofstrasse 4", level: 1, amount: 5600, fee: 0, sentOn: "2026-10-22", next: "1. Mahnung ab 01.11." },
];

/* ---------- Nebenkostenabrechnung (NKA) ---------- */

export const NKA_STEPS = [
  { id: "entwurf", label: "Entwurf", note: "Kosten erfasst" },
  { id: "pruefung", label: "Prüfung", note: "Vier-Augen-Prinzip" },
  { id: "versand", label: "Versand", note: "An Mieter versendet" },
  { id: "einsprache", label: "Einsprachefrist", note: "30 Tage ab Versand" },
  { id: "abschluss", label: "Abschluss", note: "Saldo verbucht" },
] as const;

export type NkaRun = { id: string; property: string; period: string; units: number; step: 0 | 1 | 2 | 3 | 4; balance: number; note: string };
export const NKA_RUNS: NkaRun[] = [
  { id: "NKA-25-01", property: "Seefeldstrasse 12", period: "01.01.–31.12.2025", units: 24, step: 3, balance: -3820.4, note: "Einsprachefrist bis 12.11.2026" },
  { id: "NKA-25-02", property: "Rebbergweg 8", period: "01.01.–31.12.2025", units: 16, step: 2, balance: 1240, note: "Versand am 21.10.2026" },
  { id: "NKA-25-03", property: "Bahnhofstrasse 4", period: "01.01.–31.12.2025", units: 32, step: 1, balance: -5160.8, note: "Prüfung bis 31.10.2026" },
  { id: "NKA-25-04", property: "Seestrasse 41", period: "01.01.–31.12.2025", units: 28, step: 4, balance: 410.2, note: "Abgeschlossen am 15.09.2026" },
  { id: "NKA-25-05", property: "Lindenhof 3", period: "01.01.–31.12.2025", units: 26, step: 0, balance: 0, note: "Heizkosten fehlen noch" },
];
