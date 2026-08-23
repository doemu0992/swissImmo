"""Keine Zeilensperre über der optionalen Seite eines Outer Join.

DER BEFUND (E0.3)

`select_for_update()` zusammen mit `select_related()` über einen OPTIONALEN
Fremdschlüssel erzeugt einen LEFT OUTER JOIN. PostgreSQL verweigert dort die
Sperre:

    FOR UPDATE cannot be applied to the nullable side of an outer join

Betroffen waren «Forderung abschreiben» (`listen.py`) und «Zahlungseingang
stornieren» (`aktionen.py`). Jeder dieser Klicks hätte in der Produktion einen
Fehler geworfen. **SQLite ignoriert `FOR UPDATE` stillschweigend** — deshalb
war es hier nie zu sehen, und deshalb steht dieser Wächter im Quelltext statt
in einer Datenbankabfrage.

WARUM DIESER TEST DEN QUELLTEXT LIEST

Er soll auf **jeder** Datenbank anschlagen, auch auf der SQLite-Maschine eines
Entwicklers. Ein Test, der den Fehler nur auf PostgreSQL findet, findet ihn
genau dort nicht, wo er entsteht — beim Schreiben des Codes.

WAS «OPTIONAL» HIER HEISST — UND WAS NICHT

Die Nullbarkeit des Feldes allein entscheidet nicht. Beim Bau dieses Tests
stellte sich heraus (auf echtem PostgreSQL nachgemessen), dass
`aktionen.py` die Sammelzuordnung trotz optionalem `konto` **keinen** LEFT
JOIN erzeugt: Ein `filter(konto__nummer__in=…)` kann nur mit vorhandenem Konto
erfüllt sein, also joint Django INNER, und `select_related('konto')` benutzt
denselben Join weiter. Eine Prüfung, die bloss «Feld ist null=True» zählt,
hätte dort eine Änderung verlangt, die nichts behebt.

Der Test prüft deshalb das Paar `select_for_update()` + `select_related()` als
Muster und verlangt entweder `of=(…)` oder einen Eintrag in `GEPRUEFT` mit
Begründung. Das ist bewusst grob: Es zwingt beim nächsten Mal zum Nachmessen,
statt eine Regel zu behaupten, die nur meistens stimmt.
"""
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

WURZEL = pathlib.Path(settings.BASE_DIR)

#: Stellen, die `select_for_update()` mit `select_related()` verbinden, aber
#: nachweislich KEINEN LEFT JOIN erzeugen. Auf PostgreSQL nachgemessen, nicht
#: aus der Modelldefinition geschlossen. Wer hier etwas einträgt, hat es
#: gemessen — sonst gehört `of=('self',)` an die Stelle.
GEPRUEFT = {
    ('core/views/fw/kreditoren.py', 'kreditor'):
        'KreditorenZahlung.kreditor ist null=False — INNER JOIN.',
    ('core/views/fw/aktionen.py', 'konto'):
        'Der filter auf konto__nummer erzwingt INNER JOIN; select_related '
        'benutzt denselben Join weiter.',
}

# Nur eine DURCHGEHENDE Aufrufkette. Die Zwischenglieder duerfen ausschliesslich
# `.name(...)` sein — kein beliebiger Text.
#
# Eine erste Fassung erlaubte dazwischen `[^;]{0,400}` und meldete daraufhin
# `core/services/automation.py`. Dort steht das GEGENTEIL eines Fehlers: Die
# Sperre holt in einer eigenen Abfrage nur die IDs, die Objekte kommen danach
# aus einer zweiten, ungesperrten Abfrage mit `select_related`. Der Ausdruck
# hatte die Anweisungsgrenze uebersprungen und zwei getrennte Abfragen zu einer
# verklebt. Ein Waechter, der ein richtiges Muster anzeigt, wird abgeschaltet.
MUSTER = re.compile(
    # `of=('self',)` traegt selbst Klammern — eine Ebene muss hinein.
    r'select_for_update\((?P<args>(?:[^()]|\([^()]*\))*)\)'       # die Sperre …
    r'(?P<rest>(?:\s*\.\s*\w+\((?:[^()]|\([^()]*\))*\))*?)'       # … Kettenglieder
    r'\s*\.\s*select_related\((?P<felder>[^()]*)\)',              # … select_related
    re.S)


def _stellen():
    """Alle Vorkommen von `select_for_update(...) … .select_related(...)`."""
    for pfad in sorted((WURZEL / 'core').rglob('*.py')):
        rel = pfad.relative_to(WURZEL).as_posix()
        if '/tests/' in rel or rel.startswith('core/tests'):
            continue
        text = pfad.read_text(encoding='utf-8')
        for treffer in MUSTER.finditer(text):
            zeile = text[:treffer.start()].count('\n') + 1
            yield rel, zeile, treffer.group('args'), treffer.group('felder')


class ZeilensperrenTest(SimpleTestCase):

    def test_die_suche_findet_ueberhaupt_stellen(self):
        """Sonst prüfte der Test darunter eine leere Liste.

        Genau diese Blindheit hatte `AktenkopfTests`: eine Bedingung, die
        immer erfüllt ist, weil sie ins Leere greift.
        """
        gefunden = list(_stellen())
        self.assertGreaterEqual(
            len(gefunden), 3,
            f'Nur {len(gefunden)} Stellen gefunden — Schreibweise geändert? '
            f'{gefunden}')

    def test_jede_sperre_ueber_einem_join_ist_eingegrenzt_oder_gemessen(self):
        offen = []
        for rel, zeile, args, felder in _stellen():
            if 'of=' in args:
                continue
            schluessel = [f.strip().strip('\'"') for f in felder.split(',')]
            begruendet = any((rel, f.split('__')[0]) in GEPRUEFT
                             for f in schluessel if f)
            if not begruendet:
                offen.append(f'{rel}:{zeile}  select_related({felder.strip()})')

        self.assertEqual(
            offen, [],
            'Diese Zeilensperren spannen einen Join auf, ohne ihn einzugrenzen:\n  '
            + '\n  '.join(offen)
            + '\n\nIst einer der verbundenen Fremdschlüssel optional, entsteht '
              'ein LEFT OUTER JOIN, und PostgreSQL bricht ab: «FOR UPDATE '
              'cannot be applied to the nullable side of an outer join». '
              'SQLite verschluckt das — der Fehler zeigt sich erst in der '
              'Produktion.\n'
              'Entweder `select_for_update(of=(\'self\',))` schreiben (sperrt '
              'die eigene Zeile, nicht die mitverbundenen), oder auf '
              'PostgreSQL nachmessen und mit Begründung in GEPRUEFT eintragen.')

    def test_die_ausnahmeliste_ist_nicht_verwaist(self):
        """Ein Eintrag in `GEPRUEFT` für eine Stelle, die es nicht mehr gibt,
        täuscht eine Prüfung vor, die niemand mehr durchführt."""
        vorhanden = set()
        for rel, _zeile, _args, felder in _stellen():
            for f in felder.split(','):
                f = f.strip().strip('\'"')
                if f:
                    vorhanden.add((rel, f.split('__')[0]))

        verwaist = sorted(k for k in GEPRUEFT if k not in vorhanden)
        self.assertEqual(
            verwaist, [],
            f'Diese Einträge in GEPRUEFT zeigen auf nichts mehr: {verwaist}. '
            f'Bitte streichen.')

    def test_die_beiden_behobenen_stellen_tragen_die_eingrenzung(self):
        """Namentlich, damit ein Rückfall nicht nur allgemein auffällt.

        Beide sind auf echtem PostgreSQL nachgemessen: ohne `of=('self',)`
        brechen sie mit «FOR UPDATE cannot be applied to the nullable side of
        an outer join» ab, mit ihr laufen sie.
        """
        for datei, feld in (('core/views/fw/listen.py', 'vertrag__mieter'),
                            ('core/views/fw/aktionen.py', 'debitoren_rechnung')):
            with self.subTest(datei=datei):
                treffer = [s for s in _stellen()
                           if s[0] == datei and feld in s[3]]
                self.assertTrue(
                    treffer, f'{datei}: die Stelle mit {feld} ist verschwunden.')
                for _rel, zeile, args, _felder in treffer:
                    self.assertIn(
                        'of=', args,
                        f'{datei}:{zeile} sperrt wieder über den ganzen Join. '
                        f'Auf PostgreSQL wirft dieser Klick einen Fehler.')
