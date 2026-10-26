/* ============================================================
   DIE EMBER-PALETTE (seit 26.10.2026 nach mockups/immoswiss-ember.html: warmes Hell, Tinte #17181B, Akzent Orange; Schrift-Orange #B04416 fuer AA; vorher Navy Mirage, davor Petrol)

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
  /* Markenfarbe — Ember-Orange (#B04416 als Schrift, #E0642F als Flaeche). */
  indigo:  {50:'#fdf3ed',100:'#fbe7dc',200:'#f6c8ae',300:'#f0a27a',400:'#e8804f',500:'#d0602b',600:'#b04416',700:'#8a3410',800:'#6b290e',900:'#4f1e0b'},
  /* `violet` steht im Bestand fast nur neben indigo (Verläufe im
     Aktenkopf) — eine Stufe kühler, damit der Verlauf Verlauf bleibt. */
  violet:  {50:'#fdf4ef',100:'#f9e4d8',200:'#f2c5aa',300:'#e9a079',400:'#de7c4a',500:'#c75d2a',600:'#a84418',700:'#833511',800:'#64290e',900:'#491e0b'},
  /* Graustufen, warm getönt. */
  slate:   {50:'#f6f5f3',100:'#f3f1ee',200:'#e7e5e1',300:'#d6d3ce',400:'#9e9b94',500:'#62656d',600:'#5d6068',700:'#3c3e44',800:'#26272b',900:'#17181b'},
  /* `gray` und `zinc` werden im Bestand wie slate benutzt — dieselbe
     Rampe, damit nicht zwei Grautöne nebeneinander stehen. */
  gray:    {50:'#f6f5f3',100:'#f3f1ee',200:'#e7e5e1',300:'#d6d3ce',400:'#9e9b94',500:'#62656d',600:'#5d6068',700:'#3c3e44',800:'#26272b',900:'#17181b'},
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
