"""Archiv und Mandatsende statt hartes Löschen (Etappe 2; Audit FUNK-03/FIN-16/FUNK-10).

Geschäftsunterlagen sind zehn Jahre aufzubewahren (Art. 958f OR). Darum gibt es
für Liegenschaft, Objekt, Person, Mietvertrag, Mandat (Eigentümer), Dokument,
Schadenmeldung und STWEG-Dokument einen Weg, der nichts vernichtet:

* `archivieren()` legt einen `Archiveintrag` an (wer, wann, warum, bis wann),
  setzt bei Liegenschaft und Vertrag den bestehenden Archivstatus und blendet das
  Objekt aus den Arbeitslisten (`ausblenden()`).
* `wiederherstellen()` nimmt es zurück.
* Hartes Löschen ist erst nach der Frist möglich (`endgueltig_loeschen()`), und nur,
  wenn der Löschschutz (`loeschschutz.py`) nichts mehr findet, das daran hängt.

FRIST: bis zum 31.12. des zehnten Jahres nach dem Archivierungsjahr. Art. 958f
Abs. 1 OR lässt die Frist mit dem Ablauf des Geschäftsjahres beginnen, in dem der
letzte Beleg entstand; das Archivierungsjahr ist nie früher und daher die sichere
Lesart. Ob für Korrespondenz/Schadenakten eine kürzere Frist gilt, ist ein
Fachpunkt (Audit F2) und hier NICHT entschieden: alle Typen tragen dieselbe Frist.
"""
import logging
from datetime import date

from django.apps import apps
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

logger = logging.getLogger(__name__)

#: Aufbewahrungsdauer in Jahren (Art. 958f Abs. 1 OR).
AUFBEWAHRUNG_JAHRE = 10

#: Modell-Label -> (URL-Kürzel, Bezeichnung im Plural, Statuswert für „archiviert" oder None)
TYPEN = {
    'portfolio.Liegenschaft': ('liegenschaft', _('Liegenschaften')),
    'portfolio.Einheit': ('objekt', _('Objekte')),
    'crm.Mieter': ('person', _('Personen')),
    'rentals.Mietvertrag': ('vertrag', _('Mietverträge')),
    'crm.Eigentuemer': ('mandat', _('Mandate')),
    'rentals.Dokument': ('dokument', _('Dokumente (Personen und Verträge)')),
    'portfolio.Dokument': ('ablage', _('Dokumente (Ablage)')),
    'tickets.SchadenMeldung': ('schaden', _('Schadenmeldungen')),
    'stweg.StwegDokument': ('stwegdokument', _('STWEG-Dokumente')),
}
_NACH_KUERZEL = {kuerzel: label for label, (kuerzel, _name) in TYPEN.items()}


class ArchivFehler(Exception):
    """Archivieren oder Wiederherstellen ist nicht möglich; `str(e)` ist für den Benutzer."""


def modell_von_kuerzel(kuerzel):
    label = _NACH_KUERZEL.get(kuerzel)
    return apps.get_model(label) if label else None


def kuerzel(objekt):
    return TYPEN[objekt._meta.label][0]


def aufbewahren_bis(am=None):
    am = am or timezone.localdate()
    return date(am.year + AUFBEWAHRUNG_JAHRE, 12, 31)


def bezeichnung(objekt):
    for attr in ('display_name', 'firma_oder_name', 'titel', 'bezeichnung', 'name'):
        wert = getattr(objekt, attr, None)
        if wert:
            return str(wert)[:255]
    return str(objekt)[:255]


def eintrag(objekt):
    from core.models import Archiveintrag
    return Archiveintrag.objects.filter(typ=objekt._meta.label, objekt_id=objekt.pk).first()


def ist_archiviert(objekt):
    return eintrag(objekt) is not None


def archivierte_ids(modell):
    """Die IDs der archivierten Objekte eines Modells in der aktiven Verwaltung."""
    from core.models import Archiveintrag
    return set(Archiveintrag.objects.filter(typ=modell._meta.label).values_list('objekt_id', flat=True))


def ausblenden(qs):
    """Lässt archivierte Objekte aus einer Arbeitsliste weg."""
    ids = archivierte_ids(qs.model)
    return qs.exclude(pk__in=ids) if ids else qs


def _laufende_vertraege(objekt):
    from rentals.models import Mietvertrag
    laufend = ('aktiv', 'gekuendigt')
    label = objekt._meta.label
    if label == 'portfolio.Liegenschaft':
        return Mietvertrag.objects.filter(einheit__liegenschaft=objekt, status__in=laufend)
    if label == 'portfolio.Einheit':
        return Mietvertrag.objects.filter(einheit=objekt, status__in=laufend)
    if label == 'crm.Mieter':
        from django.db.models import Q
        return Mietvertrag.objects.filter(
            Q(mieter=objekt) | Q(mitmieter=objekt) | Q(weitere_mieter=objekt), status__in=laufend).distinct()
    if label == 'rentals.Mietvertrag':
        return Mietvertrag.objects.filter(pk=objekt.pk, status__in=('aktiv',))
    return Mietvertrag.objects.none()


def _hindernis(objekt):
    """Warum sich `objekt` (noch) nicht archivieren lässt, sonst ''."""
    laufend = _laufende_vertraege(objekt).count()
    if laufend:
        return gettext('Es laufen noch %(n)s Mietverträge. Beende sie zuerst.') % {'n': laufend}
    if objekt._meta.label == 'crm.Eigentuemer':
        from portfolio.models import Liegenschaft
        offen = Liegenschaft.objects.filter(eigentuemer=objekt).exclude(status='archiviert').count()
        if offen:
            return gettext('Dem Mandat sind noch %(n)s Liegenschaften zugeordnet, die nicht archiviert sind. '
                           'Archiviere sie oder ordne sie einem anderen Mandat zu.') % {'n': offen}
    return ''


def archivieren(objekt, *, user=None, grund='', mandatsende=None, pruefen=True):
    """Archiviert `objekt`. Wirft `ArchivFehler`, wenn noch Laufendes daran hängt.

    `pruefen=False` nur für den Vertragsstatus «Inaktiv / Archiviert», der einen laufenden
    Vertrag ausdrücklich stilllegen darf (bestehendes Verhalten)."""
    from core.models import Archiveintrag
    if objekt._meta.label not in TYPEN:
        raise ValueError(f'Kein Archiv für {objekt._meta.label} vorgesehen.')
    if ist_archiviert(objekt):
        raise ArchivFehler(gettext('Bereits archiviert.'))
    warum = _hindernis(objekt) if pruefen else ''
    if warum:
        raise ArchivFehler(warum)
    heute = timezone.localdate()
    vorher = ''
    if objekt._meta.label in ('portfolio.Liegenschaft', 'rentals.Mietvertrag'):
        vorher = objekt.status
    e = Archiveintrag.objects.create(
        typ=objekt._meta.label, objekt_id=objekt.pk, bezeichnung=bezeichnung(objekt),
        archiviert_am=heute, archiviert_von=user if getattr(user, 'pk', None) else None,
        grund=(grund or '')[:255], mandatsende=mandatsende, vorher_status=vorher,
        aufbewahren_bis=aufbewahren_bis(heute))
    if objekt._meta.label == 'portfolio.Liegenschaft':
        objekt.status = 'archiviert'
        objekt.save(update_fields=['status'])
    elif objekt._meta.label == 'rentals.Mietvertrag' and objekt.status != 'archiviert':
        objekt.status = 'archiviert'
        objekt.aktiv = False
        objekt.save(update_fields=['status', 'aktiv'])
    return e


def wiederherstellen(objekt):
    """Nimmt das Objekt aus dem Archiv zurück (Status wie vor dem Archivieren)."""
    e = eintrag(objekt)
    if e is None:
        raise ArchivFehler(gettext('Nicht archiviert.'))
    if objekt._meta.label == 'portfolio.Liegenschaft':
        objekt.status = e.vorher_status if e.vorher_status and e.vorher_status != 'archiviert' else 'aktiv'
        objekt.save(update_fields=['status'])
    elif objekt._meta.label == 'rentals.Mietvertrag':
        # Zurück auf «gekündigt» statt «aktiv»: Aktivieren verlangt die Prüfung des Mietzinsmodells
        # (Art. 269b/c OR) und geschieht über die Vertragsansicht.
        vorher = e.vorher_status
        objekt.status = vorher if vorher and vorher not in ('archiviert', 'aktiv') else 'gekuendigt'
        objekt.aktiv = False
        objekt.save(update_fields=['status', 'aktiv'])
    e.delete()


def frist_hindernis(objekt):
    """Ein Hindernis für das harte Löschen: die laufende Aufbewahrungsfrist, sonst None."""
    e = eintrag(objekt)
    if e and e.aufbewahren_bis >= timezone.localdate():
        return (gettext('Aufbewahrungsfrist bis %(bis)s') % {'bis': e.aufbewahren_bis.strftime('%d.%m.%Y')}, 1)
    return None


def endgueltig_loeschen(objekt):
    """Löscht ein archiviertes Objekt, dessen Frist abgelaufen ist und an dem nichts mehr hängt.

    Wirft `ArchivFehler`/`LoeschSperre`. Dateien eines Dokuments werden mit entfernt."""
    from core.services.loeschschutz import _PRUEFER, LoeschSperre
    e = eintrag(objekt)
    if e is None:
        raise ArchivFehler(gettext('Nur archivierte Objekte lassen sich endgültig löschen.'))
    if e.aufbewahren_bis >= timezone.localdate():
        raise ArchivFehler(gettext('Die Aufbewahrungsfrist läuft bis %(bis)s.')
                           % {'bis': e.aufbewahren_bis.strftime('%d.%m.%Y')})
    if objekt._meta.label in _PRUEFER:
        h = [x for x in _PRUEFER[objekt._meta.label](objekt)]
        if h:
            raise LoeschSperre(objekt, h)
    datei = getattr(objekt, 'datei', None)
    e.delete()
    if datei:
        datei.delete(save=False)
    objekt.delete()
    return True


def eintrag_entfernen(objekt):
    """Entfernt den Archiveintrag, ohne den Status anzufassen (der Aufrufer hat ihn schon gesetzt)."""
    e = eintrag(objekt)
    if e is not None:
        e.delete()
