"""Testdaten müssen Werte benutzen, die es in der Produktion gibt.

DER FUND

`core/tests/_isolation.py` legte Einheiten mit `typ='wohnung'` an. Gültig sind
`whg/gew/stwe/pp/gar/bas` — «wohnung» steht in keiner Auswahlliste. Es waren
nicht die eine gemeldete Stelle, sondern **44 in 20 Dateien**.

WARUM DAS UNBEMERKT BLIEB

Django prüft `choices` bei `Model.objects.create()` nicht. Der Wert landet
stumm in der Datenbank; erst ein Formular oder `full_clean()` würde meckern.
Auf SQLite fällt es nie auf, auf PostgreSQL auch nicht — es ist ja ein
gültiger Text für die Spalte.

WAS DARAUS FOLGT, UND ES IST NICHT HARMLOS

Jede Auswertung, die nach Objekttyp filtert (`typ='whg'` für Leerstand,
Wohnungszählung, Nebenkostenverteilung), hat diese Einheiten **übersehen**.
Ein Test, der «kein Leerstand» erwartet, war grün — nicht weil die Rechnung
stimmte, sondern weil die Einheit für die Rechnung unsichtbar war. Kein
Produktionsrisiko, denn dort entstehen die Werte über Formulare. Aber ein
Testbestand, der etwas anderes misst, als er zu messen vorgibt.

Derselbe Fehler stand in `seed_e2e.py` und wurde in E0.1 korrigiert — dort
fiel er auf, weil jemand hinsah. Dieser Test lässt das nicht mehr vom Zufall
abhängen.

ZWEI WEITERE, DIE DER WÄCHTER GEFUNDEN HAT

  * `Pendenz.kategorie='auszug'`   → `'vertrag'`  (gültig: aufgabe, finanzen,
    frist, sonstiges, unterhalt, vertrag)
  * `Mietvertrag.status='beendet'` → `'archiviert'` (gültig: aktiv,
    archiviert, entwurf, gekuendigt)

Der zweite steht in einem Test, der eine MANDANTENGRENZE prüft — mit einem
Vertragsstatus, den es nicht gibt. Beide Änderungen sind nachgeprüft
messneutral: `_pendenz_ziel` liest die Kategorie überhaupt nicht (es
verzweigt über `quelle` und `vertrag_id`), und `mieter_rechnung_qr` filtert
auf `vertrag_id__in=<eigene Verträge>` ohne jede Statusbedingung. Der 404
kommt also weiterhin aus der Trennung, nicht aus dem Status.

EIN DRITTER FUND WURDE ZURÜCKGENOMMEN

`portfolio.Dokument(kategorie='Allgemein')` in `test_debitoren.py` war
gemeldet und ist RICHTIG: Dieses Feld hat gar keine Auswahlliste, es ist
Freitext. Der Wächter hatte es gegen die Liste von `rentals.Dokument`
geprüft — beide Modelle heissen `Dokument`. Wie es dazu kam und wie es
behoben ist, steht bei `_modelle_mit_auswahl`.

WAS GEPRÜFT WIRD

Alle `feld='wert'`-Zuweisungen in den Testdateien, deren Feldname zu einem
Modellfeld mit `choices` gehört. Nur wörtliche Zeichenketten — was aus einer
Variablen kommt, kann diese Prüfung nicht sehen, und das steht hier, damit
niemand mehr Sicherheit annimmt, als da ist.
"""
import ast
import pathlib

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Nur die eigenen Apps — Djangos eigene Modelle gehen uns hier nichts an.
EIGENE = {'core', 'crm', 'faelle', 'finance', 'portfolio', 'rentals',
          'tickets', 'mietprozess', 'benutzer'}


def _modelle_mit_auswahl():
    """Klassenname → {App-Label → {Feldname → erlaubte Werte}}.

    DAS MODELL AUS DER ZEILE, NICHT DER FELDNAME ALLEIN

    Erste Fassung ordnete allein nach Feldnamen und musste alles ausnehmen,
    was mehrdeutig war — `typ`, `status`, `art`. Damit fand sie genau den
    Fehler nicht, für den sie geschrieben wurde: `Einheit.typ='wohnung'`.

    Die Gegenprobe hat das gezeigt: Wert wieder eingesetzt, Test blieb grün.
    Ein Test, der nicht rot wird, sobald man entfernt, was er schützt, prüft
    etwas anderes als seinen Namen — in dieser Reihe inzwischen zum vierten
    Mal.

    ZWEI EBENEN, WEIL EIN KLASSENNAME NICHT EINDEUTIG IST

    Die Fassung davor ordnete nach `modell.__name__` allein und übersprang
    Modelle ohne Auswahlfelder. Es gibt aber **zwei** Modelle namens
    `Dokument`: `portfolio.Dokument` — dort ist `kategorie` FREITEXT, ganz
    ohne Auswahlliste — und `rentals.Dokument` mit vier Werten. Das erste
    wurde übersprungen, das zweite eingetragen, und ein bestehendes
    `portfolio.Dokument(kategorie='Allgemein')` in `test_debitoren.py` als
    Fehler gemeldet. Es war keiner.

    Ein Wächter, der ein RICHTIGES Muster anzeigt, wird abgeschaltet — genau
    das ist `core/tests/test_zeilensperren.py` schon einmal passiert. Deshalb
    liegt der App-Bezug jetzt in der Struktur; welches `Dokument` gemeint ist,
    liest `_modelle_der_datei` aus den Importen der jeweiligen Datei.
    """
    je_name = {}
    for modell in apps.get_models():
        if modell._meta.app_label not in EIGENE:
            continue
        felder = {f.name: {str(w) for w, _ in f.flatchoices}
                  for f in modell._meta.fields if getattr(f, 'choices', None)}
        je_name.setdefault(modell.__name__, {})[modell._meta.app_label] = felder
    return je_name


def _modelle_der_datei(baum):
    """Lokaler Name → App-Label, aus den Importen der Datei gelesen.

    `from portfolio.models import Dokument` sagt eindeutig, welches der beiden
    `Dokument` gemeint ist. Ohne diese Auflösung bliebe nur Raten — und Raten
    heisst hier: einen richtigen Wert als Fehler melden.

    Importe INNERHALB von Funktionen zählen mit. In dieser Testreihe stehen
    die meisten dort, `ast.walk` findet sie ohnehin.
    """
    zuordnung = {}
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.ImportFrom) or not knoten.module:
            continue
        label = knoten.module.split('.')[0]
        if label not in EIGENE:
            continue
        for alias in knoten.names:
            zuordnung[alias.asname or alias.name] = label
    return zuordnung


def _testdateien():
    """Alle Dateien, die Testdaten anlegen — auch die ohne `test`-Praefix.

    Erste Fassung nahm nur `test*.py`. Damit fehlten genau die Dateien, in
    denen die Fixtures stehen: `core/tests/_isolation.py` und
    `core/tests/_helfer.py`. Der urspruengliche Fund — `typ='wohnung'` in der
    Mandanten-Fixture — lag in einer davon, und die Gegenprobe blieb deshalb
    ein zweites Mal gruen.
    """
    gesehen = set()
    for muster in ('test*.py', '*/tests/*.py', '*/tests/**/*.py'):
        for p in sorted(WURZEL.glob(muster)) + sorted(WURZEL.rglob(muster)):
            pfad = p.as_posix()
            if 'node_modules' in pfad or 'staticfiles' in pfad:
                continue
            if not p.is_file() or pfad in gesehen:
                continue
            gesehen.add(pfad)
            yield p.relative_to(WURZEL).as_posix(), p


def _modellaufrufe(baum):
    """Alle `Modell(...)`- und `Modell.objects.create(...)`-Aufrufe.

    ÜBER DEN SYNTAXBAUM, NICHT ÜBER ZEILEN

    Drei Fassungen dieses Wächters suchten mit regulären Ausdrücken je Zeile —
    und scheiterten an derselben Wirklichkeit:

      * `rolle='Verwaltung'` war ein Argument des Testhelfers `_team_user`,
        kein Modellfeld. Fehlalarm.
      * Der Erklärtext dieser Datei NENNT `typ='wohnung'`. Fehlalarm.
      * Und der Fall, für den der Wächter gebaut wurde, ging durch:

            Einheit.objects.create(
                liegenschaft=…, bezeichnung=…, typ='wohnung',

        Der Modellname steht auf der einen Zeile, der Wert auf der nächsten.
        Ein zeilenweiser Blick sieht das nie — die Gegenprobe blieb grün.

    Der Syntaxbaum kennt keine Zeilen. Er weiss, welcher Aufruf welche
    Argumente hat, und er kennt keine Kommentare und keine Docstrings — die
    ganze Ausblenderei entfällt damit ersatzlos.
    """
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        f = knoten.func
        # `Modell(...)`
        if isinstance(f, ast.Name):
            name = f.id
        # `Modell.objects.create(...)`, `Modell.alle_organisationen.filter(...)`
        elif isinstance(f, ast.Attribute):
            innen = f.value
            while isinstance(innen, ast.Attribute):
                innen = innen.value
            name = innen.id if isinstance(innen, ast.Name) else None
        else:
            continue
        if not name:
            continue
        werte = {}
        for kw in knoten.keywords:
            if kw.arg and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                werte[kw.arg] = (kw.value.value, kw.value.lineno)
        if werte:
            yield name, werte


class AuswahlwerteInTestdatenTest(SimpleTestCase):

    def test_kein_test_legt_einen_ungueltigen_auswahlwert_an(self):
        je_modell = _modelle_mit_auswahl()
        self.assertGreater(len(je_modell), 5,
                           'Kaum Modelle mit Auswahlfeldern gefunden — prüft '
                           'der Test überhaupt etwas?')

        funde = []
        for rel, pfad in _testdateien():
            try:
                baum = ast.parse(pfad.read_text(encoding='utf-8'))
            except SyntaxError:
                continue
            herkunft = _modelle_der_datei(baum)
            for modell, werte in _modellaufrufe(baum):
                je_app = je_modell.get(modell)
                if not je_app:
                    continue
                # Welches Modell dieses Namens ist gemeint? Der Import sagt es.
                # Ohne Import: alle Kandidaten, und gemeldet wird nur, was fuer
                # JEDEN von ihnen ungueltig ist — lieber eine Luecke als ein
                # Fehlalarm auf einem richtigen Wert.
                label = herkunft.get(modell)
                kandidaten = ([je_app[label]] if label in je_app
                              else list(je_app.values()))
                for feld, (wert, zeile) in werte.items():
                    listen = [k[feld] for k in kandidaten if k.get(feld)]
                    if not listen or len(listen) < len(kandidaten):
                        continue        # mindestens ein Kandidat kennt kein
                        # Auswahlfeld dieses Namens (z. B. portfolio.Dokument
                        # mit Freitext-`kategorie`) — dann ist nichts belegt.
                    if wert and all(wert not in erlaubt for erlaubt in listen):
                        gezeigt = sorted(set().union(*listen))
                        funde.append(f'{rel}:{zeile}  {modell}.{feld}={wert!r} '
                                     f'— gültig: {gezeigt}')

        self.assertEqual(
            funde, [],
            'Diese Testdaten benutzen Werte, die es in keiner Auswahlliste '
            'gibt:\n  ' + '\n  '.join(funde)
            + '\n\nDjango prüft `choices` bei `create()` nicht — der Wert '
              'landet stumm in der Datenbank. Jede Auswertung, die nach diesem '
              'Feld filtert, übersieht den Datensatz danach, und der Test ist '
              'grün, weil er nichts mehr misst.')

    def test_die_gegenprobe(self):
        """Der Wächter muss den Fehler finden, für den er gebaut wurde.

        Ausgeführt, nicht behauptet — und mit einem MEHRZEILIGEN Aufruf, weil
        genau daran die zeilenweise Fassung gescheitert ist: In
        `core/tests/_isolation.py` steht `Einheit.objects.create(` auf der
        einen Zeile und `typ='wohnung'` auf der nächsten. Die Gegenprobe blieb
        grün, obwohl der Fehler dastand.
        """
        quelle = (
            "Einheit.objects.create(\n"
            "    liegenschaft=lg, bezeichnung='3.5 Zi',\n"
            "    typ='wohnung')\n"
        )
        gefunden = dict(_modellaufrufe(ast.parse(quelle)))
        self.assertIn('Einheit', gefunden,
                      'Der mehrzeilige Aufruf wurde nicht erkannt.')
        wert, _zeile = gefunden['Einheit']['typ']
        self.assertEqual(wert, 'wohnung')

        listen = _modelle_mit_auswahl()['Einheit']['portfolio']['typ']
        self.assertNotIn('wohnung', listen,
                         'Wenn «wohnung» gültig geworden ist, ist diese '
                         'Gegenprobe hinfällig — dann einen anderen '
                         'ungültigen Wert einsetzen.')
        self.assertIn('whg', listen)
