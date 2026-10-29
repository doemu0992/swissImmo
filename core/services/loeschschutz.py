"""Löschschutz: Was an einer Person, Liegenschaft, einem Mandat oder Vertrag hängt.

WARUM ES DAS GIBT (Audit 28.10.2026, FUNK-03 / FIN-16)

«Person löschen», «Liegenschaft löschen» und «Mandat löschen» sperrten nur bei
AKTIVEN Verträgen bzw. vorhandenen Liegenschaften. Alles andere fiel mit: Die
Löschkaskade nahm alle Verträge, NK-Abrechnungen samt eingefrorenem Snapshot,
Abnahmen, Dokumente, Jahresabschlüsse, Anlagen und Auszahlungen mit; Rechnungen,
Zahlungen und Mahnungen verloren still ihren Bezug (`SET_NULL`) und fielen aus
Mieterkonto, Mahnlauf und Art. 257d OR. Geschäftsbücher und Buchungsbelege sind
zehn Jahre aufzubewahren (Art. 958f OR).

Etappe 0 sperrt das harte Löschen, sobald so etwas hängt. Etappe 2 liefert den Weg
dazu: das Archiv (`core/services/archiv.py`) mit Aufbewahrungsfrist. Ein archiviertes
Objekt ist bis zum Fristende nicht löschbar (`hindernisse()` nennt die Frist);
eine Person wird auf Wunsch zusätzlich anonymisiert (DSG), ein Mandat endet über
«Archivieren» (Mandatsende).

ZWEI SCHICHTEN, WIE BEI DER MANDANTENTRENNUNG
  1. Diese Datei: eine VERSTÄNDLICHE Antwort für die Oberfläche («es hängen noch
     3 Mietverträge und 12 Rechnungen daran»).
  2. `on_delete=PROTECT` an den Fremdschlüsseln, die Verträge, Rechnungen,
     Buchungen, Abrechnungen und Abschlüsse treffen: Auch ein `delete()` an der
     Ansicht vorbei (Shell, Skript, späterer Löschweg) endet in einem
     `ProtectedError` statt im Datenverlust.

`hindernisse()` zählt MEHR als die zweite Schicht schützt (zum Beispiel
Schadenmeldungen und STWEG-Beschlüsse einer Liegenschaft). Wer hier etwas
ergänzt, ergänzt keine Migration.

Alle Abfragen laufen über die Mandanten-Manager (`Modell.objects`): gezählt wird
nur, was zur eigenen Verwaltung gehört.
"""
from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy as _


class LoeschSperre(Exception):
    """An dem Objekt hängen Daten, die ein hartes Löschen verbieten."""

    def __init__(self, objekt, hindernisse):
        self.objekt = objekt
        self.hindernisse = list(hindernisse)
        super().__init__(f'{objekt}: ' + ', '.join(f'{n} {name}' for name, n in self.hindernisse))


def _zaehlen(*pruefungen):
    """`[(Bezeichnung, Queryset), …]` → `[(Bezeichnung, Anzahl), …]`, nur Anzahl > 0."""
    ergebnis = []
    for name, qs in pruefungen:
        n = qs.count()
        if n:
            ergebnis.append((name, n))
    return ergebnis


def _person(m):
    from finance.models import Betreibung, DebitorenRechnung, Mahnung, Zahlungseingang
    from rentals.models import Abnahmeprotokoll, Dokument, Kuendigung, Mietverfahren, Mietvertrag
    return _zaehlen(
        (_('Mietverträge'), Mietvertrag.objects.filter(
            Q(mieter=m) | Q(mitmieter=m) | Q(weitere_mieter=m)).distinct()),
        (_('Rechnungen'), DebitorenRechnung.objects.filter(vertrag__mieter=m)),
        (_('Zahlungen'), Zahlungseingang.objects.filter(vertrag__mieter=m)),
        (_('Mahnungen'), Mahnung.objects.filter(vertrag__mieter=m)),
        (_('Betreibungen'), Betreibung.objects.filter(vertrag__mieter=m)),
        (_('Kündigungen'), Kuendigung.objects.filter(vertrag__mieter=m)),
        (_('Mietrechtliche Verfahren'), Mietverfahren.objects.filter(vertrag__mieter=m)),
        (_('Abnahmeprotokolle'), Abnahmeprotokoll.objects.filter(vertrag__mieter=m)),
        (_('Dokumente'), Dokument.objects.filter(mieter=m)),
    )


def _vertrag(v):
    """Was an einem Vertrag hängt. Die automatisch erzeugten Vertragspaket-Dokumente
    zählen nicht: `Mietvertrag.delete()` räumt sie selbst weg."""
    from core.views.pdf import VERTRAGSPAKET_TITEL
    from finance.models import Betreibung, DebitorenRechnung, Mahnung, Zahlungseingang, Zahlungsvereinbarung
    from rentals.models import Abnahmeprotokoll, Dokument, Kuendigung, Mietverfahren
    return _zaehlen(
        (_('Rechnungen'), DebitorenRechnung.objects.filter(vertrag=v)),
        (_('Zahlungen'), Zahlungseingang.objects.filter(vertrag=v)),
        (_('Mahnungen'), Mahnung.objects.filter(vertrag=v)),
        (_('Betreibungen'), Betreibung.objects.filter(vertrag=v)),
        (_('Zahlungsvereinbarungen'), Zahlungsvereinbarung.objects.filter(vertrag=v)),
        (_('Kündigungen'), Kuendigung.objects.filter(vertrag=v)),
        (_('Mietrechtliche Verfahren'), Mietverfahren.objects.filter(vertrag=v)),
        (_('Abnahmeprotokolle'), Abnahmeprotokoll.objects.filter(vertrag=v)),
        (_('Dokumente'), Dokument.objects.filter(vertrag=v).exclude(
            kategorie='vertrag', bezeichnung__in=VERTRAGSPAKET_TITEL)),
    )


def _liegenschaft(lg):
    from finance.models import (AbrechnungsPeriode, Anlage, Bankbewegung, Buchung, DebitorenRechnung,
                                Erneuerungsfonds, Hypothek, Jahresabschluss, KreditorenRechnung,
                                Zahlungseingang)
    from portfolio.models import Dokument as PortfolioDokument
    from rentals.models import Abnahmeprotokoll, Dokument, Mietvertrag
    from stweg.models import StwegAbrechnung, StwegBudget, StwegDokument, Versammlung, Zirkularbeschluss
    from tickets.models import SchadenMeldung
    return _zaehlen(
        (_('Mietverträge'), Mietvertrag.objects.filter(einheit__liegenschaft=lg)),
        # Rechnungen und Zahlungen hängen an der Liegenschaft direkt ODER über den Vertrag der Einheit.
        (_('Rechnungen'), DebitorenRechnung.objects.filter(
            Q(liegenschaft=lg) | Q(vertrag__einheit__liegenschaft=lg)).distinct()),
        (_('Kreditorenrechnungen'), KreditorenRechnung.objects.filter(liegenschaft=lg)),
        (_('Zahlungen'), Zahlungseingang.objects.filter(
            Q(liegenschaft=lg) | Q(vertrag__einheit__liegenschaft=lg)).distinct()),
        (_('Buchungen'), Buchung.objects.filter(liegenschaft=lg)),
        (_('Bankbewegungen'), Bankbewegung.objects.filter(liegenschaft=lg)),
        (_('Nebenkostenabrechnungen'), AbrechnungsPeriode.objects.filter(liegenschaft=lg)),
        (_('Jahresabschlüsse'), Jahresabschluss.objects.filter(liegenschaft=lg)),
        (_('Anlagen'), Anlage.objects.filter(liegenschaft=lg)),
        (_('Hypotheken'), Hypothek.objects.filter(liegenschaft=lg)),
        (_('Erneuerungsfonds'), Erneuerungsfonds.objects.filter(liegenschaft=lg)),
        (_('Abnahmeprotokolle'), Abnahmeprotokoll.objects.filter(einheit__liegenschaft=lg)),
        (_('Dokumente'), PortfolioDokument.objects.filter(liegenschaft=lg)),
        (_('Dokumente zu Verträgen und Personen'), Dokument.objects.filter(liegenschaft=lg)),
        (_('Schadenmeldungen'), SchadenMeldung.objects.filter(liegenschaft=lg)),
        (_('STWEG-Abrechnungen'), StwegAbrechnung.objects.filter(liegenschaft=lg)),
        (_('STWEG-Budgets'), StwegBudget.objects.filter(liegenschaft=lg)),
        (_('STWEG-Dokumente'), StwegDokument.objects.filter(liegenschaft=lg)),
        (_('Versammlungen und Beschlüsse'), Versammlung.objects.filter(liegenschaft=lg)),
        (_('Zirkularbeschlüsse'), Zirkularbeschluss.objects.filter(liegenschaft=lg)),
    )


def _einheit(e):
    from finance.models import DebitorenRechnung, KreditorenRechnung
    from portfolio.models import Dokument as PortfolioDokument
    from rentals.models import Abnahmeprotokoll, Dokument, Mietvertrag
    return _zaehlen(
        (_('Mietverträge'), Mietvertrag.objects.filter(einheit=e)),
        (_('Rechnungen'), DebitorenRechnung.objects.filter(einheit=e)),
        (_('Kreditorenrechnungen'), KreditorenRechnung.objects.filter(einheit=e)),
        (_('Abnahmeprotokolle'), Abnahmeprotokoll.objects.filter(einheit=e)),
        (_('Dokumente'), PortfolioDokument.objects.filter(einheit=e)),
        (_('Dokumente zu Verträgen und Personen'), Dokument.objects.filter(einheit=e)),
    )


def _eigentuemer(md):
    from finance.models import EigentuemerAuszahlung
    from portfolio.models import Einheit, Liegenschaft
    from rentals.models import Dokument
    return _zaehlen(
        (_('Liegenschaften'), Liegenschaft.objects.filter(eigentuemer=md)),
        (_('Auszahlungen'), EigentuemerAuszahlung.objects.filter(eigentuemer=md)),
        (_('Stockwerkeinheiten'), Einheit.objects.filter(stockwerkeigentuemer=md)),
        (_('Dokumente'), Dokument.objects.filter(eigentuemer=md)),
    )


def _ohne_abhaengige(_objekt):
    """Dokument, Schadenmeldung und STWEG-Dokument tragen nichts, das an ihnen hängt;
    für sie gilt allein die Aufbewahrungsfrist des Archivs (`hindernisse()`)."""
    return []


_PRUEFER = {
    'rentals.Dokument': _ohne_abhaengige,
    'portfolio.Dokument': _ohne_abhaengige,
    'tickets.SchadenMeldung': _ohne_abhaengige,
    'stweg.StwegDokument': _ohne_abhaengige,
    'crm.Mieter': _person,
    'rentals.Mietvertrag': _vertrag,
    'portfolio.Liegenschaft': _liegenschaft,
    'portfolio.Einheit': _einheit,
    'crm.Eigentuemer': _eigentuemer,
}

#: Der Hinweis, der die Sperre mit einem gangbaren Weg verbindet.
_ALTERNATIVE = {
    'crm.Mieter': _('Beende die Verträge; auf Wunsch der Person kannst du ihre Daten über die '
                    'Datenschutz-Löschung (Anonymisierung) unkenntlich machen.'),
    'rentals.Mietvertrag': _('Archiviere den Vertrag stattdessen («Inaktiv / Archiviert»).'),
    'portfolio.Liegenschaft': _('Setze die Liegenschaft stattdessen auf «Archiviert» (Archiv, Aufbewahrung zehn Jahre).'),
    'portfolio.Einheit': _('Beende die Verträge und archiviere das Objekt; es bleibt mit seiner Geschichte bestehen.'),
    'crm.Eigentuemer': _('Beende das Mandat über «Archivieren» (Mandatsende): Es bleibt zehn Jahre aufbewahrt.'),
    'rentals.Dokument': _('Archiviere das Dokument stattdessen.'),
    'portfolio.Dokument': _('Archiviere das Dokument stattdessen.'),
    'tickets.SchadenMeldung': _('Archiviere die Schadenmeldung stattdessen.'),
    'stweg.StwegDokument': _('Archiviere das Dokument stattdessen.'),
}


def hindernisse(objekt):
    """Was an `objekt` hängt: `[(Bezeichnung, Anzahl), …]`; leer = löschbar."""
    pruefer = _PRUEFER.get(objekt._meta.label)
    if pruefer is None:
        raise ValueError(f'Kein Löschschutz für {objekt._meta.label} vorgesehen.')
    gefunden = list(pruefer(objekt))
    # Ein archiviertes Objekt ist bis zum Ende der Aufbewahrungsfrist nicht löschbar.
    from core.services.archiv import frist_hindernis
    frist = frist_hindernis(objekt)
    if frist:
        gefunden.append(frist)
    return gefunden


def pruefe_loeschbar(objekt):
    """Wirft `LoeschSperre`, wenn an `objekt` etwas hängt."""
    h = hindernisse(objekt)
    if h:
        raise LoeschSperre(objekt, h)


def sperrmeldung(objekt, hindernisse_, name=None):
    """Der Text für die Oberfläche: was hängt, warum es bleibt, was stattdessen geht."""
    was = ', '.join(f'{n} {bez}' for bez, n in hindernisse_)
    return gettext(
        '«%(name)s» kann nicht gelöscht werden: Es hängen noch Daten daran (%(was)s). '
        'Geschäftsunterlagen sind zehn Jahre aufzubewahren (Art. 958f OR). %(weg)s'
    ) % {'name': name or objekt, 'was': was, 'weg': gettext(_ALTERNATIVE[objekt._meta.label])}


def geschuetzt_melden(objekt, geschuetzt_fehler, name=None):
    """Der Text für den Fall, dass trotz Prüfung ein `ProtectedError` kommt.

    Er nennt die Modelle, die den Fremdschlüssel halten — Sicherheitsnetz für das,
    was `hindernisse()` (noch) nicht zählt."""
    modelle = sorted({o._meta.verbose_name_plural for o in geschuetzt_fehler.protected_objects})
    return sperrmeldung(objekt, [(', '.join(str(m) for m in modelle) or '?', len(geschuetzt_fehler.protected_objects))],
                        name)
