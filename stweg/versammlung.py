"""Ablauf einer Versammlung: Einladung prüfen und versenden, durchführen,
Protokoll versenden. Jede Zustellung wird in `StwegVersand` festgehalten."""
from django.db import transaction
from django.utils import timezone

from core.utils.email_service import send_via_hoststar
from stweg.models import Anwesenheit, StwegVersand, Versammlung
from stweg.pdf import einladung_pdf, protokoll_pdf
from stweg.validierung import WertquotenFehler, pruefe_wertquoten


class VersammlungsFehler(ValueError):
    """Ein Schritt ist (noch) nicht zulässig; `args[0]` ist die Liste der Gründe."""

    def __init__(self, probleme):
        self.probleme = list(probleme)
        super().__init__('; '.join(self.probleme))


def empfaenger(versammlung):
    """Die Eigentümer der Gemeinschaft (je einmal) und Einheiten ohne Eigentümer."""
    einheiten = list(versammlung.liegenschaft.einheiten.select_related('stockwerkeigentuemer'))
    eig, ohne = {}, []
    for e in einheiten:
        if e.stockwerkeigentuemer_id:
            eig[e.stockwerkeigentuemer_id] = e.stockwerkeigentuemer
        else:
            ohne.append(e)
    return list(eig.values()), ohne


def einladung_pruefen(versammlung, heute=None):
    """Gründe, die dem Versand im Weg stehen (leer = versandbereit)."""
    v, heute = versammlung, heute or timezone.localdate()
    lg = v.liegenschaft
    probleme = []
    if not lg.ist_stweg or lg.status != lg.STATUS_AKTIV:
        probleme.append('Die Gemeinschaft muss eine aktive STWEG sein.')
    else:
        try:
            pruefe_wertquoten(lg)
        except WertquotenFehler as e:
            probleme.append(str(e.message))
    if not v.traktanden.exists():
        probleme.append('Es ist kein Traktandum erfasst.')
    tage = (timezone.localtime(v.datum).date() - heute).days if timezone.is_aware(v.datum) \
        else (v.datum.date() - heute).days
    if tage < v.einladungsfrist_tage:
        probleme.append(f'Einladungsfrist unterschritten: noch {tage} Tage bis zur Versammlung, '
                        f'verlangt sind {v.einladungsfrist_tage}.')
    eig, ohne = empfaenger(v)
    if not eig:
        probleme.append('Keine Stockwerkeigentümer den Einheiten zugeordnet.')
    for e in ohne:
        probleme.append(f'Einheit «{e.bezeichnung}» hat keinen Stockwerkeigentümer — '
                        'sie würde nicht eingeladen.')
    return probleme


def _senden(versammlung, art, eigentuemer, betreff, html, dateiname, pdf_bytes):
    """Ein Empfänger, ein Eintrag im Versandprotokoll."""
    from tickets.workflow import reply_to
    if not eigentuemer.email:
        status, fehler = StwegVersand.POST, ''
    else:
        ok = send_via_hoststar(eigentuemer.email, betreff, html, dateiname, pdf_bytes,
                               reply_to=reply_to(versammlung))
        status, fehler = (StwegVersand.GESENDET, '') if ok else (StwegVersand.FEHLER, 'Versand fehlgeschlagen')
    return StwegVersand.objects.create(
        versammlung=versammlung, art=art, eigentuemer=eigentuemer,
        email=eigentuemer.email or '', status=status, fehler=fehler)


def _schon_gesendet(versammlung, art):
    return set(StwegVersand.objects.filter(
        versammlung=versammlung, art=art, status=StwegVersand.GESENDET
    ).values_list('eigentuemer_id', flat=True))


def einladung_versenden(versammlung, *, heute=None):
    """Prüft, lädt alle Eigentümer ein, protokolliert jede Zustellung.

    Wiederholbar: wer schon eine gesendete Einladung hat, bekommt keine zweite;
    fehlgeschlagene und Post-Fälle werden erneut versucht. Gibt die neuen
    Versandeinträge zurück."""
    v = versammlung
    if v.status not in (v.ENTWURF, v.EINGELADEN):
        raise VersammlungsFehler(['Die Versammlung ist bereits durchgeführt.'])
    probleme = einladung_pruefen(v, heute)
    if probleme:
        raise VersammlungsFehler(probleme)
    eig, _ = empfaenger(v)
    schon = _schon_gesendet(v, StwegVersand.EINLADUNG)
    org = v.liegenschaft.organisation
    neu = []
    for e in eig:
        if e.pk in schon:
            continue
        html = ("<html><body style='font-family:Arial,sans-serif;line-height:1.5'>"
                f"<p>Guten Tag {e.firma_oder_name}</p>"
                f"<p>wir laden Sie zur {v.get_art_display()} der Gemeinschaft "
                f"{v.liegenschaft} ein: <strong>{timezone.localtime(v.datum):%d.%m.%Y, %H:%M} Uhr</strong>"
                f"{', ' + v.ort if v.ort else ''}. Traktanden und Anträge finden Sie in der Beilage.</p>"
                f"<p>Freundliche Grüsse<br>{org.firma}</p></body></html>")
        neu.append(_senden(v, StwegVersand.EINLADUNG, e, f'Einladung: {v.titel}', html,
                           f'Einladung_{v.datum:%Y%m%d}.pdf', einladung_pdf(v, e)))
    with transaction.atomic():
        v.status = v.EINGELADEN
        v.einladung_versendet_am = v.einladung_versendet_am or timezone.now()
        v.save(update_fields=['status', 'einladung_versendet_am'])
    return neu


@transaction.atomic
def durchfuehren(versammlung):
    """Eröffnet die Erfassung: Status «durchgeführt», jede Einheit zunächst abwesend."""
    v = versammlung
    if v.status != v.EINGELADEN:
        raise VersammlungsFehler(['Durchführen setzt eine versendete Einladung voraus.'])
    for e in v.liegenschaft.einheiten.all():
        Anwesenheit.objects.get_or_create(versammlung=v, einheit=e,
                                          defaults={'art': Anwesenheit.ABWESEND})
    v.status = v.DURCHGEFUEHRT
    v.save(update_fields=['status'])
    return v


def protokoll_pruefen(versammlung):
    from stweg.models import Traktandum
    probleme = []
    if versammlung.status not in (versammlung.DURCHGEFUEHRT, versammlung.PROTOKOLLIERT):
        probleme.append('Die Versammlung ist noch nicht durchgeführt.')
    for t in versammlung.traktanden.filter(ergebnis=Traktandum.OFFEN):
        probleme.append(f'Traktandum {t.nr} «{t.titel}» hat noch kein festgestelltes Ergebnis.')
    return probleme


def protokoll_versenden(versammlung):
    """Schickt das Protokoll an alle Eigentümer (auch an Abwesende)."""
    v = versammlung
    probleme = protokoll_pruefen(v)
    if probleme:
        raise VersammlungsFehler(probleme)
    eig, _ = empfaenger(v)
    schon = _schon_gesendet(v, StwegVersand.PROTOKOLL)
    org = v.liegenschaft.organisation
    pdf = protokoll_pdf(v)
    neu = []
    for e in eig:
        if e.pk in schon:
            continue
        html = ("<html><body style='font-family:Arial,sans-serif;line-height:1.5'>"
                f"<p>Guten Tag {e.firma_oder_name}</p>"
                f"<p>in der Beilage das Protokoll der {v.get_art_display()} vom "
                f"{timezone.localtime(v.datum):%d.%m.%Y}.</p>"
                f"<p>Freundliche Grüsse<br>{org.firma}</p></body></html>")
        neu.append(_senden(v, StwegVersand.PROTOKOLL, e, f'Protokoll: {v.titel}', html,
                           f'Protokoll_{v.datum:%Y%m%d}.pdf', pdf))
    v.status = v.PROTOKOLLIERT
    v.protokoll_versendet_am = v.protokoll_versendet_am or timezone.now()
    v.save(update_fields=['status', 'protokoll_versendet_am'])
    return neu
