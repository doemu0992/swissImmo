/* Wo Tailwind nach Klassennamen sucht.

   Die .py-Dateien sind kein Versehen: Views und Vorlagen-Tags setzen
   Klassen als Zeichenketten zusammen ('bg-amber-50 text-amber-700').
   Fehlen sie hier, baut Tailwind sie nicht — und die Chips sind farblos.
   Beim CDN fiel das nie auf, weil es zur Laufzeit im Browser übersetzte. */
/* TESTDATEIEN SIND AUSGENOMMEN (E2.49)

   ACHTUNG BEIM SCHREIBEN DIESES KOMMENTARS: Ein Glob wie
   `./core/<zwei Sterne>/<stern>.py` enthaelt die Zeichenfolge, die einen
   Blockkommentar SCHLIESST. Steht er hier ausgeschrieben, endet der
   Kommentar mitten im Satz, der Rest wird zu Code, und `npm run css:alle`
   bricht mit `SyntaxError: Unexpected token (9:15)` ab — der Bau laeuft dann
   gar nicht mehr, und die zwei Zeilen im Aufrufskript melden nur «bitte von
   Hand». Genau so ist die erste Fassung dieser Aenderung eingetroffen.
   Deshalb stehen Globs in diesem Kommentar umschrieben.

   Das Sammelmuster fuer die Anwendung erfasste auch `core/tests/`. Dort
   stehen Farbklassen als BEISPIELE — in Waechtern, die gerade belegen, dass
   eine Klasse NICHT vorkommen soll. Tailwind kennt den Unterschied nicht und
   baut Regeln daraus.

   GEMESSEN: Selektormengen vor und nach dem Bau verglichen — es sind ZWOELF
   Selektoren, nicht zwei:

     bg-indigo-600            hover:bg-emerald-600   hover:bg-indigo-700
     border-white/10          m-1                    ring
     from-[#122b31]           from-[#15182e]
     to-[#0a1c20]             to-[#0d0f1e]
     [-2:-1]                  [label:stelle]

   Jeder einzeln nachgesehen: KEINER kommt ausserhalb der Tests vor.
   Die Verlaufsfarben stehen in `test_palette.py`, wo sie belegen, wie die
   Seitenleiste FRUEHER aussah. Die letzten zwei sind gar keine Klassen,
   sondern Python-Ausschnitte (`html[label:stelle]`), die Tailwind fuer
   welche gehalten hat.

   NICHT BETROFFEN, obwohl aehnlich benannt: `-m-1`, `ring-1`, `ring-2` und
   `ring-inset` bleiben — die stehen in echten Vorlagen und in `crm/admin.py`.
   Nachgesehen, weil `.m-1` und `.ring` auf den ersten Blick nach einem
   Verlust aussehen.

   (Ein Zwischenstand behauptete, `bg-indigo-600` bleibe, weil es in
   `crm/admin.py` und `rentals/admin.py` stehe. Nachgemessen stimmt das
   nicht: Dort stehen `bg-indigo-50`, `text-indigo-600` und
   `ring-indigo-600/20` — `bg-indigo-600` steht nur in
   `faelle/test_bereichsgestaltung.py`, und es ist weg.)

   Wenig Gewicht, aber die falsche Richtung: Ein Waechter, der eine Klasse
   verbietet, sorgt dafuer, dass sie gebaut wird. Und wer spaeter misst,
   welche Farben die Anwendung noch traegt, zaehlt seine eigenen Tests mit.

   Die `!`-Ausnahmen stehen VOR den Mustern, damit sie greifen. */
module.exports = [
  '!./*/test_*.py',
  '!./*/tests/**/*.py',
  '!./**/test_*.py',
  '!./**/tests/**/*.py',
  './core/templates/**/*.html',
  './templates/**/*.html',
  './core/**/*.py',
  './faelle/**/*.py',
  './finance/**/*.py',
  './portfolio/**/*.py',
  './rentals/**/*.py',
  './crm/**/*.py',
  './tickets/**/*.py',
  './mietprozess/**/*.py',
];
