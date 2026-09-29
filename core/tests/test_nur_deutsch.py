"""Deutsch formulierte Dokumente entstehen fest auf Deutsch.

Die PDF-Erzeuger in core/services, deren Text kein gettext kennt, liefen in
der Sprache der Sachbearbeitung: Bei französischer Oberfläche bekam ein
deutscher Mietvertrag französische Monatsnamen aus `date:"F"`, und jeder
übersetzte Auswahlwert (`get_…_display()`) stünde mitten im deutschen Text.

Der Wächter verlangt `@nur_deutsch` an jedem solchen Erzeuger — auch an
künftigen. Wer ein Dokument übersetzt, ersetzt den Dekorator durch
`in_sprache(sprache_von(empfaenger))` und nimmt gettext in die Datei auf.

Gegenproben:
- bei `generate_serienbrief_pdf` in core/services/serienbrief.py die Zeile
  `@nur_deutsch` entfernen — `test_jeder_deutsche_erzeuger_ist_fest_deutsch`
  wird rot;
- in core/services/dokumentsprache.py in `nur_deutsch` den Block
  `with in_sprache(STANDARD):` durch `if True:` ersetzen —
  `test_der_dekorator_setzt_deutsch_durch` wird rot.
"""
import ast
import importlib
import pathlib

from django.test import SimpleTestCase
from django.utils import formats, translation

from core.services.dokumentsprache import nur_deutsch

DIENSTE = pathlib.Path(__file__).resolve().parents[1] / 'services'

#: Woran ein Dokumenterzeuger erkennbar ist.
ERZEUGT_DOKUMENT = ('reportlab', 'pisa', 'pypdf')
#: Welche öffentlichen Funktionen ein Dokument liefern.
IST_ERZEUGER = ('generate_', 'fill_', 'render_')


def _erzeuger():
    """(Modul, Funktion) für jeden Erzeuger in einer Datei ohne gettext."""
    funde = []
    for datei in sorted(DIENSTE.glob('*.py')):
        quelle = datei.read_text(encoding='utf-8')
        if not any(m in quelle for m in ERZEUGT_DOKUMENT):
            continue
        if 'gettext' in quelle or 'in_sprache' in quelle:
            continue   # übersetztes Dokument: steuert seine Sprache selbst
        for knoten in ast.parse(quelle).body:
            if isinstance(knoten, ast.FunctionDef) and not knoten.name.startswith('_') and (
                    knoten.name.startswith(IST_ERZEUGER) or knoten.name.endswith('_pdf')):
                funde.append((datei.stem, knoten.name))
    return funde


class NurDeutschTests(SimpleTestCase):

    def test_die_suche_findet_ueberhaupt_erzeuger(self):
        """Sonst wäre der Wächter darunter trivial grün."""
        self.assertGreater(len(_erzeuger()), 30)

    def test_jeder_deutsche_erzeuger_ist_fest_deutsch(self):
        fehlend = []
        for modul, name in _erzeuger():
            funktion = getattr(importlib.import_module(f'core.services.{modul}'), name)
            if getattr(funktion, 'dokumentsprache', None) != 'de':
                fehlend.append(f'{modul}.{name}')
        self.assertEqual(fehlend, [], 'Ohne @nur_deutsch (core.services.dokumentsprache)')

    def test_dokumente_ausserhalb_der_dienste(self):
        """Die Suche oben erkennt nur core/services; diese liegen anderswo."""
        from core.services import docuseal_service
        from core.views import dossier
        for funktion in (docuseal_service.docuseal_senden, dossier.mieter_dossier,
                         dossier.liegenschaft_dossier, dossier.vertrag_dossier):
            with self.subTest(funktion=funktion.__name__):
                # `rolle_erforderlich` legt sich darum; der Dekorator steckt innen.
                innen = getattr(funktion, '__wrapped__', funktion)
                self.assertEqual(getattr(innen, 'dokumentsprache', getattr(funktion, 'dokumentsprache', None)), 'de')

    def test_der_dekorator_setzt_deutsch_durch(self):
        @nur_deutsch
        def monat():
            return formats.date_format(__import__('datetime').date(2026, 5, 1), 'F')

        with translation.override('fr'):
            self.assertEqual(monat(), 'Mai')
            # und danach gilt wieder die Sprache der Oberfläche
            self.assertEqual(translation.get_language(), 'fr')
