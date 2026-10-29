# Etappe 3: Menüband, Rollen, Felder, Beträge, Kontrast, Admin (29.10.2026)

Beschluss aus dem Audit vom 28.10.2026 (Befunde DESIGN-01 bis -05, -07, -10, -11, -14, -15, -27, -28, ROUTE-02).
Was Entwicklerinnen und Entwickler seither beachten:

## Menüband: jede Team-Seite gehört zu einem Bereich

* Jede Ansicht, die `fw/base.html` rendert, meldet einen `nav`-Schlüssel. Er steht in einer Gruppe von
  `core/navigation.py` (`items[].keys` oder `extra_keys`) oder in `EINSTELLUNGEN_KEYS`.
* `core/tests/test_menueband_zuordnung.py` prüft beides: jeder `'nav': '…'` im Programmtext ist ein bekannter
  Schlüssel (Tippfehler wie `schaeden`), und jede abrufbare `/neu/`- und `/konto/`-Seite meldet einen.
* Seiten ohne eigenen Menüpunkt (`dokumente`, `kommunikation`, `suche`) leuchten unter «Akten» bzw. «Heute», ohne
  aktiven Punkt im Band. Ob sie einen Punkt bekommen, ist die offene Entscheidungsfrage DESIGN-05.
* STWEG-Seiten rufen `_global_filter(request)` auf wie alle anderen; der Bestandsfilter bleibt erhalten.

## Aktionen nur für Rollen, die sie öffnen dürfen

* Der Dekorator `@rolle_erforderlich` ist die einzige Quelle der Wahrheit (`benoetigte_rollen`).
* In Vorlagen: `{% if kann_schreiben %}` (Schreib-Rollen, kommt aus `_global_filter`) oder, genauer,
  `{% if request.user|darf:"/neu/ziel/1/" %}` (`{% load rechte %}`; der Pfad wird gegen die Ansicht aufgelöst).
* `fw/_archivieren.html` und die Einstellungs-Kacheln prüfen selbst. «Neuer Fall» im Kopf auch.
* Wächter: `core/tests/test_oberflaeche_rolle.py` kriecht über Links und POST-Formulare. Hauswart: null Ausnahmen.
  Lesezugriff und Sachbearbeitung: Sperrklinke `BEKANNT_OFFEN` (nur senken). Offen sind vor allem die grossen
  Akten (`liegenschaft_detail`, `objekt_detail`, `vertrag_detail`, `mandat_detail`, `mandate`).

## Feldnamen

* Jedes Feld hat einen zugänglichen Namen. `core/middleware_feldnamen.py` (Umwandlung in `core/utils/feldnamen.py`)
  verbindet ein `<label>` ohne `for` mit dem Feld direkt dahinter (`for`/`id`, im `<template>` `aria-label`) und
  nimmt bei Feldern ohne Label den Platzhalter als Namen.
* Alles andere (Feld in Tabellenzelle, Datei-Feld hinter einem Layout-Block, Auswahl ohne Beschriftung) bekommt ein
  `aria-label` in der Vorlage. `core/tests/test_feldnamen.py` meldet die Stelle: einmal über abgerufene Seiten,
  einmal über den Quelltext aller Vorlagen (Ausnahmen mit Grund in `QUELLTEXT_AUSNAHMEN`).

## Beträge

* Ein Parser: `core/utils/betrag.py` (`betrag_normalisieren`, `betrag_parsen`, `betrag_oder_none`, `betrag_text`).
  «1'450.50», «1450,5», «1.450,50», «CHF 12'500.00» gelten überall. Kein eigener `.replace(',', '.')` mehr
  (Wächter `test_kein_neuer_eigener_parser_im_programm`).
* Ein Feld: `<input type="text" inputmode="decimal" data-chf data-fehler="…">` für Beträge,
  `data-dezimal` für Zinssätze, Prozent, Punkte. `fw/_feld.html` setzt es mit `betrag=True` bzw. `zahl=True`.
  Kein `type="number"` für Geld (Wächter `VorlagenWaechterTests`).
* Skript: `static/js/fw-bausteine.js` schreibt den Wert beim Verlassen des Feldes; `window.fwZahl(text)` liest ihn
  für Berechnungen, `fwBetragSetzen(feld, zahl)` setzt ihn. Skripte, die vor `fw-bausteine.js` (defer) laufen,
  brauchen einen Ersatz (siehe `zahlAus` in `fw/vertrag_neu.html`).
* `core/tests/test_betrag.py` prüft Python und JavaScript gegen dieselbe Tabelle.

## Kontrast (WCAG AA, hell und dunkel)

* Weisse Schrift auf Ember-Flächen steht auf `--ds-karte-hell/-mitte/-tief` (5.2 : 1 bis 7.7 : 1), nicht auf
  `--ds-akzent` (3.5 : 1) oder `--ds-akzent-hell` (2.5 : 1). Gilt für `fw-kachel.akzent`, `fw-kpi.fw-accent`
  und den Avatar.
* e2e `felder-betrag-kontrast.spec.ts` misst die Pixel hinter dem Text (hell und dunkel, 390 px).
* Keine Klassen `text-indigo-*`: Sie ergaben im Dunkelmodus 3.31 : 1 und widersprechen dem Designsystem.

## Admin

* `core/tests/test_admin_seiten.py`: Jeder Name in Liste, Fieldsets und Inlines muss sich auflösen, und jede
  Liste und Änderungsseite mit Datensatz öffnet sich. Ein Konto ohne Verwaltung bekommt im Admin 403 statt 500.
* Offen: Die Kopfbereiche von Mieter, Handwerker, Eigentümer und Organisation laden eine Google-Maps-Karte mit
  der Adresse (`admin/crm/*_header.html`): Adressdaten verlassen das System. Entscheidung der Fachseite nötig.
