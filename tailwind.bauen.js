/* Tailwind-Bau (v4): erzeugt static/css/tailwind.css (`npm run css`).

   Tailwind 4 liest `content` aus der JS-Konfiguration nicht mehr, und `@source not` kennt keine Globs für Dateien.
   Dieses Skript bleibt deshalb bei der alten Quelle der Wahrheit, `tailwind.inhalt.js` (Muster mit `!` für Ausnahmen:
   Testdateien), löst sie zu einzelnen Dateien auf und schreibt daraus eine Eingabedatei mit einem `@source` je Datei. */
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const wurzel = __dirname;
const muster = require('./tailwind.inhalt.js');
const ja = muster.filter((m) => !m.startsWith('!'));
const nein = muster.filter((m) => m.startsWith('!')).map((m) => m.slice(1));

const alle = (liste) => new Set(liste.flatMap((m) => fs.globSync(m, { cwd: wurzel })).map((f) => f.split(path.sep).join('/')));
const verboten = alle(nein);
const dateien = [...alle(ja)].filter((f) => !verboten.has(f) && fs.statSync(path.join(wurzel, f)).isFile()).sort();

const kopf = fs.readFileSync(path.join(wurzel, 'tailwind.eingang.css'), 'utf8');
const eingabe = path.join(wurzel, '.tailwind-eingabe.css');
fs.writeFileSync(eingabe, kopf + '\n' + dateien.map((f) => `@source "./${f}";`).join('\n') + '\n');
try {
  const bin = path.join(wurzel, 'node_modules', '.bin', 'tailwindcss');
  const r = spawnSync(bin, ['-i', eingabe, '-o', path.join(wurzel, 'static/css/tailwind.css'), '--minify'], { stdio: 'inherit', cwd: wurzel });
  if (r.status !== 0) process.exitCode = r.status || 1;
} finally {
  fs.rmSync(eingabe, { force: true });
}
console.log(`${dateien.length} Dateien gelesen.`);
