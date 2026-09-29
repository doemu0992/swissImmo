"""Dokumente entstehen in der Sprache des Empfängers (Entscheid D11, docs/PLAN-V7.md §8).

Nicht die Sprache der angemeldeten Person: Wer mit französischer Oberfläche
arbeitet, erzeugt für eine deutschsprachige Mieterin trotzdem ein deutsches
Dokument — und umgekehrt.

Stand 29.09.2026, erster Schnitt:

- Empfänger Mieter: `Mieter.sprache` («Korrespondenzsprache», gepflegt im
  Personenformular).
- Empfänger Eigentümer: `Eigentuemer.sprache` (Mandatsformular) — Portal-
  Zugangsmail, Eigentümerabrechnung, Portfolio-Report und die Begleitmail des
  Report-Versands. Der Steuerauszug bleibt deutsch: Seine Begriffe (AfA,
  Liegenschaftsrechnung) haben kantonal festgelegte Entsprechungen.
- Die Verwaltung selbst hat bewusst kein Sprachfeld: Wer bei ihr arbeitet,
  wählt die Sprache der Oberfläche persönlich; interne Auswertungen am
  Bildschirm folgen ihr. Deren PDFs (Mieterspiegel) entstehen deutsch, solange
  offen ist, wer bei internen Berichten der Empfänger ist.
- Dokumente mit Rechtstext (Mietvertrag, Allgemeine Bedingungen, Hausordnung,
  Kündigungsbestätigung, Mahnung, amtliche Formulare) bleiben DEUTSCH, bis ihr
  Wortlaut juristisch geprüft übersetzt ist. Eine sinngemässe Übertragung
  eines Vertragstexts wäre schlechter als ein korrekter deutscher.

Wichtig ist auch der umgekehrte Fall: Ein noch nicht übersetztes Dokument wird
ausdrücklich auf Deutsch erzeugt. Sonst liefen Datumsformate und Bausteine mit
Übersetzung in der Sprache der Sachbearbeitung mit — ein Dokument in zwei
Sprachen.
"""
from contextlib import contextmanager
from functools import wraps

from django.conf import settings
from django.utils import translation

STANDARD = 'de'


def gueltige_sprache(code):
    code = (code or '').strip().lower()[:2]
    verfuegbar = {c for c, _name in settings.LANGUAGES}
    return code if code in verfuegbar else STANDARD


def sprache_von(empfaenger):
    """Korrespondenzsprache eines Empfängers; Deutsch, wenn keine hinterlegt ist."""
    return gueltige_sprache(getattr(empfaenger, 'sprache', None))


@contextmanager
def in_sprache(code):
    """Rendert alles im Block in `code` (unbekannte Werte → Deutsch)."""
    with translation.override(gueltige_sprache(code)):
        yield


def nur_deutsch(erzeuger):
    """Für Dokumente, deren Text (noch) nur deutsch formuliert ist.

    Erzeugt fest auf Deutsch, unabhängig von der Sprache der Sachbearbeitung.
    Sonst liefen übersetzte Bausteine mit — Monatsnamen aus `date:"F"`,
    Auswahlwerte aus `get_…_display()` — und das Dokument stünde in zwei
    Sprachen. Ein Wächtertest verlangt diesen Dekorator an jedem Erzeuger
    in core/services, der kein gettext kennt."""
    @wraps(erzeuger)
    def fest_deutsch(*args, **kwargs):
        with in_sprache(STANDARD):
            return erzeuger(*args, **kwargs)
    fest_deutsch.dokumentsprache = STANDARD
    return fest_deutsch
