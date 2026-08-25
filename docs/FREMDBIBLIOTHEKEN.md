# Fremdbibliotheken im Repo

Fünf Bibliotheken kamen bis E2.23 zur Laufzeit von `cdn.jsdelivr.net` und
`unpkg.com`. Drei der vier Vorlagen, die sie luden, sind öffentlich: jeder
Aufruf schickte die IP-Adresse eines Mieters oder Bewerbers an einen Dritten,
und die Seite brach, wenn das CDN nicht erreichbar war.

Vier liegen jetzt unter `static/`. Die fünfte ist **weggefallen** — siehe
unten. `core/tests/test_keine_fremdquellen.py` sperrt beide Hosts;
`ANDERE_FREMDQUELLEN` ist seither leer.

## Was im Repo liegt

Jede Datei wurde **byteweise gegen das npm-Paket verglichen**, nicht anhand
ihres Banners eingeordnet. Der Unterschied ist nicht theoretisch — siehe
«Die Fassung steht nicht drauf» unten.

| Datei unter `static/` | npm-Paket | Datei im Paket | Vergleich |
|---|---|---|---|
| `js/alpine.min.js` | `alpinejs@3.13.3` | `dist/cdn.min.js` | byteidentisch |
| `js/signature_pad.umd.min.js` | `signature_pad@4.1.7` | `dist/signature_pad.umd.min.js` | byteidentisch |
| `js/chart.umd.js` | `chart.js@4.5.1` | `dist/chart.umd.js` | byteidentisch |
| `js/vue.global.prod.js` | `vue@3.5.41` | `dist/vue.global.prod.js` | byteidentisch |

Die Fassungen stehen in `package.json` **ohne Caret**. Das ist Absicht: Die
Dateien liegen im Repo, also muss `npm install` genau die holen, die
ausgeliefert wird. Sonst wäre der Vergleich oben still falsch. Dieselbe
Schreibweise wie `tailwindcss` und `@playwright/test` daneben.

npm ist hier nur der **Beschaffungsweg**, keine Laufzeitabhängigkeit. Die
Anwendung lädt nichts aus `node_modules`; sie lädt aus `static/`.

`core/tests/test_vendor_dateien.py` prüft, dass jede `{% static %}`-Adresse
auf eine vorhandene Datei zeigt und dass die Fassungen ohne Caret stehen.

## bootstrap-icons: nicht geholt, sondern entfernt

`modern_base.html` lud bootstrap-icons seit jeher von `cdn.jsdelivr.net`.
E2.23 wollte die Datei ins Repo holen. Beim Prüfen fiel auf:

> **Keine** Vorlage, kein View und kein Skript im ganzen Bestand benutzt eine
> `bi-`-Klasse. Null Treffer.

Die Symbole dieser Hülle kommen aus Font Awesome — `fa-solid fa-buildings`
steht 19 Zeilen unter dem alten Verweis, und `css/fontawesome.css` wird über
`_assets_aussen.html` geladen. Der bootstrap-icons-Verweis war ein Rest aus
einer früheren Fassung.

Was er gekostet hat, und was das Vendoring gekostet hätte:

| | |
|---|---|
| bei **jedem** Aufruf von `/schaden/melden/` geladen | 98 257 B CSS |
| davon benutzte Symbole | **0 von 2050** |
| zusätzlich ins Repo gelegt (Schriften `woff2` + `woff`) | 306 960 B |
| Summe im Repo | 405 217 B (396 KB) |

`/schaden/melden/` ist die öffentliche Schadenmeldung — die Seite, die Mieter
aufrufen, oft mobil. Der Verweis ist deshalb **entfernt** statt vendort. Das
erledigt den CDN-Aufruf genauso und spart 98 KB pro Aufruf dazu.

`test_vendor_dateien.test_bootstrap_icons_kommt_nicht_zurueck` hält den
Zustand fest — der Name darf in Vorlagen nur noch im Erklärtext stehen, nicht
in einem `<link>`, und nicht in `package.json`.

Wer die Symbole wirklich braucht: über npm nach `static/` holen, in
`package.json` ohne Caret eintragen, `NICHT_GEHOLT` → `VENDOR` verschieben —
und die Pfadkorrektur nicht vergessen (nächster Abschnitt).

### Die Pfadkorrektur, die kein Test bemerkt hätte

bootstrap-icons sucht seine Schriften unter `./fonts/` — relativ zur
CSS-Datei. Im npm-Paket liegen sie dort. Bei uns läge die CSS unter
`static/css/` und die Schriften unter `static/fonts/`, also eine Ebene höher:

```
-  src: url("./fonts/bootstrap-icons.woff2?…")
+  src: url("../fonts/bootstrap-icons.woff2?…")
```

Ohne diese Zeile bliebe **jedes** Icon leer. Ein fehlender Schrift-Download
ergibt keinen Fehler, keine Warnung und keine rote Zeile im Protokoll — nur
leere Kästchen, die aussehen wie ein Gestaltungsentscheid. (Die gelieferte
Fassung hatte die Korrektur; sie ist hier festgehalten, weil sie bei jeder
Aktualisierung erneut nötig wäre. `css/fontawesome.css` macht es mit
`../webfonts/` schon genauso.)

### Die Fassung steht nicht drauf

Der Vollständigkeit halber, weil es beim Prüfen einmal danebenging: Die
gelieferte `bootstrap-icons.css` trug das Banner

```
 * Bootstrap Icons v1.10.5
 * Copyright 2019-2023 The Bootstrap Authors
```

und war trotzdem **1.11.0**. Upstream hat in Release 1.11.0 vergessen, das
Banner mitzuziehen; die 1.11.0 aus npm trägt dasselbe Banner Zeichen für
Zeichen. Nachweisbar war die Fassung an der Prüfsumme der beiden
Schriftdateien und am Cache-Anhänger im `src:`.

**Der naheliegende Vergleich taugt dafür nicht:** Über die Icon-Regeln lässt
sich die Fassung *nicht* bestimmen — 1.11.0 bis 1.11.3 führen alle exakt
dieselben 2050 Regeln. Wer daraus «1.11.3» schliesst, hat eine Messung
benutzt, deren Auflösung nicht reicht. Genau das ist beim ersten Durchgang
passiert, und es stand schon zwischenzeitlich als Befund im Protokoll.

## Vue: der Produktionsbau, unter seinem eigenen Namen

Bis E2.23 lud das Bewerbungsformular `unpkg.com/vue@3/dist/vue.global.js` —
unter diesem Pfad liefert unpkg den **Entwicklungsbau**: 591 KB, mit
Warnungen und Devtools-Anbindung, auf einer Seite, die Bewerber ausfüllen.

Im Repo liegt jetzt `vue.global.prod.js` (166 KB). Das ist eine bewusste
Änderung, kein Nebeneffekt des Umzugs.

Die gelieferte Fassung hiess `vue.global.js` — sie *war* der Produktionsbau,
trug aber den Namen, den Vue für den Entwicklungsbau vergibt. Umbenannt,
damit der nächste Vergleich gegen das npm-Paket nicht dieselbe Verwirrung
stiftet wie dieser hier.

## Aktualisieren

1. Fassung in `package.json` hochsetzen (**ohne** Caret) und `npm install`.
2. Datei aus `node_modules/` nach `static/` kopieren.
3. `VENDOR` in `core/tests/test_vendor_dateien.py` und diese Tabelle nachführen.
4. `python manage.py test core.tests.test_vendor_dateien core.tests.test_keine_fremdquellen`
