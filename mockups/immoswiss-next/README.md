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
    ui/                shadcn/ui: card, badge, button, input, avatar, tabs
    layout/            logo, sidebar, mobile-nav, topbar
    dashboard/         page-header, kpi-grid, kpi-card, sparkline,
                       revenue-chart (Liniendiagramm), appointments-card, occupancy-chart (Donut)
```

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

- Die Navigationseinträge außer «Dashboard» verweisen auf noch nicht vorhandene Seiten (404).
- shadcn/ui-Komponenten wurden von Hand im Stil der offiziellen Quellen angelegt; `components.json` ist
  vorhanden, damit `npx shadcn@latest add …` später weitere Bausteine ergänzen kann.
- Schrift: Plus Jakarta Sans per Google-Fonts-`<link>` (Fallback: System-Sans).
