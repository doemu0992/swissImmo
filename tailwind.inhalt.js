/* Wo Tailwind nach Klassennamen sucht.

   Die .py-Dateien sind kein Versehen: Views und Vorlagen-Tags setzen
   Klassen als Zeichenketten zusammen ('bg-amber-50 text-amber-700').
   Fehlen sie hier, baut Tailwind sie nicht — und die Chips sind farblos.
   Beim CDN fiel das nie auf, weil es zur Laufzeit im Browser übersetzte. */
module.exports = [
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
