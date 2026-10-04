"""Wertquoten-Prüfung einer STWEG-Gemeinschaft.

Die Wertquoten aller Einheiten müssen exakt den Nenner der Gemeinschaft
ergeben (Grundbuch: z. B. 1000/1000). Fehlt auch nur ein Promille, wäre jede
Kostenverteilung falsch — es würde ein Teil der Kosten keinem Eigentümer
belastet. Deshalb ist die Prüfung hart: Sie wirft, sie warnt nicht.

Zwei Stellen erzwingen sie:
  · `Liegenschaft.save()` — eine STWEG wird nie `aktiv`, wenn die Summe nicht
    aufgeht;
  · `StwegAbrechnungService` — es wird nie abgerechnet, wenn die Summe nicht
    aufgeht (auch nicht, wenn jemand die Einheiten nach der Aktivierung
    verändert hat; das lässt sich bei Einzelspeicherung nicht verhindern, ohne
    das gleichzeitige Umbuchen mehrerer Quoten unmöglich zu machen).

Nicht erfasst: `QuerySet.update()` und `bulk_create()` gehen an `save()`
vorbei. Die Abrechnung prüft deshalb unabhängig davon noch einmal.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum


class WertquotenFehler(ValidationError):
    """Die Wertquoten einer STWEG ergeben nicht das Total."""


def wertquoten_summe(liegenschaft):
    """Summe der Wertquoten aller Einheiten der Liegenschaft (Decimal)."""
    # Rückbezug über die Instanz: gefiltert wird durch die Liegenschaft selbst.
    return liegenschaft.einheiten.aggregate(s=Sum('wertquote'))['s'] or Decimal('0')


def pruefe_wertquoten(liegenschaft):
    """Wirft `WertquotenFehler`, wenn die Summe nicht exakt dem Total entspricht.

    Gilt nur für STWEG-Liegenschaften; Mietliegenschaften werden nicht geprüft.
    """
    if not liegenschaft.ist_stweg:
        return
    summe = wertquoten_summe(liegenschaft)
    total = Decimal(liegenschaft.wertquote_total)
    if summe != total:
        raise WertquotenFehler(
            f'Wertquoten von «{liegenschaft}» ergeben {summe:g}/{total:g}, '
            f'erwartet {total:g}/{total:g}. Differenz: {total - summe:+g}.',
            code='wertquoten_summe')
