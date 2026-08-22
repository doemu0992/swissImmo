/* ============================================================
   DIE PETROL-PALETTE (aus fw/_tailwind_palette.html, E0.2)

   Bis E0.2 stand diese Palette in einem <script>-Block und wurde dem
   Tailwind-CDN zur Laufzeit im Browser untergeschoben. Seit der Bau im
   Repo läuft, gehört sie hierher — derselbe Inhalt, nur zur Bauzeit
   statt bei jedem Seitenaufruf.

   WARUM DIE RAMPEN UMDEFINIERT WERDEN UND NICHT DIE VORLAGEN
   Am 20.08.2026 gemessen: 7490 fest verdrahtete Farbklassen in 176
   Vorlagen. Sie einzeln umzustellen hiesse Wochen mit einem zweifarbigen
   Zustand dazwischen. Hier zeigen dieselben Klassennamen einfach woanders
   hin: aus `bg-indigo-600` wird die Markenfarbe.

   DIE RAMPEN SIND AN DIE TOKENS GEBUNDEN
   indigo-600 = --ds-brand, indigo-700 = --ds-brand-600, slate-200 =
   --ds-line, slate-500 = --ds-faint, slate-600 = --ds-muted, slate-900 =
   --ds-ink. core/tests/test_palette.py prüft das nach.

   DIE HELLIGKEITSTREPPE BLEIBT
   Jede Stufe behält ungefähr die Helligkeit ihrer Tailwind-Vorlage —
   verändert wird der Farbton, nicht die Ordnung.

   WAS DAS NICHT LÖST
   Den Dunkelmodus. Tailwind-Klassen sind statisch; `bg-white` bleibt
   weiss. Die Komponentenschicht (fw-*) ist der Weg dorthin.
   ============================================================ */
module.exports = {
  /* Markenfarbe — Petrol. */
  indigo:  {50:'#eef7f6',100:'#d9efed',200:'#b3dedb',300:'#7fc6c1',400:'#46a49d',500:'#17847d',600:'#0f6f6a',700:'#0b5450',800:'#0a4441',900:'#093734'},
  /* `violet` steht im Bestand fast nur neben indigo (Verläufe im
     Aktenkopf) — eine Stufe kühler, damit der Verlauf Verlauf bleibt. */
  violet:  {50:'#eef7f7',100:'#d7eeef',200:'#aeddde',300:'#79c3c6',400:'#3fa0a6',500:'#158088',600:'#0d6a74',700:'#0a505a',800:'#09414a',900:'#08343c'},
  /* Graustufen, petrolgetönt statt blaugrau. */
  slate:   {50:'#f4f7f7',100:'#eaf0f0',200:'#dde6e8',300:'#c2d2d4',400:'#8ba4aa',500:'#5c757c',600:'#4c6169',700:'#33474d',800:'#1c3239',900:'#0e2227'},
  /* `gray` und `zinc` werden im Bestand wie slate benutzt — dieselbe
     Rampe, damit nicht zwei Grautöne nebeneinander stehen. */
  gray:    {50:'#f4f7f7',100:'#eaf0f0',200:'#dde6e8',300:'#c2d2d4',400:'#8ba4aa',500:'#5c757c',600:'#4c6169',700:'#33474d',800:'#1c3239',900:'#0e2227'},
  /* Semantische Farben: dieselben Töne wie --ds-good/-warn/-crit/-info.
     Rot bleibt Rot — eine Warnung in Petrol wäre keine Warnung mehr. */
  emerald: {50:'#e0f2e5',100:'#c6e6cf',200:'#9bd3ac',300:'#6bba81',400:'#3f9d5b',500:'#237a3d',600:'#166534',700:'#11512a',800:'#0e4123',900:'#0b341c'},
  green:   {50:'#e0f2e5',100:'#c6e6cf',200:'#9bd3ac',300:'#6bba81',400:'#3f9d5b',500:'#237a3d',600:'#166534',700:'#11512a',800:'#0e4123',900:'#0b341c'},
  amber:   {50:'#fbeeda',100:'#f6ddb4',200:'#ecc07c',300:'#dfa04a',400:'#c97f20',500:'#b06a10',600:'#a35a09',700:'#834707',800:'#693906',900:'#552e05'},
  orange:  {50:'#fbeeda',100:'#f6ddb4',200:'#ecc07c',300:'#dfa04a',400:'#c97f20',500:'#b06a10',600:'#a35a09',700:'#834707',800:'#693906',900:'#552e05'},
  rose:    {50:'#fbe6e9',100:'#f6ccd2',200:'#eb9ea9',300:'#de7080',400:'#cf4459',500:'#c22e43',600:'#b32133',700:'#911a29',800:'#751521',900:'#5e111b'},
  red:     {50:'#fbe6e9',100:'#f6ccd2',200:'#eb9ea9',300:'#de7080',400:'#cf4459',500:'#c22e43',600:'#b32133',700:'#911a29',800:'#751521',900:'#5e111b'},
  sky:     {50:'#e0eff8',100:'#c2dff1',200:'#8ec3e4',300:'#5aa5d3',400:'#2a83bb',500:'#0f6ba4',600:'#0b5c8f',700:'#094a73',800:'#083c5e',900:'#06304b'},
  blue:    {50:'#e0eff8',100:'#c2dff1',200:'#8ec3e4',300:'#5aa5d3',400:'#2a83bb',500:'#0f6ba4',600:'#0b5c8f',700:'#094a73',800:'#083c5e',900:'#06304b'},
};
