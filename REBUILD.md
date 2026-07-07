# Fairwalter-Rebuild — Blaupause

Ziel: gleiche Struktur, Funktionen und Design wie Fairwalter (my.fairwalter.ch),
aufgesetzt auf das bestehende swissImmo-Backend (Modelle + APIs bleiben).
Referenz: 10 Original-Screenshots des Nutzers (Juli 2026).

## Design-System (aus den Screenshots)
- Sidebar: fast-schwarzes Navy (#161926-Bereich), Logo oben, "Globaler Filter"-Box,
  aktiver Punkt = GEFÜLLTER Indigo-Button, Sektionen als graue UPPERCASE-Labels
- Akzent: Indigo (#5661F2-Bereich) — Zahlen, Links, Primärbuttons
- Topbar: weiss — Suche links, Glocke, KI-Button, "Hallo, <Name>" + Avatar
- Inhalt: grosse schwarze Seitentitel (h1), Sektionstitel mit ⓘ-Hilfe-Icon,
  weisse Karten (rounded-xl, border-slate-200), Status-Pills
  (grün gefüllt=Bezahlt/Aktiv, amber soft=Teilbezahlt, outline=Offen,
  rose soft=Überbezahlt/Gekündigt/Leerstand)
- Listen = echte Datentabellen: Filterzeile (Suche + Dropdowns), Bulk-Aktionen,
  sortierbare Spalten, Checkbox-Spalte, Kebab-Menü, Auge=Ansehen
- Details = Overlay/Seite mit Breadcrumb-Pfad (indigo Links), Tabs
  (z.B. Allgemein/Personen/Kaution), Felder in Rahmen-Boxen, Bearbeiten-Button
- Assistenten (Kündigung, Mitteilung): Schritte links, Formular Mitte,
  LIVE-DOKUMENT-VORSCHAU rechts (Brief/E-Mail)

## Ziel-Navigation (1:1 Fairwalter)
Dashboard · Erste Schritte · Liegenschaften · Objekte · Dokumente · Kommunikation
VERWALTUNG: Personen · Verträge · Mietzins
FINANZEN: Buchhaltung · Bankkonten · Bankabgleich · Sollstellung Miete ·
          Debitoren · Kreditoren · Mahnwesen · Nebenkosten · Hypotheken
GEBÄUDE:  Assets · Dienstleister · Schadensfälle
+ Globaler Filter (Liegenschaft) über allem

## Dashboard (Desktop-Referenz IMG_5981)
- Portfolio: KPI-Karten mit Icon-Chip + grosser Indigo-Zahl; Mietobjekte-Karte
  mit Breakdown (Wohnen/Parkplatz/Gewerbe), Verträge-Karte mit Status-Breakdown
  (Beendet/Aktiv grün/Gekündigt rot/Zukünftig amber)
- Leerstand-Karte mit Tabs: Leerstand [n] / Gekündigt [n] / Bevorstehend [n]
- Aufgaben-Karte: Meine/Alle Aufgaben, +Neu, Checkbox-Items mit Priorität+Datum

## Etappen
A) Shell (/neu/): Sidebar+Topbar+Globaler Filter + neues Dashboard  ← IN ARBEIT
B) Listen: Liegenschaften, Objekte, Personen, Verträge, Debitoren, Kreditoren
   als Datentabellen; Details mit Breadcrumb+Tabs (bestehende Dossiers ausbauen)
C) Finanzen: Buchhaltung, Sollstellung, Nebenkosten auf neue Shell
D) Neue Module: Mahnwesen (Stufen), Bankabgleich (camt + QR-IBAN/QRR),
   Dokumente zentral + "Erstellbare Dokumente" je Vertrag, Kommunikation
   (Mitteilungs-Assistent mit E-Mail/Brief-Vorschau), Kündigungs-Assistent,
   Erste Schritte, Bankkonten, Hypotheken, Aufgaben-Modul (manuelle Aufgaben)

Alte App bleibt unter /app/ bis zur Ablösung; /neu/ wächst Etappe für Etappe.
Nicht fertige Navigationspunkte verlinken übergangsweise auf /app/?tab=…
