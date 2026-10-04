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
from django.utils.translation import gettext
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum


def zahl(wert):
    """Eine Quote für die Anzeige: ohne überflüssige Nullen, auf jeder Datenbank gleich.

    SQLite liefert die Summe als `Decimal('999')`, PostgreSQL als `Decimal('999.00')`
    (die Spalte hat zwei Nachkommastellen). `format(…, 'g')` behält diese Nullen —
    «999.00/1000» statt «999/1000». Aufgefallen erst im CI-Lauf gegen PostgreSQL."""
    d = Decimal(wert)
    return format(d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize(), 'f')


class WertquotenFehler(ValidationError):
    """Die Wertquoten einer STWEG ergeben nicht das Total."""


def stimm_einheiten(liegenschaft):
    """Die Einheiten, die eine Wertquote und eine Stimme haben: die Hauptobjekte.

    Nebenräume (Parkplatz, Keller — `gehoert_zu` gesetzt) gehören zu einer
    Einheit und haben in der Regel weder eigene Quote noch eigenen Eigentümer.
    Zählten sie mit, ginge die Quotensumme nie auf (das Feld hat die Vorgabe 10
    aus dem Mietmodul) und jeder Keller wäre ein zusätzlicher «Kopf».

    Ist ein Parkplatz eine selbständige Stockwerkeinheit mit eigener Quote, wird
    er als eigenständiges Objekt erfasst (ohne `gehoert_zu`) und zählt mit."""
    return liegenschaft.einheiten.filter(gehoert_zu__isnull=True)


def wertquoten_summe(liegenschaft):
    """Summe der Wertquoten aller stimmberechtigten Einheiten (Decimal)."""
    return stimm_einheiten(liegenschaft).aggregate(s=Sum('wertquote'))['s'] or Decimal('0')


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
            gettext('Wertquoten von «%(liegenschaft)s» ergeben %(wert)s/%(wert2)s, erwartet %(wert3)s/%(wert4)s. Differenz: %(wert5)s%(wert6)s.') % {'liegenschaft': liegenschaft, 'wert': zahl(summe), 'wert2': zahl(total), 'wert3': zahl(total), 'wert4': zahl(total), 'wert5': "+" if total >= summe else "-", 'wert6': zahl(abs(total - summe))},
            code='wertquoten_summe')
