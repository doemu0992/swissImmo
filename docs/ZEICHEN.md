# Zeichensatz — 42 Zeichen mit fester Bedeutung

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

### Navigation und Struktur (7)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `weiter` | Eine Ebene tiefer, Detail öffnen | `chevron-right`, `angle-right`, `arrow-right`, `arrow-right-long` |
| `zurueck` | Eine Ebene höher | `chevron-left`, `arrow-left`, `angles-left` |
| `aufklappen` | Abschnitt öffnen/schliessen | `chevron-down`, `chevron-up`, `caret-down` |
| `mehr` | Weitere Handlungen (Menü) | `ellipsis`, `ellipsis-vertical`, `bars`, `grid-2`, `layer-group` |
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
| `senden` | An jemanden hinausgeben | `paper-plane`, `envelope`, `envelope-open-text`, `reply`, `bullhorn`, `comments`, `phone`, `phone-volume` |
| `drucken` | Auf Papier oder als PDF | `print`, `file-pdf` |
| `kopieren` | Vervielfältigen | `copy`, `clone` |
| `hochladen` | Datei hereingeben | `upload`, `file-import`, `paperclip` |
| `herunterladen` | Datei hinausgeben | `download`, `file-export`, `file-zipper`, `file-arrow-down`, `file-csv`, `cloud-arrow-down` |

### Zustände (8)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `gut` | Erledigt, in Ordnung | `check`, `check-double`, `circle-check`, `envelope-circle-check`, `calendar-check`, `clipboard-check`, `user-check` |
| `warnung` | Beanstandet, aber nicht blockiert | `triangle-exclamation` |
| `kritisch` | Blockiert, Frist verletzt | `circle-exclamation`, `fire`, `fire-burner`, `house-crack`, `house-chimney-crack`, `house-circle-exclamation`, `cloud-bolt`, `bolt`, `file-circle-xmark`, `file-circle-minus` |
| `hinweis` | Erklärung, kein Handlungsbedarf | `circle-info`, `circle-question`, `lightbulb`, `note-sticky`, `flag` |
| `wartet` | Auf Dritte, auf Zeitablauf | `clock`, `hourglass-end`, `hourglass-half`, `spinner`, `circle-notch`, `user-clock`, `inbox` |
| `gesperrt` | Kein Zugriff, nicht änderbar | `lock`, `shield-halved`, `shield-heart`, `user-slash`, `user-shield` |
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

### Zeit und Verlauf (5)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `termin` | Datum, Kalender, Termin-Art | `calendar`, `calendar-days`, `calendar-day`, `calendar-week`, `person-walking` |
| `verlauf` | Chronik, Historie | `clock-rotate-left`, `list-ol`, `code-branch` |
| `lauf` | Wiederkehrender Vorgang | `rotate`, `arrows-rotate`, `truck-fast` |
| `bericht` | Auswertung, Zahlenbild | `chart-simple`, `chart-pie`, `chart-column`, `chart-line`, `percent`, `calculator` |
| `trend` | Richtung einer Zahl: steigt, fällt, unverändert | `arrow-trend-up`, `arrow-trend-down`, `equals`, `arrow-down-long` |

### Bedienung (1)

| Zeichen | Bedeutung | ersetzt heute |
|---|---|---|
| `einstellungen` | Konfiguration, Verhalten ändern | `gear`, `gears`, `plug`, `star`, `wand-magic-sparkles`, `robot`, `language`, `eye`, `hand` |

**Summe: 42 Zeichen.**

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

## Noch ohne Bedeutung (6 Klassen, 5 Fragen)

Diese sechs sind heute in Gebrauch und **bewusst nicht** zugeordnet. Für jedes
fehlt eine Entscheidung, die nicht beim Sortieren nebenbei fällt — sie hier
zu erfinden, hiesse eine Bedeutung festzuschreiben, die niemand geprüft hat.

| Klasse | Wo | Wofür es eine Bedeutung bräuchte |
|---|---|---|
| `stamp` | »Eingangsrechnungen freigeben« (Dashboard) | **Freigeben** ist eine eigene Handlung: nicht speichern, nicht erledigen — jemand mit Berechtigung lässt etwas zu. Fehlt in »Handlungen«. |
| `share`, `share-from-square` | »Weiterverrechnen & Debitor erstellen« | **Weiterverrechnen** ist Fachlogik, kein Teilen. `extern` passt nicht (nichts verlässt die Anwendung), `senden` auch nicht (niemand bekommt Post). Zwei Klassen für eine Sache — eine davon fällt ohnehin weg. |
| `rotate-left` | »Stornieren« | **Rückgängig** ist weder `loeschen` (der Beleg bleibt) noch `bearbeiten`. Buchhalterisch ist ein Storno ein eigener Vorgang. |
| `bell` | »Neueste Tickets«, »Sonnerie-Beschriftung« | Steht heute schon für **zwei Dinge**: eine Meldung und ein Klingelschild. Beide brauchen eine Zuordnung, und es kann nicht dieselbe sein. |
| `code` | »JSON ansehen« | Rohdaten für die Fehlersuche. Ob so etwas überhaupt ein Zeichen tragen soll, ist Teil der Frage. |

Der Wächter zählt sie mit (`STAND_OFFEN`): Die Liste darf schrumpfen, nicht
wachsen.

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
