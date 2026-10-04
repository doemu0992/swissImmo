"""Zirkularbeschluss: Antrag versenden, Stimmen sammeln, Ergebnis feststellen und mitteilen.

Ablauf: entwurf → (versenden) laufend → (feststellen) abgeschlossen.
Abgestimmt wird je EINHEIT; im Portal stimmt der Eigentümer für seine Einheiten,
die Verwaltung erfasst schriftlich eingegangene Stimmen. Nach der Frist (oder
sobald alle Einheiten abgestimmt haben) wird das Ergebnis festgestellt."""
from django.db import transaction
from django.utils import timezone

from core.utils.email_service import send_via_hoststar
from stweg.beschluss import BeschlussFehler, zaehlen
from stweg.models import Stimme, Traktandum, Zirkularbeschluss, ZirkularStimme, ZirkularVersand
from stweg.pdf import zirkular_pdf
from stweg.validierung import WertquotenFehler, pruefe_wertquoten
from stweg.versammlung import VersammlungsFehler


def _empfaenger(z):
    from stweg.versammlung import empfaenger
    return empfaenger(z)


def pruefen(z, heute=None):
    """Gründe, die dem Versand im Weg stehen (leer = versandbereit)."""
    heute = heute or timezone.localdate()
    lg = z.liegenschaft
    probleme = []
    if not lg.ist_stweg or lg.status != lg.STATUS_AKTIV:
        probleme.append('Die Gemeinschaft muss eine aktive STWEG sein.')
    else:
        try:
            pruefe_wertquoten(lg)
        except WertquotenFehler as e:
            probleme.append(str(e.message))
    if not z.antrag.strip():
        probleme.append('Der Antrag fehlt.')
    if z.frist_bis <= heute:
        probleme.append('Die Abstimmungsfrist muss in der Zukunft liegen.')
    eig, ohne = _empfaenger(z)
    if not eig:
        probleme.append('Keine Stockwerkeigentümer den Einheiten zugeordnet.')
    for e in ohne:
        probleme.append(f'Einheit «{e.bezeichnung}» hat keinen Stockwerkeigentümer — sie könnte nicht abstimmen.')
    return probleme


def _senden(z, art, eigentuemer, betreff, html, dateiname, pdf):
    from tickets.workflow import reply_to
    if not eigentuemer.email:
        status, fehler = 'post_noetig', ''
    else:
        ok = send_via_hoststar(eigentuemer.email, betreff, html, dateiname, pdf, reply_to=reply_to(z))
        status, fehler = ('gesendet', '') if ok else ('fehler', 'Versand fehlgeschlagen')
    return ZirkularVersand.objects.create(zirkular=z, art=art, eigentuemer=eigentuemer,
                                          email=eigentuemer.email or '', status=status, fehler=fehler)


def _schon_gesendet(z, art):
    return set(ZirkularVersand.objects.filter(zirkular=z, art=art, status='gesendet')
               .values_list('eigentuemer_id', flat=True))


def versenden(z, *, heute=None):
    """Prüft, schickt den Antrag an alle Eigentümer und setzt den Beschluss auf «läuft».
    Wiederholbar wie die Einladung: nur Fehlgeschlagene und Post-Fälle werden erneut versucht."""
    if z.status not in (z.ENTWURF, z.LAUFEND):
        raise VersammlungsFehler(['Der Beschluss ist bereits abgeschlossen.'])
    probleme = pruefen(z, heute)
    if probleme:
        raise VersammlungsFehler(probleme)
    eig, _ = _empfaenger(z)
    schon = _schon_gesendet(z, ZirkularVersand.ANTRAG)
    org = z.liegenschaft.organisation
    pdf = zirkular_pdf(z)
    neu = []
    for e in eig:
        if e.pk in schon:
            continue
        html = ("<html><body style='font-family:Arial,sans-serif;line-height:1.5'>"
                f"<p>Guten Tag {e.firma_oder_name}</p>"
                f"<p>die Gemeinschaft {z.liegenschaft} stimmt auf dem Zirkularweg über «{z.titel}» ab. "
                f"Bitte stimmen Sie bis <strong>{z.frist_bis:%d.%m.%Y}</strong> im Eigentümerportal ab. "
                "Den Antrag finden Sie in der Beilage.</p>"
                f"<p>Freundliche Grüsse<br>{org.firma}</p></body></html>")
        neu.append(_senden(z, ZirkularVersand.ANTRAG, e, f'Abstimmung: {z.titel}', html,
                           f'Antrag_{z.pk}.pdf', pdf))
    with transaction.atomic():
        z.status = z.LAUFEND
        z.versendet_am = z.versendet_am or timezone.now()
        z.save(update_fields=['status', 'versendet_am'])
    return neu


def stimme_abgeben(z, einheit, wert, *, kanal='portal', heute=None):
    heute = heute or timezone.localdate()
    if z.status != z.LAUFEND:
        raise BeschlussFehler('Über diesen Beschluss wird zurzeit nicht abgestimmt.')
    if kanal == 'portal' and heute > z.frist_bis:
        raise BeschlussFehler('Die Abstimmungsfrist ist abgelaufen.')
    if einheit.liegenschaft_id != z.liegenschaft_id:
        raise BeschlussFehler('Die Einheit gehört nicht zu dieser Gemeinschaft.')
    if wert not in dict(Stimme.WERT_CHOICES):
        raise BeschlussFehler(f'Ungültige Stimme «{wert}».')
    obj, _ = ZirkularStimme.objects.update_or_create(
        zirkular=z, einheit=einheit, defaults={'wert': wert, 'kanal': kanal})
    return obj


def auswerten(z):
    stimmen = {s.einheit_id: s.wert for s in ZirkularStimme.objects.filter(zirkular=z)}
    return zaehlen(list(z.liegenschaft.einheiten.all()), stimmen, z.mehrheitsart,
                   z.liegenschaft.wertquote_total)


def vollstaendig(z):
    """Haben alle Einheiten abgestimmt?"""
    return ZirkularStimme.objects.filter(zirkular=z).count() >= z.liegenschaft.einheiten.count()


@transaction.atomic
def feststellen(z, ergebnis, *, beschlusstext=None, user=None, heute=None):
    heute = heute or timezone.localdate()
    if z.status != z.LAUFEND:
        raise BeschlussFehler('Nur ein laufender Beschluss lässt sich feststellen.')
    if ergebnis not in (Traktandum.ANGENOMMEN, Traktandum.ABGELEHNT):
        raise BeschlussFehler(f'Ungültiges Ergebnis «{ergebnis}».')
    if heute <= z.frist_bis and not vollstaendig(z):
        raise BeschlussFehler('Die Frist läuft noch und nicht alle Einheiten haben abgestimmt.')
    zz = auswerten(z)
    if zz['widerspruch']:
        raise BeschlussFehler('Widersprüchliche Stimmen desselben Eigentümers — bitte zuerst korrigieren.')
    for feld in ('ja_koepfe', 'nein_koepfe', 'enthaltung_koepfe',
                 'ja_quoten', 'nein_quoten', 'enthaltung_quoten'):
        setattr(z, feld, zz[feld])
    z.ergebnis = ergebnis
    if beschlusstext is not None:
        z.beschlusstext = beschlusstext
    z.status = z.ABGESCHLOSSEN
    z.festgestellt_am = timezone.now()
    z.save()
    if ergebnis == Traktandum.ANGENOMMEN and z.vollzug_aufgabe:
        from core.models import Pendenz
        Pendenz.objects.update_or_create(
            liegenschaft=z.liegenschaft, quelle=f'stweg:zirkular:{z.pk}',
            defaults={'titel': z.vollzug_aufgabe[:200], 'beschreibung': f'Zirkularbeschluss «{z.titel}»',
                      'kategorie': 'aufgabe', 'faellig_am': z.vollzug_faellig_am, 'erstellt_von': user})
    return z


def ergebnis_versenden(z):
    """Teilt allen Eigentümern das Ergebnis mit (auch denen, die nicht abgestimmt haben)."""
    if z.status != z.ABGESCHLOSSEN:
        raise VersammlungsFehler(['Das Ergebnis ist noch nicht festgestellt.'])
    eig, _ = _empfaenger(z)
    schon = _schon_gesendet(z, ZirkularVersand.ERGEBNIS)
    org = z.liegenschaft.organisation
    pdf = zirkular_pdf(z)
    neu = []
    for e in eig:
        if e.pk in schon:
            continue
        html = ("<html><body style='font-family:Arial,sans-serif;line-height:1.5'>"
                f"<p>Guten Tag {e.firma_oder_name}</p>"
                f"<p>die Abstimmung «{z.titel}» ist abgeschlossen: <strong>{z.get_ergebnis_display()}</strong>. "
                "Einzelheiten in der Beilage.</p>"
                f"<p>Freundliche Grüsse<br>{org.firma}</p></body></html>")
        neu.append(_senden(z, ZirkularVersand.ERGEBNIS, e, f'Ergebnis: {z.titel}', html,
                           f'Ergebnis_{z.pk}.pdf', pdf))
    z.ergebnis_versendet_am = z.ergebnis_versendet_am or timezone.now()
    z.save(update_fields=['ergebnis_versendet_am'])
    return neu
