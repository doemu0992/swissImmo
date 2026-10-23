/* DUMMY-DATEN (CHF) — später durch Server-Daten (Server Components / API) ersetzen.
   Die Formen (Typen) sind so gewählt, dass die Komponenten unverändert bleiben. */
import { Building2, CalendarDays, Coins, FileText, Home, KeyRound, LayoutDashboard, LineChart, Settings, Ticket, Users, Wallet, Wrench, type LucideIcon } from "lucide-react";

export type NavItem = { href: string; label: string; short: string; icon: LucideIcon; badge?: number };

export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", short: "Start", icon: LayoutDashboard },
  { href: "/immobilien", label: "Immobilien", short: "Objekte", icon: Building2 },
  { href: "/mieter", label: "Mieter", short: "Mieter", icon: Users },
  { href: "/tickets", label: "Tickets", short: "Tickets", icon: Ticket, badge: 4 },
  { href: "/kalender", label: "Kalender", short: "Kalender", icon: CalendarDays },
  { href: "/finanzen", label: "Finanzen", short: "Finanzen", icon: Wallet, badge: 3 },
  { href: "/portfolio", label: "Portfolio", short: "Portfolio", icon: LineChart },
  { href: "/dokumente", label: "Dokumente", short: "Dateien", icon: FileText },
  { href: "/einstellungen", label: "Einstellungen", short: "Mehr", icon: Settings },
];

export type Kpi = {
  id: string;
  label: string;
  value: string;
  trend: number;
  /** Einheit direkt hinter der Zahl im Badge, z. B. « %» oder « Pkt.» */
  trendUnit: string;
  trendNote: string;
  /** Welche Richtung ist gut? Daraus folgt grün oder rot. */
  goodWhen: "up" | "down";
  icon: LucideIcon;
  spark: number[];
  alert?: boolean;
};

export const KPIS: Kpi[] = [
  { id: "einnahmen", label: "Gesamteinnahmen", value: "CHF 482'350", trend: 5.2, trendUnit: " %", trendNote: "vs. Vormonat", goodWhen: "up", icon: Coins, spark: [38, 41, 40, 44, 43, 47, 48] },
  { id: "objekte", label: "Aktive Mietobjekte", value: "126", trend: 3, trendUnit: "", trendNote: "neu seit Vormonat", goodWhen: "up", icon: Home, spark: [118, 118, 120, 121, 121, 123, 126] },
  { id: "reparaturen", label: "Offene Reparaturen", value: "14", trend: 4, trendUnit: "", trendNote: "vs. Vormonat", goodWhen: "down", icon: Wrench, spark: [8, 9, 7, 10, 10, 12, 14], alert: true },
  { id: "leerstand", label: "Leerstandsquote", value: "2.4 %", trend: -0.6, trendUnit: " Pkt.", trendNote: "vs. Vormonat", goodWhen: "down", icon: KeyRound, spark: [4.1, 3.8, 3.5, 3.2, 3.0, 3.0, 2.4] },
];

export const MONTHS = ["Mai", "Jun", "Jul", "Aug", "Sep", "Okt"] as const;

export type ChartSeries = { key: string; label: string; colorVar: string; dashed?: boolean };
export type ChartView = {
  id: "einnahmen" | "belegung";
  title: string;
  series: ChartSeries[];
  rows: Record<string, number | string>[];
  domain: [number, number];
  tickSuffix: string;
  tickDivisor: number;
  summary: { label: string; value: string; delta: string; positive: boolean }[];
};

export const CHART_VIEWS: ChartView[] = [
  {
    id: "einnahmen",
    title: "Finanz- & Mietübersicht",
    series: [
      { key: "ist", label: "Einnahmen", colorVar: "--chart-1" },
      { key: "soll", label: "Mietsoll", colorVar: "--chart-2", dashed: true },
    ],
    rows: [
      { month: "Mai", ist: 431200, soll: 440000 },
      { month: "Jun", ist: 438900, soll: 445000 },
      { month: "Jul", ist: 447500, soll: 450000 },
      { month: "Aug", ist: 452300, soll: 455000 },
      { month: "Sep", ist: 458700, soll: 462000 },
      { month: "Okt", ist: 482350, soll: 470000 },
    ],
    domain: [420000, 490000],
    tickSuffix: "k",
    tickDivisor: 1000,
    summary: [
      { label: "Einnahmen Okt.", value: "CHF 482'350", delta: "+5.2 %", positive: true },
      { label: "Mietsoll Okt.", value: "CHF 470'000", delta: "+1.7 %", positive: true },
      { label: "Zahlungsquote", value: "102.6 %", delta: "+1.1 Pkt.", positive: true },
    ],
  },
  {
    id: "belegung",
    title: "Belegungsquote",
    series: [{ key: "quote", label: "Belegung", colorVar: "--chart-1" }],
    rows: [
      { month: "Mai", quote: 94.8 },
      { month: "Jun", quote: 95.4 },
      { month: "Jul", quote: 96.1 },
      { month: "Aug", quote: 96.6 },
      { month: "Sep", quote: 97.0 },
      { month: "Okt", quote: 97.6 },
    ],
    domain: [93, 99],
    tickSuffix: " %",
    tickDivisor: 1,
    summary: [
      { label: "Belegung Okt.", value: "97.6 %", delta: "+0.6 Pkt.", positive: true },
      { label: "Ø Leerstand", value: "4.9 Tage", delta: "−1.2 Tage", positive: true },
      { label: "Kündigungen", value: "5", delta: "+2", positive: false },
    ],
  },
];

export type Appointment = { id: number; title: string; kind: "Abnahme" | "Besichtigung" | "Handwerker" | "Übergabe"; place: string; date: string; time: string; people: string[] };
export const APPOINTMENTS: Appointment[] = [
  { id: 1, title: "Wohnungsabnahme", kind: "Abnahme", place: "Seefeldstrasse 12 · 3.5 Zi, 2. OG", date: "Heute", time: "14:00", people: ["Muster Hans", "Dominik Gerber"] },
  { id: 2, title: "Besichtigung Neuvermietung", kind: "Besichtigung", place: "Rebbergweg 8 · 2.5 Zi, DG", date: "Heute", time: "16:30", people: ["Bianchi Sara"] },
  { id: 3, title: "Heizungswartung", kind: "Handwerker", place: "Bahnhofstrasse 4 · Technikraum", date: "Mi", time: "08:00", people: ["Kälte Meier", "Rossi Luca", "Dominik Gerber"] },
  { id: 4, title: "Wohnungsübergabe", kind: "Übergabe", place: "Seestrasse 41 · 4.5 Zi, 3. OG", date: "Fr", time: "10:15", people: ["Rossi Luca"] },
];

export type Todo = { id: number; title: string; due: string; urgent?: boolean; done?: boolean };
export const TODOS: Todo[] = [
  { id: 11, title: "Mahnung 2 an Keller Maria versenden", due: "fällig heute", urgent: true },
  { id: 12, title: "Nebenkostenabrechnung 2025 prüfen", due: "bis 31.10." },
  { id: 13, title: "Offerte Dachreparatur freigeben", due: "bis 03.11.", done: true },
  { id: 14, title: "Mietvertrag Schmid P. unterschreiben lassen", due: "bis 05.11." },
];

export type OccupancySlice = { key: string; label: string; value: number; colorVar: string };
export const OCCUPANCY: OccupancySlice[] = [
  { key: "vermietet", label: "Vermietet", value: 118, colorVar: "--chart-1" },
  { key: "gekuendigt", label: "Gekündigt", value: 5, colorVar: "--chart-3" },
  { key: "leer", label: "Leerstand", value: 3, colorVar: "--chart-4" },
];
