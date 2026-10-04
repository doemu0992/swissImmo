"""To-do-Liste und offene Punkte einer STWEG.

Aufgaben sind `core.Pendenz` — keine zweite Aufgabenliste. Damit erscheinen sie
dort, wo die Verwaltung ihre Fristen ohnehin liest (Pendenzen, Fristen-Digest).
Die Herkunft steht im Schlüssel `quelle`:

    stweg:beschluss:<traktandum-id>   Vollzug eines angenommenen Beschlusses
    stweg:anfrage:<anfrage-id>        Eine Anfrage ist zu beantworten
    stweg:aufgabe                     manuell erfasst
"""
from django.utils import timezone

from core.models import Pendenz
from stweg.models import StwegAnfrage, StwegVersand, Traktandum, Versammlung, Zirkularbeschluss

PREFIX = 'stweg:'


def vollzug_pendenz(traktandum, *, user=None):
    """Pendenz für den Vollzug eines Beschlusses; idempotent je Traktandum."""
    v = traktandum.versammlung
    obj, _ = Pendenz.objects.update_or_create(
        liegenschaft=v.liegenschaft, quelle=f'{PREFIX}beschluss:{traktandum.pk}',
        defaults={'titel': traktandum.vollzug_aufgabe[:200],
                  'beschreibung': f'Beschluss «{traktandum.titel}» der {v}',
                  'kategorie': 'aufgabe', 'faellig_am': traktandum.vollzug_faellig_am,
                  'erstellt_von': user})
    return obj


def aufgabe_erfassen(liegenschaft, titel, *, faellig_am=None, beschreibung='', user=None):
    return Pendenz.objects.create(
        liegenschaft=liegenschaft, titel=titel[:200], beschreibung=beschreibung,
        kategorie='aufgabe', faellig_am=faellig_am, quelle=f'{PREFIX}aufgabe', erstellt_von=user)


def erledigen(pendenz, *, heute=None):
    pendenz.erledigt = True
    pendenz.erledigt_am = heute or timezone.localdate()
    pendenz.save(update_fields=['erledigt', 'erledigt_am'])
    return pendenz


def stweg_pendenzen(liegenschaft, *, offen=True):
    qs = Pendenz.objects.filter(liegenschaft=liegenschaft, quelle__startswith=PREFIX)
    return qs.filter(erledigt=False) if offen else qs


def offene_punkte(liegenschaft):
    """Alles, was in dieser Gemeinschaft noch zu tun ist — an einer Stelle."""
    return {
        'aufgaben': list(stweg_pendenzen(liegenschaft)),
        'anfragen': list(StwegAnfrage.objects.filter(liegenschaft=liegenschaft)
                         .exclude(status=StwegAnfrage.ERLEDIGT)),
        # Geschäfte, die an einer durchgeführten Versammlung nicht entschieden wurden.
        'unentschiedene_traktanden': list(
            Traktandum.objects.filter(
                versammlung__liegenschaft=liegenschaft,
                versammlung__status__in=(Versammlung.DURCHGEFUEHRT, Versammlung.PROTOKOLLIERT),
                ergebnis__in=(Traktandum.OFFEN, Traktandum.VERTAGT))
            .select_related('versammlung')),
        'zirkulare_offen': list(Zirkularbeschluss.objects.filter(
            liegenschaft=liegenschaft, status__in=(Zirkularbeschluss.ENTWURF, Zirkularbeschluss.LAUFEND))),
        'zirkular_ergebnis_ausstehend': list(Zirkularbeschluss.objects.filter(
            liegenschaft=liegenschaft, status=Zirkularbeschluss.ABGESCHLOSSEN,
            ergebnis_versendet_am__isnull=True)),
        'protokoll_ausstehend': list(Versammlung.objects.filter(
            liegenschaft=liegenschaft, status=Versammlung.DURCHGEFUEHRT)),
        # Zustellungen, die nicht (mehr) automatisch laufen.
        'zustellung_offen': list(StwegVersand.objects.filter(
            versammlung__liegenschaft=liegenschaft,
            status__in=(StwegVersand.FEHLER, StwegVersand.POST))
            .select_related('versammlung', 'eigentuemer')),
    }
