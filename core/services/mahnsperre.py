"""Welche Forderungen der Mahnlauf nicht anfasst — EINE Stelle für Lauf und Übersicht.

Drei Gründe, eine Forderung nicht zu mahnen, und sie wirken verschieden weit:

* `Mieter.mahnsperre` — der Handschalter der Verwaltung. Er sperrt den ganzen
  Mieter und wird am Mieter geprüft, nicht hier (`Mahnlauf`, `fw_mahnwesen`).
* Eine aktive Zahlungsvereinbarung — sperrt nur die Forderungen, die ihr
  Ratenplan deckt (`core.services.zahlungsvereinbarung.gesperrte_rechnung_ids`).
  Neue Mieten während des Plans werden gemahnt.
* Eine offene Betreibung — sperrt die Forderungen, die betrieben werden
  (`core.services.betreibung.rechnung_ids_in_offener_betreibung`). Die
  Zahlungsaufforderung kommt dort vom Betreibungsamt.

Bis 26.10.2026 entschieden Mahnlauf und Mahnwesen jedes für sich, und beide nur
über den Mieter. Wer hier etwas ändert, ändert beides.
"""
from django.utils.translation import gettext


def gesperrte_forderungen():
    """{rechnung_id: Grund} — die durch Vereinbarung oder Betreibung gesperrten
    Forderungen der aktuellen Organisation. Vier Abfragen, unabhängig von der
    Zahl der Rechnungen; einmal vor der Schleife aufrufen, nicht in ihr.

    Steht eine Forderung in beiden, gilt die Betreibung: Sie ist der weitere
    Schritt, und ihr Grund ist der, den die Verwaltung sehen muss."""
    from core.services.betreibung import rechnung_ids_in_offener_betreibung
    from core.services.zahlungsvereinbarung import gesperrte_rechnung_ids

    gruende = {}
    vereinbarung = gettext('Gedeckt durch eine laufende Zahlungsvereinbarung (Ratenplan)')
    for pk in gesperrte_rechnung_ids():
        gruende[pk] = vereinbarung
    betreibung = gettext('In Betreibung (SchKG) — gemahnt wird über das Betreibungsamt')
    for pk in rechnung_ids_in_offener_betreibung():
        gruende[pk] = betreibung
    return gruende
