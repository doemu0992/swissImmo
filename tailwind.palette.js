/* ============================================================
   DIE NAVY-PALETTE «Navy Mirage» (#141E30 / #35577D; seit 23.10.2026 nach mockups/konzept-v9-vergleich.html, vorher Petrol aus konzept-v8)

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
  /* Markenfarbe — Navy (#35577D). */
  indigo:  {50:'#f0f4f9',100:'#e3ebf5',200:'#c4d4e8',300:'#94b0d0',400:'#6286b0',500:'#46688f',600:'#35577d',700:'#27415f',800:'#1d3250',900:'#141e30'},
  /* `violet` steht im Bestand fast nur neben indigo (Verläufe im
     Aktenkopf) — eine Stufe kühler, damit der Verlauf Verlauf bleibt. */
  violet:  {50:'#eef3f9',100:'#dde7f3',200:'#bccee3',300:'#8eaccb',400:'#5f82ab',500:'#3f6591',600:'#2e5079',700:'#233e5f',800:'#1b304a',900:'#121f33'},
  /* Graustufen, navygetönt. */
  slate:   {50:'#f6f8fb',100:'#eaeff6',200:'#dde4ee',300:'#c6d1e0',400:'#93a4bb',500:'#5a6980',600:'#43526a',700:'#2f3d54',800:'#1f2b40',900:'#141e30'},
  /* `gray` und `zinc` werden im Bestand wie slate benutzt — dieselbe
     Rampe, damit nicht zwei Grautöne nebeneinander stehen. */
  gray:    {50:'#f6f8fb',100:'#eaeff6',200:'#dde4ee',300:'#c6d1e0',400:'#93a4bb',500:'#5a6980',600:'#43526a',700:'#2f3d54',800:'#1f2b40',900:'#141e30'},
  /* Semantische Farben: dieselben Töne wie --ds-good/-warn/-crit/-info.
     Rot bleibt Rot — eine Warnung in Petrol wäre keine Warnung mehr. */
  emerald: {50:'#e3f3e8',100:'#c6e6cf',200:'#9bd3ac',300:'#6bba81',400:'#3f9d5b',500:'#237a3d',600:'#15683a',700:'#11512a',800:'#0e4123',900:'#0b341c'},
  green:   {50:'#e3f3e8',100:'#c6e6cf',200:'#9bd3ac',300:'#6bba81',400:'#3f9d5b',500:'#237a3d',600:'#15683a',700:'#11512a',800:'#0e4123',900:'#0b341c'},
  amber:   {50:'#fbf0de',100:'#f6ddb4',200:'#ecc07c',300:'#dfa04a',400:'#c97f20',500:'#b06a10',600:'#955708',700:'#834707',800:'#693906',900:'#552e05'},
  orange:  {50:'#fbf0de',100:'#f6ddb4',200:'#ecc07c',300:'#dfa04a',400:'#c97f20',500:'#b06a10',600:'#955708',700:'#834707',800:'#693906',900:'#552e05'},
  rose:    {50:'#fbe9eb',100:'#f6ccd2',200:'#eb9ea9',300:'#de7080',400:'#cf4459',500:'#c22e43',600:'#b0222e',700:'#911a29',800:'#751521',900:'#5e111b'},
  red:     {50:'#fbe9eb',100:'#f6ccd2',200:'#eb9ea9',300:'#de7080',400:'#cf4459',500:'#c22e43',600:'#b0222e',700:'#911a29',800:'#751521',900:'#5e111b'},
  sky:     {50:'#e2f1ef',100:'#c6e3df',200:'#9ccdc7',300:'#6bb1a9',400:'#3b9189',500:'#17766f',600:'#0e6b65',700:'#0a5551',800:'#08443f',900:'#063531'},
  blue:    {50:'#e2f1ef',100:'#c6e3df',200:'#9ccdc7',300:'#6bb1a9',400:'#3b9189',500:'#17766f',600:'#0e6b65',700:'#0a5551',800:'#08443f',900:'#063531'},
};
