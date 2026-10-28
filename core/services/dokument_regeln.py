"""Regeln «Ereignis → Dokument» (Modul 5, 27.10.2026).

Eine Vorlage mit `ereignis` erzeugt beim Ereignis ein BEGLEITDOKUMENT. Das
fest verdrahtete Dokument an derselben Stelle (Vertragspaket, amtliches
Formular, NK-Abrechnung …) bleibt, wie es ist; die Regel legt ein weiteres
dazu. Amtliche Formulare und Mahnungen mit Rechtstext gibt es hier nicht.

WELCHE VORLAGE GILT (`aktive_vorlage`)

1. Kandidaten: Vorlagen der eigenen Verwaltung und Systemvorlagen
   (`organisation IS NULL`) mit diesem Ereignis, deren `gueltig_ab` leer
   oder <= heute ist, und nur in der Sprache des Empfängers oder in «de».
2. Rangfolge: eigene vor System, dann Empfängersprache vor «de», dann das
   jüngste `gueltig_ab` (leer = ältestes), dann die höhere Version.
3. Nur aktive Vorlagen zählen. AUSGESCHALTET ist die Regel für eine
   Verwaltung, wenn sie eigene Vorlagen zu diesem Ereignis hat und keine
   davon aktiv ist — dann greift auch die Systemvorlage nicht. Anders liesse
   sich eine Systemregel nicht abschalten, ohne sie allen abzuschalten.

FEHLER KOSTEN DEN HAUPTABLAUF NICHT
`dokument_fuer_ereignis` fängt jeden Fehler, protokolliert ihn mit
`logger.exception` und gibt `None` zurück. Die Datenbankarbeit läuft in einem
eigenen Sicherungspunkt: Ein Fehler darin rollt nur die Regel zurück, nicht
die Kündigung, die gerade gespeichert wurde.
"""
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

#: Was an jedem Ereignis heute schon FEST entsteht — für die Regelkacheln,
#: damit niemand eine Regel für ein Dokument anlegt, das es ohnehin gibt.
#: Nachgesehen an den Aufrufstellen, nicht aus dem Konzept übernommen.
FEST_VERDRAHTET = {
    'vertrag_erstellt': _('Mietvertrag mit Beilagen, Anfangsmietzins-Formular, wo Pflicht'),
    'bewerber_zugesagt': _('E-Mail aus der Vorlage «Bewerber – Zusage»'),
    'kuendigung_erfasst': _('Pendenzen der Auszugscheckliste; das amtliche Formular entsteht beim Abruf'),
    'mza_versandt': _('amtliches Formular in der Akte (nur das Kantonsoriginal)'),
    'nk_versandt': _('Nebenkostenabrechnung je Mieter in der Akte'),
    'abnahme_abgeschlossen': _('Protokoll in der Akte beim ersten PDF-Abruf'),
}


def _gilt(v, stichtag):
    return v.gueltig_ab is None or v.gueltig_ab <= stichtag


def _waehle(vorlagen, organisation, sprache, stichtag):
    """Die Auswahl aus einer schon geladenen Liste (ein Ereignis). Siehe oben."""
    gueltig = [v for v in vorlagen if _gilt(v, stichtag)]
    eigene = [v for v in gueltig if v.organisation_id == organisation.pk]
    if eigene and not any(v.aktiv for v in eigene):
        return None                                   # abgeschaltet
    aktive = [v for v in gueltig if v.aktiv and v.sprache in (sprache, 'de')]
    if not aktive:
        return None

    def rang(v):
        return (0 if v.organisation_id == organisation.pk else 1,
                0 if v.sprache == sprache else 1,
                -(v.gueltig_ab.toordinal() if v.gueltig_ab else 0),
                -(v.version or 0),
                -v.pk)
    return sorted(aktive, key=rang)[0]


def _vorlagen(organisation, ereignis=None):
    """Eigene und Systemvorlagen mit Ereignis — EINE Abfrage."""
    from crm.models import Vorlage
    from core.tenancy import organisation_kontext
    with organisation_kontext(organisation):
        qs = Vorlage.objects.exclude(ereignis='')
        if ereignis:
            qs = qs.filter(ereignis=ereignis)
        return list(qs)


def regel_ausgeschaltet(ereignis, organisation, stichtag=None):
    """True, wenn die Verwaltung die Regel abgeschaltet hat (siehe oben, 3.)."""
    stichtag = stichtag or timezone.localdate()
    eigene = [v for v in _vorlagen(organisation, ereignis)
              if v.organisation_id == organisation.pk and _gilt(v, stichtag)]
    return bool(eigene) and not any(v.aktiv for v in eigene)


def aktive_vorlage(ereignis, *, organisation, sprache=None, stichtag=None):
    """Die Vorlage, die bei `ereignis` für diese Verwaltung gilt — oder None."""
    from core.services.dokumentsprache import gueltige_sprache
    if not ereignis or organisation is None:
        return None
    return _waehle(_vorlagen(organisation, ereignis), organisation,
                   gueltige_sprache(sprache), stichtag or timezone.localdate())


def regel_uebersicht(organisation, stichtag=None):
    """Je Ereignis eine Kachel «Wenn … dann …» — mit einer einzigen Abfrage.

    `status`: 'aktiv' | 'aus'. `herkunft`: 'eigen' | 'system' | '' (keine
    Vorlage). `vorlage`: die geltende deutsche Fassung, bei «aus» die
    abgeschaltete eigene, sonst None.
    """
    from crm.models import Vorlage
    stichtag = stichtag or timezone.localdate()
    alle = _vorlagen(organisation)
    kacheln = []
    for schluessel, label in Vorlage.EREIGNIS_CHOICES:
        liste = [v for v in alle if v.ereignis == schluessel]
        gilt = _waehle(liste, organisation, 'de', stichtag)
        eigene = [v for v in liste if v.organisation_id == organisation.pk]
        eigene_gueltig = [v for v in eigene if _gilt(v, stichtag)]
        abgeschaltet = bool(eigene_gueltig) and not any(v.aktiv for v in eigene_gueltig)
        if gilt is None and not abgeschaltet:
            # Keine deutsche Fassung, aber eine in einer anderen Sprache: Die
            # Regel greift für diese Empfänger — die Kachel sagt «aktiv».
            andere = [v for v in liste if v.aktiv and _gilt(v, stichtag)]
            andere.sort(key=lambda v: (0 if v.organisation_id == organisation.pk else 1, -v.pk))
            gilt = andere[0] if andere else None
        if gilt is not None:
            vorlage, status = gilt, 'aktiv'
        else:
            vorlage, status = (sorted(eigene, key=lambda v: -v.pk)[0] if eigene else None), 'aus'
        kacheln.append({
            'ereignis': schluessel, 'label': label, 'status': status, 'vorlage': vorlage,
            'herkunft': ('' if vorlage is None else ('eigen' if vorlage.organisation_id else 'system')),
            'sprachen': sorted({v.sprache for v in liste if v.aktiv}),
            'fest': FEST_VERDRAHTET.get(schluessel, ''),
            'umschaltbar': bool(liste),
        })
    return kacheln


def _empfaenger_sprache(vertrag, bewerbung):
    from core.services.dokumentsprache import sprache_von
    if vertrag is not None and vertrag.mieter_id:
        return sprache_von(vertrag.mieter)
    return sprache_von(bewerbung)        # Bewerbungen tragen keine Sprache → «de»


def dokument_fuer_ereignis(ereignis, *, organisation, vertrag=None, bewerbung=None, sprache=None):
    """Erzeugt das Begleitdokument zu `ereignis`, legt es ab und gibt es zurück.

    Ohne passende aktive Vorlage: None, und es entsteht nichts. Jeder Fehler
    wird protokolliert und ergibt None — der Aufrufer läuft weiter.
    """
    try:
        if organisation is None:
            return None
        sprache = sprache or _empfaenger_sprache(vertrag, bewerbung)
        vorlage = aktive_vorlage(ereignis, organisation=organisation, sprache=sprache)
        if vorlage is None:
            return None
        from core.services.ablage import ablegen
        from core.services.platzhalter import kontext_fuer
        from core.services.vorlagen_pdf import vorlage_pdf
        from core.tenancy import organisation_kontext
        with organisation_kontext(organisation), transaction.atomic():
            kontext = kontext_fuer(vertrag=vertrag, bewerbung=bewerbung,
                                   organisation=organisation, sprache=vorlage.sprache)
            pdf = vorlage_pdf(vorlage, kontext, organisation)
            titel = vorlage.name
            einheit = None
            if vertrag is None and bewerbung is not None:
                titel = f"{vorlage.name} – {kontext.get('bewerbung.name', '')}".strip(' –')
                einheit = bewerbung.einheit
            dok = ablegen(
                pdf, titel, kategorie='korrespondenz', vertrag=vertrag, einheit=einheit,
                dedup=True, vorlage=vorlage,
                # Ein Schreiben an eine BEWERBERIN hängt an der Einheit, nicht an
                # einem Vertrag. Im Mieterportal sähe es sonst der heutige Mieter
                # dieser Einheit (Objektdokumente ohne Vertrag sind dort sichtbar).
                #
                # Zu einem Vertrag gehört das Begleitschreiben dem Mieter: Die
                # Verwaltung hat die Regel ausdrücklich für dieses Ereignis
                # eingerichtet (Versand, Vertragserstellung, Abnahme), das ist die
                # Freigabe. Ohne Vertrag bleibt es unsichtbar.
                im_portal_sichtbar=(vertrag is not None))
            if dok is None:
                raise RuntimeError('Ablage gescheitert')
            return dok
    except Exception:
        logger.exception('Regel «%s» hat kein Dokument erzeugt (Organisation %s)',
                         ereignis, getattr(organisation, 'pk', None))
        return None
