/* DUMMY-DATEN Portfolio (Rolle Eigentümer). Beträge in CHF. */

export type PortfolioKpi = { id: string; label: string; value: string; note: string; trend: string; positive: boolean };
export const PORTFOLIO_KPIS: PortfolioKpi[] = [
  { id: "rendite", label: "Bruttorendite", value: "4.8 %", note: "Ø der letzten 12 Monate", trend: "+0.2 Pkt.", positive: true },
  { id: "netto", label: "Nettoertrag p. a.", value: "CHF 2'184'600", note: "nach Unterhalt und Verwaltung", trend: "+3.1 %", positive: true },
  { id: "leerstand", label: "Leerstandsquote", value: "2.4 %", note: "3 von 126 Einheiten", trend: "−0.6 Pkt.", positive: true },
  { id: "wert", label: "Portfolio-Wert", value: "CHF 112'400'000", note: "Verkehrswert, Schätzung 06/2026", trend: "+1.8 %", positive: true },
];

export type CashflowRow = { month: string; einnahmen: number; ausgaben: number; netto: number };
export const CASHFLOW: CashflowRow[] = [
  { month: "Nov 25", einnahmen: 441200, ausgaben: 228400, netto: 212800 },
  { month: "Dez 25", einnahmen: 439800, ausgaben: 261900, netto: 177900 },
  { month: "Jan 26", einnahmen: 444600, ausgaben: 236100, netto: 208500 },
  { month: "Feb 26", einnahmen: 445100, ausgaben: 219700, netto: 225400 },
  { month: "Mär 26", einnahmen: 447300, ausgaben: 254800, netto: 192500 },
  { month: "Apr 26", einnahmen: 449900, ausgaben: 231200, netto: 218700 },
  { month: "Mai 26", einnahmen: 431200, ausgaben: 224600, netto: 206600 },
  { month: "Jun 26", einnahmen: 438900, ausgaben: 247300, netto: 191600 },
  { month: "Jul 26", einnahmen: 447500, ausgaben: 233800, netto: 213700 },
  { month: "Aug 26", einnahmen: 452300, ausgaben: 262500, netto: 189800 },
  { month: "Sep 26", einnahmen: 458700, ausgaben: 226900, netto: 231800 },
  { month: "Okt 26", einnahmen: 482350, ausgaben: 241700, netto: 240650 },
];

export type Holding = { id: string; name: string; use: "Wohnen" | "Gewerbe" | "Gemischt"; value: number; target: number; actual: number; vacancy: number; yield: number; trend: number[] };
export const HOLDINGS: Holding[] = [
  { id: "p1", name: "Seefeldstrasse 12, Zürich", use: "Wohnen", value: 38200000, target: 1520000, actual: 1498000, vacancy: 1.4, yield: 4.1, trend: [4.0, 4.0, 4.1, 4.0, 4.1, 4.1] },
  { id: "p2", name: "Bahnhofstrasse 4, Zürich", use: "Gemischt", value: 31500000, target: 1890000, actual: 1801000, vacancy: 4.7, yield: 5.6, trend: [5.9, 5.8, 5.7, 5.6, 5.5, 5.6] },
  { id: "p3", name: "Seestrasse 41, Küsnacht", use: "Wohnen", value: 24800000, target: 1180000, actual: 1172000, vacancy: 0.7, yield: 4.5, trend: [4.3, 4.4, 4.4, 4.5, 4.5, 4.5] },
  { id: "p4", name: "Lindenhof 3, Zürich", use: "Wohnen", value: 11600000, target: 612000, actual: 574000, vacancy: 6.2, yield: 5.1, trend: [5.4, 5.3, 5.2, 5.0, 5.0, 5.1] },
  { id: "p5", name: "Rebbergweg 8, Männedorf", use: "Wohnen", value: 6300000, target: 318000, actual: 311000, vacancy: 2.2, yield: 4.9, trend: [4.7, 4.8, 4.8, 4.9, 4.9, 4.9] },
];

export const PAYOUT = {
  month: "November 2026",
  date: "27.11.2026",
  amount: 187400,
  items: [
    { label: "Mieteinnahmen Oktober (Ist)", amount: 482350 },
    { label: "Unterhalt und Reparaturen", amount: -118900 },
    { label: "Verwaltungshonorar", amount: -19300 },
    { label: "Nebenkosten-Akonto Rückstellung", amount: -156750 },
  ],
};
