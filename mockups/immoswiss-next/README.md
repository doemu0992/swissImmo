# immoswiss — Dashboard-Mockup (Next.js)

Rein visuelles Mockup des Haupt-Dashboards mit Dummy-Daten. Keine Backend-Anbindung.

**Stack:** Next.js 14 (App Router) · React 18 · Tailwind CSS 3 · shadcn/ui (Komponenten im
Projekt, `src/components/ui`) · lucide-react · recharts · TypeScript.

```bash
cd mockups/immoswiss-next
npm install
npm run dev        # http://localhost:3000
npm run build      # Typprüfung + Produktionsbau
```

## Aufbau

```
src/
  app/                 layout.tsx (Sidebar, Top-Bar, Mobile-Nav) · page.tsx (Dashboard) · globals.css (Tokens)
  lib/
    mock-data.ts       ALLE Dummy-Daten und ihre Typen — später durch Server-Daten ersetzen
    utils.ts           cn()
  components/
    ui/                shadcn/ui: card, badge, button, input, avatar, tabs, dialog, dropdown-menu, table, select
    layout/            logo, sidebar, mobile-nav, topbar
    dashboard/         page-header, kpi-grid, kpi-card, sparkline,
                       revenue-chart (Liniendiagramm), appointments-card, occupancy-chart (Donut)
```

## Rollen-Screens (statisch, Dummy-Daten, nur lokaler State)

| Route | Rolle | Inhalt | Daten |
|---|---|---|---|
| `/tickets` | Bewirtschafter | Kanban (Neu · In Bearbeitung · Wartet auf Dritte · Erledigt) oder Liste, Suche, Filter-Chips, Statuswechsel per Menü, Dialoge «Neues Ticket» und «Mieter kontaktieren» | `lib/tickets-data.ts` |
| `/kalender` | Bewirtschafter | Monatsraster Mo–So (Okt./Nov. 2026 mit Terminen), Monatswechsel, Agenda «Heute / Diese Woche»; auf dem Telefon Agenda statt Raster | `lib/calendar-data.ts` |
| `/finanzen` | Buchhalter | Tabs Debitoren (KPIs, Ampel mit Text, Filter, Sortierung, Auswahl, Export-Menü, Pagination) · Kreditoren (Stepper) · Mahnwesen · NKA (Stepper) | `lib/finance-data.ts` |
| `/portfolio` | Eigentümer | KPIs, Cashflow-Liniendiagramm (6/12 Monate), Donut (Liegenschaft/Nutzung), Performance-Tabelle mit Sparkline, Karte «Auszahlung November» | `lib/portfolio-data.ts` |

Neue Bausteine: `ui/dialog`, `ui/dropdown-menu` (Radix), `ui/table` (scrollt im eigenen Container), `ui/select` (nativer Select, Textarea, Field),
`shared/stepper`, `shared/person-avatar`, `shared/page-title`, `shared/placeholder-page`; Formatierung mit Apostroph in `lib/format.ts`.
Die Mobile-Navigation scrollt bei 9 Einträgen in sich. Zusatz-Token `--chart-5` (Donut mit 5 Segmenten).
Stolperstein: `.sr-only` ist `position:absolute` — Scroll-Container (Tabellen, Board) brauchen `relative`, sonst entsteht Seitenüberlauf.

## Design

- **Farben als Tokens** (`globals.css`, shadcn-Konvention: HSL-Kanäle). Dunkel ist Standard
  (`<html class="dark">`), Hell ist vollständig definiert. Palette «Navy Mirage» #141E30 … #35577D.
- **60-30-10:** 60 % Navy-Flächen (`background`, `card`), 30 % Strukturblau (`border`, `secondary`, `brand`),
  10 % Akzent (`primary`) und Zustandsfarben (`success`, `warning`, `destructive`).
- **Trendfarbe folgt der Bewertung, nicht der Richtung** (`goodWhen` in `mock-data.ts`): «+4 offene Reparaturen» ist rot.
- **Initialen statt Fotos** in Avataren (Mieterdaten, DSG).
- Diagrammfarben kommen aus `--chart-1…4`; Hell/Dunkel schalten also ohne Codeänderung um.
- Responsiv: Sidebar ab 1024 px, darunter schwebende Glas-Leiste; Raster 1 / 2 / 4 Spalten.

## Hinweise

- «Immobilien», «Mieter», «Dokumente», «Einstellungen» zeigen auf eine «In Arbeit»-Platzhalterseite (`components/shared/placeholder-page.tsx`), damit es keine 404 gibt.
- shadcn/ui-Komponenten wurden von Hand im Stil der offiziellen Quellen angelegt; `components.json` ist
  vorhanden, damit `npx shadcn@latest add …` später weitere Bausteine ergänzen kann.
- Schrift: Plus Jakarta Sans per Google-Fonts-`<link>` (Fallback: System-Sans).
