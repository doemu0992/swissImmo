# Zeichensatz — 61 Zeichen mit fester Bedeutung

> Grundlage: Entscheid **D5** in `docs/ENTSCHEIDE-V7.md`, Befund **B8** in
> `docs/UX-ANALYSE-V7.md`.

## Warum überhaupt

Gemessen am Bestand: **207 verschiedene Font-Awesome-Klassen, 1136 Vorkommen.**
Davon werden **90 Zeichen genau einmal** benutzt.

Gezählt wird an allen drei Orten, an denen ein Zeichen gewählt wird: in
`core/templates/` (190), in den Admin-Vorlagen unter `templates/` (7) und in
**Python-Code** (72 Klassen, 17 davon in keiner Vorlage) — Kachellisten,
Termin-Arten und Gewerke stehen dort als Zeichenkette und erreichen die
Vorlage über den Kontext.

Das ist kein Zeichensatz, das ist eine Sammlung. Die Folge sieht man, wenn man
die Einzelgänger nebeneinanderlegt: `fa-trash` und `fa-trash-can` stehen für
dasselbe, ebenso `fa-list`/`fa-list-ol`, `fa-gauge`/`fa-gauge-high` und drei
verschiedene Personengruppen-Symbole. Wer eine neue Seite baut, wählt aus 2'000
Zeichen — und trifft nie dieselbe Wahl wie der Vorgänger.

Ein Zeichen, das an zwei Orten Verschiedenes bedeutet, ist schlimmer als kein
Zeichen: Es wird gelesen, bevor der Text daneben gelesen wird.

## Der Grundsatz

**Jedes Zeichen hat genau eine Bedeutung, und jede Bedeutung genau ein
Zeichen.** Wer ein neues braucht, trägt es hier ein — mit Begründung, warum
keines der bestehenden passt.

Zeichen bilden **Handlungen und Zustände** ab, nicht Gegenstände. `fa-bed` für
ein Schlafzimmer ist ein Gegenstand; im Raumkatalog steht ohnehin der Name des
Raums daneben, und das Bett trägt nichts bei.

## Die Tabelle

### Navigation und Struktur (8)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `weiter` | Eine Ebene tiefer, Detail öffnen | `chevron-right`, `angle-right`, `arrow-right`, `arrow-right-long` |
| `zurueck` | Eine Ebene höher | `chevron-left`, `arrow-left`, `angles-left` |
| `aufklappen` | Abschnitt öffnen/schliessen | `chevron-down`, `chevron-up`, `caret-down` |
| `mehr` | Weitere Handlungen (Menü) | `ellipsis`, `ellipsis-vertical`, `bars`, `grid-2`, `layer-group` |
| `schliessen` | Dialog, Meldung oder Menü wegklicken | `xmark` (nur wo schliessend) |
| `extern` | Führt aus der Anwendung heraus | `up-right-from-square`, `arrow-up-right-from-square`, `link`, `share-nodes`, `arrow-right-from-bracket`, `right-from-bracket`, `window-maximize` |
| `suchen` | Suche | `magnifying-glass` |
| `filtern` | Auswahl einschränken | `filter`, `sliders`, `table-list`, `folder-tree` |

### Handlungen (9)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `neu` | Etwas anlegen | `plus`, `circle-plus`, `calendar-plus` |
| `bearbeiten` | Bestehendes ändern | `pen`, `pen-to-square`, `pen-nib`, `eraser` |
| `loeschen` | Entfernen | `trash`, `trash-can`, `xmark` (nur wo löschend) |
| `speichern` | Festschreiben | `floppy-disk`, `check` (nur wo speichernd) |
| `senden` | An jemanden hinausgeben | `paper-plane`, `envelope`, `envelope-open-text` (**nur ausgehend** — ein Eingang ist `dokument`), `reply`, `bullhorn`, `comments`, `phone`, `phone-volume` |
| `drucken` | Auf Papier oder als PDF | `print`, `file-pdf` |
| `kopieren` | Vervielfältigen | `copy`, `clone` |
| `hochladen` | Datei hereingeben | `upload`, `file-import`, `paperclip` |
| `herunterladen` | Datei hinausgeben | `download`, `file-export`, `file-zipper`, `file-arrow-down`, `file-csv`, `cloud-arrow-down` |

### Zustände (8)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `gut` | Erledigt, in Ordnung | `check`, `check-double`, `circle-check`, `envelope-circle-check`, `calendar-check`, `clipboard-check`, `user-check` — die `*-check` jeweils **nur wo sie einen Zustand meinen** |
| `warnung` | Beanstandet, aber nicht blockiert | `triangle-exclamation` |
| `kritisch` | Blockiert, Frist verletzt | `circle-exclamation`, `fire`, `fire-burner`, `house-crack`, `house-chimney-crack`, `house-circle-exclamation`, `cloud-bolt`, `bolt` (nicht als Gewerk «Elektro»), `file-circle-xmark`, `file-circle-minus` (beide **nur wo blockierend**, nicht als Kündigungs-Dokument) |
| `hinweis` | Erklärung, kein Handlungsbedarf | `circle-info`, `circle-question`, `lightbulb`, `note-sticky`, `flag` |
| `wartet` | Auf Dritte, auf Zeitablauf | `clock`, `hourglass-end`, `hourglass-half`, `spinner`, `circle-notch`, `user-clock`, `inbox` |
| `gesperrt` | Kein Zugriff, nicht änderbar | `lock`, `shield-halved` (**nicht** als Kaution — das ist `geld`), `shield-heart`, `user-slash`, `user-shield` |
| `offen` | Noch nicht bearbeitet | `circle` (leer) |
| `entwurf` | Angefangen, nicht gültig | `pen-ruler`, `file-pen` |

### Fachbegriffe (12)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `liegenschaft` | Gebäude, Objekt | `building`, `buildings`, `building-user`, `city`, `house`, `university`, `landmark`, `location-dot`, `map-location-dot`, `stairs` |
| `einheit` | Wohnung, Geschäftsraum, Parkplatz | `door-open`, `car`, `bed`, `bath`, `couch`, `kitchen-set` |
| `person` | Mieter, Eigentümer, Kontakt | `user`, `users`, `people-group`, `people-roof`, `people-arrows`, `address-book`, `address-card`, `id-badge`, `id-card`, `handshake`, `mobile-screen`, `user-tie` |
| `vertrag` | Mietverhältnis | `file-signature`, `file-contract`, `signature`, `person-walking-arrow-right` |
| `dokument` | Akte, Beleg | `file`, `file-lines`, `folder-open`, `book`, `clipboard-list`, `image`, `camera`, `briefcase`, `box`, `box-open`, `boxes-stacked` |
| `geld` | Betrag, Zahlung | `money-bill`, `money-bill-transfer`, `money-check-dollar`, `coins`, `sack-dollar`, `piggy-bank`, `right-left` |
| `rechnung` | Forderung, Verbindlichkeit | `file-invoice`, `file-invoice-dollar`, `receipt` |
| `bank` | Konto, Zahlungsverkehr | `building-columns`, `qrcode`, `credit-card` |
| `recht` | Gesetz, Frist, Regel | `scale-balanced`, `gavel`, `ruler` |
| `arbeit` | Reparatur, Handwerk, Gewerk | `screwdriver-wrench`, `hammer`, `broom`, `jug-detergent`, `paint-roller`, `tree`, `paw`, `list-check` |
| `schluessel` | Zutritt, Übergabe | `key`, `lock-open` |
| `zaehler` | Verbrauch, Ablesung | `gauge`, `gauge-high`, `faucet-drip`, `temperature-arrow-up` |

### Zeit und Verlauf (7)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `termin` | Datum, Kalender, Termin-Art | `calendar`, `calendar-days`, `calendar-day`, `calendar-week`, `person-walking` |
| `verlauf` | Chronik, Historie | `clock-rotate-left`, `list-ol`, `code-branch` |
| `lauf` | Wiederkehrender Vorgang | `rotate`, `arrows-rotate`, `truck-fast` |
| `bericht` | Auswertung, Zahlenbild | `chart-simple`, `chart-pie`, `chart-column`, `chart-line`, `percent`, `calculator` |
| `trend` | Richtung einer Zahl: steigt, fällt, unverändert | `arrow-trend-up`, `arrow-trend-down`, `equals`, `arrow-down-long` |
| `laedt` | Es läuft gerade — dreht sich | `circle-notch fa-spin`, `spinner` |
| `code` | Rohdaten zur Fehlersuche | `code` |

### Bedienung (1)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `einstellungen` | Konfiguration, Verhalten ändern | `gear`, `gears`, `plug`, `star`, `wand-magic-sparkles`, `robot`, `language`, `eye` (**nicht** als «sichtbar» — dafür `gut`/`gesperrt`), `hand` |

> **Warum `schliessen` dazukam (E2.40, Gegenprüfung).** Die Umstellung
> setzte `xmark` auf Schliessen-Knöpfen auf `mehr` (»Weitere Handlungen«) —
> vier Stellen —, und E2.38 hatte »Menü schliessen« in `base.html` auf
> `loeschen` gesetzt, also auf einen Papierkorb. Ein Knopf, der aussieht,
> als lösche er etwas, ist schlimmer als gar kein Zeichen.
>
> `mehr` hätte damit an zwei Orten Verschiedenes geheissen — genau der
> Fehler, gegen den diese Tabelle geschrieben ist. Wegklicken ist eine
> eigene Bedeutung; sie fehlte.

### Räume im Schadenformular (12) — entschieden in E2.51

Diese zwölf stehen bewusst **nicht** unter »Fachbegriffe«. Sie sind kein Teil
des Vokabulars der Anwendung, sondern der Katalog **einer einzigen Seite**:
`/report/<id>/`, das öffentliche Schadenformular vom Aushang im Treppenhaus.
Dort wählt ein Mieter am Handy aus zwölf Kacheln, oft in Eile — dort führt ein
Symbol das Auge schneller als zwölfmal gleich aussehender Text.

Wer sie in der Anwendung verwenden will, soll erst begründen, warum
`liegenschaft` oder `einheit` nicht reicht. Ein Katalog, der in die
Innenansicht wandert, wird zum Sonderfall-Sammelbecken.

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `kueche` | Raum: Küche | (neu, E2.51) |
| `bad` | Raum: Bad | (neu, E2.51) |
| `korridor` | Raum: Korridor | (neu, E2.51) |
| `zimmer` | Raum: Zimmer | (neu, E2.51) |
| `reduit` | Raum: Reduit | (neu, E2.51) |
| `balkon` | Raum: Balkon/Terrasse | (neu, E2.51) |
| `treppenhaus` | Raum: Treppenhaus | (neu, E2.51) |
| `waschkueche` | Raum: Waschküche | (neu, E2.51) |
| `keller` | Raum: Keller | (neu, E2.51) |
| `estrich` | Raum: Estrich | (neu, E2.51) |
| `veloraum` | Raum: Veloraum | (neu, E2.51) |
| `briefkasten` | Raum: Briefkasten | (neu, E2.51) |

### Fachliche Handlungen (4) — entschieden in E2.40

Diese drei standen unter »Noch ohne Bedeutung«. Sie sind jetzt eigene Zeichen,
weil keine der bestehenden Bedeutungen sie trägt — und weil ein falsch
zugeordnetes Zeichen schlechter ist als ein zusätzliches.

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `freigeben` | Prüfen und zur Zahlung freigeben | `stamp` |
| `storno` | Aufheben — der Beleg bleibt | `rotate-left` |
| `weiterverrechnen` | Kosten an den Mieter weitergeben | `share-from-square`, `share` |
| `meldung` | Etwas wartet auf Aufmerksamkeit | `bell` |

**`freigeben`** ist weder `speichern` (es entsteht nichts Neues) noch `gut`
(das ist ein Zustand, keine Handlung). Wer eine Rechnung freigibt, trifft eine
Entscheidung mit Geldfolge.

**`storno`** ist weder `loeschen` (der Beleg bleibt, und das ist der ganze
Punkt) noch `bearbeiten`. Buchhalterisch entsteht eine Gegenbuchung. Der Pfeil
läuft deshalb rückwärts — anders als bei `lauf`, der vorwärts läuft.

**`meldung`** ist nicht `hinweis`: Ein Hinweis erklärt, eine Meldung verlangt
Aufmerksamkeit.

`bell` stand für **zwei** Dinge, und das war richtig gemessen: das
Klingelschild in `debitoren.html` (eine Rechnungsposition) und »Neueste
Tickets« in `templates/admin/dashboard_stats.html` (eine Meldung). E2.40
nahm an, es gebe nur die erste Fundstelle — dabei fehlten die
Admin-Vorlagen im Suchbereich, genau die Verengung, gegen die der Wächter
seit E2.35 alle drei Orte misst.

Der Konflikt ist damit nicht widerlegt, sondern **aufgelöst**: Die
Rechnungsposition bekommt `dokument`, die Tickets bekommen `meldung`. Zwei
Fundstellen, zwei Bedeutungen, zwei Zeichen.

**Summe: 61 Zeichen** — 49 fuer die Anwendung, dazu die zwoelf
Raumzeichen des oeffentlichen Schadenformulars (E2.51, eigener
Abschnitt weiter unten).

> **Warum es 42 geworden sind.** Die Tabelle entstand aus der
> Häufigkeitsliste; der Wächter meldete danach Zeichen, die keiner Bedeutung
> zugeordnet waren. Fast alle liessen sich einordnen — zwei nicht.
>
> `gear`: Einstellungen sind weder eine Handlung noch ein Zustand noch ein
> Fachbegriff. Die Bedeutung fehlte schlicht.
>
> `arrow-trend-up`/`-down`/`equals`: Der erste Entwurf steckte sie unter
> `weiter` und `zurueck` — das war falsch. Nachgesehen, wo sie stehen:
> »Erhöhung möglich«, »Senkungsanspruch«, »Aktuell« (`core/views/fw/mietzins.py`)
> und die beiden Kennzahlkacheln in `buchhaltung.html`. Das ist die Richtung
> einer **Zahl**, nicht die Richtung einer **Bewegung durch die Anwendung**.
> Unter `weiter` einsortiert hiesse ein Pfeil an zwei Orten Verschiedenes —
> genau der Fehler, den die Tabelle verhindern soll. Also ein eigenes Zeichen
> `trend`, mit drei Richtungen wie `aufklappen` mit zwei.
>
> D5 sagt »~40 Zeichen«. Die Tilde ist hier der Punkt.

## Eine Klasse, zwei Bedeutungen — der Fallstrick der Spalte «ersetzt heute»

Die Spalte liest sich wie eine Umrechnungstabelle, und für die meisten
Klassen ist sie das auch. Für einige nicht: Dieselbe Klasse stand im Bestand
einmal für einen **Zustand** und einmal für einen **Gegenstand**.

`shield-halved` ist das deutlichste Beispiel. Es steht unter `gesperrt` — und
war zugleich das Zeichen der **Kaution**, an drei Stellen. Klassenweise
umgesetzt trägt die Kaution danach ein Vorhängeschloss.

Ebenso: `file-circle-xmark` (unter `kritisch`) war das Zeichen der
**Kündigungs-Dokumente**; `user-check`, `clipboard-check` und
`calendar-check` (unter `gut`) standen für **Bewerbungen**, die
**Wohnungsabnahme** und die Kategorie **Erstmals kündbar**; `bolt` (unter
`kritisch`) war das **Gewerk Elektro**.

Bei `check` und `xmark` steht der Vorbehalt seit E2.35 in der Zeile. Bei den
übrigen fehlte er — nachgetragen. Wer umstellt, entscheidet am **Ort**, nicht
am Namen; und wo eine Kategorie oder ein Dokument gemeint ist, gehört ein
Fachbegriff hin, kein Zustand.

## Noch ohne Bedeutung (keine)

Hier standen bis E2.44 die Klassen, deren Bedeutung noch niemand entschieden
hatte. Die Überschrift bleibt genau so stehen: `core/templatetags/zeichen.py`
schneidet die Tabelle an ihr ab (`MARKE_OFFEN`), damit ein ungeklärtes Zeichen
nicht als gültig durchgeht. Wer sie umbenennt, macht die offene Liste wieder
zu einem Teil der Tabelle — beim ersten Versuch hier prompt passiert. Mit `weiterverrechnen` ist die letzte beantwortet; der Abschnitt bleibt
als Ort für die nächste.

> **Der Eintrag blieb einmal zu lange stehen.** E2.40 entschied `stamp`,
> `rotate-left` und `bell`, liess ihre Zeilen hier aber stehen — und E2.44
> tat dasselbe mit `share`/`share-from-square`: oben entschieden, unten
> weiter als offen beschrieben, samt Begründung, warum die Bedeutung fehle.
>
> Beide Male blieb der Wächter grün. Er verglich die **Zeichennamen** der
> Tabelle (`weiterverrechnen`) mit den **Klassennamen** der offenen Liste
> (`share`) — zwei Namensräume, Schnittmenge immer leer. Er konnte den Fall
> nie treffen, auch wenn er ihn zu prüfen behauptete. Verglichen werden jetzt
> die Klassen aus »ersetzt heute« gegen die offene Liste.

## Was bewusst wegfällt

**Raumkatalog-Symbole.** `bed`, `bath`, `couch`, `kitchen-set`, `plate-wheat`
— im Raumkatalog steht der Name des Raums daneben. Das Symbol wiederholt ihn
nur und wird bei jedem neuen Raumtyp zur Suche nach einem passenden Bild.
Stattdessen: `einheit` überall, oder gar keines.

**Dekoration.** `guitar`, `puzzle-piece`, `snowflake`, `sun`, `wind`,
`plane-departure` — sie standen an Stellen, wo sie eine Stimmung transportieren
sollten. Ein Verwaltungswerkzeug braucht das nicht, und beim zweiten Anblick
stört es.

**Doppelungen.** `trash`/`trash-can`, `list`/`list-ol`, `gauge`/`gauge-high`,
`link`/`link-slash`, `comment`/`comment-dots` — dieselbe Bedeutung, zufällig
verschiedene Wahl.

## Was noch zu entscheiden ist

Die **Pfade** selbst: D5 sieht ein Inline-SVG-Sprite im Lucide-Stil vor
(ISC-Lizenz, kopiert statt als Paket eingebunden). Diese Tabelle legt fest,
*welche* Zeichen es gibt und *was* sie bedeuten — nicht, wie sie aussehen.

Das ist Absicht: Über die Bedeutung lässt sich streiten, bevor eine einzige
Zeile SVG geschrieben ist. Wer die Reihenfolge umdreht, diskutiert am Ende über
Strichstärken statt über die Frage, ob `wartet` und `offen` zwei Zustände sind
oder einer.

> **Nachgetragen in E2.39.** Bei der Umstellung tauchten Klassen auf, die in der Häufigkeitsliste nicht vorkamen: `arrows-left-right`, `ban`, `calendar-day`, `circle-notch`, `circle-xmark`, `file`, `folder`, `guitar`, `heart`, `link-slash`, `list`, `plane-departure`, `puzzle-piece`, `rotate-left`, `share`, `signature`, `snowflake`, `star`, `sun`, `wind`. Alle sind bestehenden Bedeutungen zugeordnet — keine neue nötig.

> **`laedt` und `code`, nachgetragen in E2.42.** `laedt` ersetzt die zwei
> `fa-spin`-Spinner: Sie allein hielten 89 KB Font-Awesome-CSS und 119 KB
> Schrift am Leben, nachdem 1136 Vorkommen auf 11 gefallen waren. Die
> Drehung macht die Schicht mit acht Zeilen CSS.
>
> `code` stand unter «Noch ohne Bedeutung» — die Frage war, ob Rohdaten
> überhaupt ein Zeichen tragen sollen. Sie bekommen eines, weil die
> Alternative war, für eine Fundstelle ein ganzes Schriftpaket zu laden.

> **`weiterverrechnen`, entschieden in E2.44.** Die letzte offene Frage.
> Aus einer Kreditorenrechnung wird eine Forderung an den Mieter — die
> Schuld wechselt den Träger. Das ist weder `senden` (es wird nichts
> verschickt) noch `rechnung` (die gibt es vorher und nachher) noch
> `geld` (kein Betrag fliesst). Der Pfeil tritt deshalb aus dem Beleg
> aus, statt ihn zu teilen.

> **Raumzeichen, entschieden in E2.51 — und das kehrt einen früheren
> Entscheid um.** Oben steht unter «Was bewusst wegfällt»: Raumkatalog-
> Symbole seien überflüssig, weil der Name daneben steht. Das war für
> die INNENANSICHT gedacht, wo Räume in Listen erscheinen.
>
> Im öffentlichen Schadenformular ist es anders: Dort wählt ein Mieter
> am Handy aus zwölf Kacheln, oft in Eile und im Treppenhaus. Ein
> Symbol führt das Auge schneller als zwölfmal gleich aussehender Text.
> Zwölf gleiche `einheit`-Zeichen wären schlechter als keine — zwölf
> verschiedene sind besser als beides.
>
> Der frühere Absatz bleibt stehen und gilt weiter für die Innenansicht.
