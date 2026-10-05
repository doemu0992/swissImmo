# tickets/workflow.py
"""State-Machine und Sicherheitssperre für Mängel-Tickets (SchadenMeldung).

Statusfluss (Regelweg)::

    neu -> in_bearbeitung -> wartet_auf_rechnung -> erledigt
              (Handwerker       (Arbeit gemacht,    (Rechnung
               zugewiesen)       Rechnung fehlt)     verknüpft)

Dazu die Wartezustände ``warte_auf_mieter`` / ``warte_auf_handwerker`` und die
Wiedereröffnung ``erledigt -> in_bearbeitung``.

DIE SPERRE

Ein Ticket mit Handwerkerauftrag darf nicht «erledigt» werden, solange ein
Auftrag ohne verknüpfte Kreditorenrechnung besteht. Geprüft wird an den
Aufträgen, nicht am Statuswort «warte_auf_handwerker»: Wer den Status
übersprungen hat, soll die Sperre nicht umgehen. Ein Auftrag mit Status
``storniert`` zählt nicht (der Handwerker hat nicht gearbeitet).

Die Sperre sitzt in ``SchadenMeldung.save()`` (über ``abschluss_pruefen``) und
gilt damit für Ansicht, Admin und Skripte. Nicht erfasst:
``QuerySet.update()`` — wie bei jeder Modellregel.
"""
import logging

from django.core.exceptions import ValidationError
from django.db import transaction

logger = logging.getLogger(__name__)

#: Erlaubte Übergänge. Alles andere wird abgelehnt.
UEBERGAENGE = {
    'neu':                  {'in_bearbeitung', 'warte_auf_mieter', 'erledigt'},
    'in_bearbeitung':       {'warte_auf_mieter', 'warte_auf_handwerker',
                             'wartet_auf_rechnung', 'erledigt'},
    'warte_auf_mieter':     {'in_bearbeitung', 'warte_auf_handwerker', 'erledigt'},
    'warte_auf_handwerker': {'in_bearbeitung', 'warte_auf_mieter',
                             'wartet_auf_rechnung'},
    'wartet_auf_rechnung':  {'in_bearbeitung', 'erledigt'},
    'erledigt':             {'in_bearbeitung'},
}

AUFTRAG_STORNIERT = 'storniert'


class UngueltigerUebergang(ValidationError):
    """Der Statuswechsel ist im Fluss nicht vorgesehen."""


class AbschlussGesperrt(ValidationError):
    """Abschluss verweigert: Handwerkerrechnung fehlt."""


def erlaubte_ziele(status):
    """Status, auf die ein Ticket von ``status`` aus wechseln darf (sortiert)."""
    return sorted(UEBERGAENGE.get(status, ()))


def auftraege_ohne_rechnung(ticket):
    """Aufträge des Tickets, denen noch keine Kreditorenrechnung zugeordnet ist."""
    if not ticket.pk:
        return []
    return list(ticket.handwerker_auftraege
                .filter(kreditoren_rechnung__isnull=True)
                .exclude(status=AUFTRAG_STORNIERT))


class KostentraegerFehlt(ValidationError):
    """STWEG: Bauteil und Kostenträger (Sonderrecht oder gemeinschaftlich) sind nicht deklariert."""


def kostentraeger_pruefen(ticket):
    """Wirft ``KostentraegerFehlt``, wenn ein STWEG-Ticket Bauteil und Kostenträger nicht (richtig) deklariert hat.
    Ausserhalb einer STWEG tut es nichts. Siehe ``stweg.bauteile``."""
    from stweg.bauteile import probleme
    fehler = probleme(ticket)
    if fehler:
        raise KostentraegerFehlt(fehler, code='kostentraeger_fehlt')


def abschluss_pruefen(ticket):
    """Wirft ``AbschlussGesperrt``, wenn das Ticket nicht erledigt werden darf.

    Ein Ticket, das in der Datenbank schon «erledigt» ist, wird nicht erneut
    geprüft: Altbestand ohne Rechnung soll sich weiter speichern lassen.
    """
    if not ticket.pk:
        return
    alt = (type(ticket)._base_manager.filter(pk=ticket.pk)
           .values_list('status', flat=True).first())
    if alt == 'erledigt':
        return
    kostentraeger_pruefen(ticket)
    offen = auftraege_ohne_rechnung(ticket)
    if offen:
        namen = ', '.join(str(a.handwerker) for a in offen)
        raise AbschlussGesperrt(
            f"Ticket #{ticket.pk} kann nicht erledigt werden: Für den Auftrag an "
            f"{namen} ist noch keine Kreditorenrechnung verknüpft.",
            code='rechnung_fehlt')


#: Statuswechsel, über die der Melder automatisch informiert wird, und die
#: Vorlage dafür. Alles andere (z. B. «wartet_auf_rechnung») ist intern: den
#: Mieter geht die Rechnungsstellung des Handwerkers nichts an.
MELDER_INFO = {
    'in_bearbeitung': 'ticket_melder_status',
    'warte_auf_mieter': 'ticket_melder_status',
    'erledigt': 'ticket_erledigt',
}


def wechsle_status(ticket, neu, melder_informieren=False):
    """Statuswechsel nach dem Flussplan; speichert das Ticket.

    Gleicher Status ist ein No-op. Unbekannter Status oder nicht erlaubter
    Übergang -> ``UngueltigerUebergang``; fehlende Rechnung beim Abschluss ->
    ``AbschlussGesperrt`` (aus ``save()``). Bei einem Fehler bleibt der
    Status am Objekt unverändert.

    Mit ``melder_informieren`` geht nach erfolgreichem Wechsel automatisch eine
    Mail an den Melder (nur für Status aus ``MELDER_INFO``); Mailfehler
    verhindern den Statuswechsel nie.
    """
    alt = ticket.status
    if neu == alt:
        return ticket
    if neu not in UEBERGAENGE:
        raise UngueltigerUebergang(f"Unbekannter Status «{neu}».", code='unbekannt')
    if neu not in UEBERGAENGE.get(alt, ()):
        raise UngueltigerUebergang(
            f"Übergang {alt} -> {neu} ist nicht vorgesehen.", code='uebergang')
    ticket.status = neu
    try:
        ticket.save()
    except ValidationError:
        ticket.status = alt
        raise
    if melder_informieren and neu in MELDER_INFO:
        melder_benachrichtigen(ticket, MELDER_INFO[neu])
    return ticket


def reply_to(ticket):
    """Antwortadresse der Verwaltung des Tickets: ihr aktives «Antworten»-Postfach.

    Das ist genau das Postfach, das ``fetch_replies`` für diese Verwaltung abruft —
    eine Antwort auf eine Ticket-Mail landet damit im richtigen Bestand. Ohne
    eingerichtetes Postfach (oder ohne Adresse als Benutzername) ``None``: dann
    gilt die globale Adresse. Der Absender (From) bleibt global — er hängt am
    SMTP-Konto.
    """
    from core.models import Postfach
    pf = (Postfach.alle_organisationen
          .filter(organisation_id=ticket.organisation_id,
                  zweck=Postfach.ZWECK_ANTWORTEN, aktiv=True)
          .order_by('pk').first())
    return pf.benutzer if pf and '@' in (pf.benutzer or '') else None


def melder_adresse(ticket):
    """E-Mail-Adresse des Melders (Formular oder Mieterstamm), sonst ''."""
    return ticket.email_melder or (
        ticket.gemeldet_von.email if ticket.gemeldet_von_id and ticket.gemeldet_von.email else '')


def melder_benachrichtigen(ticket, kategorie, handwerker=None, text=None, betreff=None):
    """Mail an den Melder aus der Vorlage ``kategorie``; Verlaufseintrag bei Erfolg.

    Der Eintrag ist NICHT intern und stammt von der Verwaltung: Der Mieter sieht
    ihn im Portal, und er zählt für den Befund «ohne Echo» als Antwort.
    Gibt True zurück, wenn tatsächlich versendet wurde. Fehler werden
    protokolliert, nie geworfen.
    """
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    from .models import TicketNachricht
    adresse = melder_adresse(ticket)
    if not adresse:
        return False
    try:
        v_betreff, v_text = vorlage_text(kategorie, ticket, handwerker=handwerker)
        ok = send_ticket_email(adresse, betreff or v_betreff, text or v_text,
                               reply_to=reply_to(ticket))
    except Exception:
        logger.exception("Melder-Mail zu Ticket #%s (%s) fehlgeschlagen", ticket.pk, kategorie)
        return False
    if ok:
        TicketNachricht.objects.create(
            ticket=ticket, absender_name='Verwaltung', typ='email',
            nachricht=f"{betreff or v_betreff}\n\n{text or v_text}",
            is_intern=False, is_von_verwaltung=True)
    return ok


def _protokoll(ticket, text):
    from .models import TicketNachricht
    TicketNachricht.objects.create(ticket=ticket, absender_name='System',
                                   typ='system', nachricht=text, is_intern=True)


def handwerker_zuweisen(ticket, handwerker, bemerkung=''):
    """Handwerker zuweisen: Auftrag anlegen, Verlauf schreiben, Status -> in_bearbeitung.

    Ein Handwerker einer anderen Organisation wird abgelehnt.
    """
    from .models import HandwerkerAuftrag
    if handwerker.organisation_id != ticket.organisation_id:
        raise ValidationError('Der Handwerker gehört nicht zur Organisation des Tickets.',
                              code='fremde_organisation')
    kostentraeger_pruefen(ticket)           # STWEG: erst deklarieren, wer die Kosten trägt, dann beauftragen
    with transaction.atomic():
        auftrag = HandwerkerAuftrag.objects.create(
            ticket=ticket, handwerker=handwerker, bemerkung=bemerkung, status='offen')
        _protokoll(ticket, f"Auftrag an {handwerker.firma} vergeben.")
        if ticket.status == 'neu':
            wechsle_status(ticket, 'in_bearbeitung')
    return auftrag


def arbeitsauftrag_senden(auftrag, text=''):
    """Arbeitsauftrag als PDF per E-Mail an den Handwerker.

    Text: ``text`` (Freitext der Verwaltung) sonst Vorlage ``ticket_handwerker``.
    Gibt ``(pdf_bytes, versendet)`` zurück. Ohne E-Mail-Adresse des Handwerkers
    entsteht das PDF trotzdem (zum Ausdrucken), ``versendet`` ist dann False.
    Der Verlauf hält fest, WAS an WEN ging (``handwerker_mail``).
    """
    from core.services.handwerker_auftrag_pdf import generate_auftrag_pdf
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_via_hoststar
    from .models import TicketNachricht

    ticket, hw = auftrag.ticket, auftrag.handwerker
    pdf = generate_auftrag_pdf(auftrag, ticket.organisation)
    versendet = False
    betreff, inhalt = vorlage_text('ticket_handwerker', ticket, handwerker=hw)
    inhalt = text or auftrag.bemerkung or inhalt
    anhaenge = []
    if ticket.foto:
        try:
            import os
            with ticket.foto.open('rb') as f:
                anhaenge.append((os.path.basename(ticket.foto.name), f.read(), 'image/jpeg'))
        except Exception:
            logger.warning("Foto zu Ticket #%s nicht lesbar, Auftrag geht ohne", ticket.pk)
    if hw.email:
        html = ("<html><body style='font-family:Arial,sans-serif'>"
                + inhalt.replace('\n', '<br>') + "</body></html>")
        versendet = send_via_hoststar(
            hw.email, betreff, html, f"Reparaturauftrag_{auftrag.id}.pdf", pdf,
            weitere_anhaenge=anhaenge, reply_to=reply_to(ticket))
    TicketNachricht.objects.create(
        ticket=ticket, absender_name='System', typ='handwerker_mail',
        empfaenger_handwerker=hw, is_intern=True, is_von_verwaltung=True,
        nachricht=(f"Arbeitsauftrag #{auftrag.id} (PDF) per E-Mail an {hw.firma} gesendet."
                   if versendet else
                   f"Arbeitsauftrag #{auftrag.id} für {hw.firma} erzeugt, NICHT versendet "
                   f"({'keine E-Mail-Adresse' if not hw.email else 'Versand fehlgeschlagen'})."))
    return pdf, versendet


def auftrag_vergeben(ticket, handwerker, text=''):
    """Der ganze Weg in einem Griff: zuweisen, Auftrag (PDF) senden, Mieter informieren.

    Rückgabe: ``dict(auftrag, handwerker_versendet, melder_informiert)``. Die
    Zuweisung gilt auch dann, wenn ein Versand scheitert — der Verlauf nennt es.
    """
    auftrag = handwerker_zuweisen(ticket, handwerker, text)
    _pdf, hw_ok = arbeitsauftrag_senden(auftrag, text)
    melder_ok = melder_benachrichtigen(ticket, 'ticket_melder', handwerker=handwerker)
    return {'auftrag': auftrag, 'handwerker_versendet': hw_ok, 'melder_informiert': melder_ok}


def rechnung_verknuepfen(auftrag, rechnung, abschliessen=True):
    """Eingehende Handwerkerrechnung (Kreditor) mit dem Auftrag verknüpfen.

    Setzt, falls leer, ``kosten_effektiv`` aus dem Rechnungsbetrag. Sind danach
    alle Aufträge des Tickets belegt und ``abschliessen`` gesetzt, geht das
    Ticket über «wartet_auf_rechnung» auf «erledigt». Die Rechnung muss zur
    selben Organisation gehören und darf nicht storniert sein.
    """
    ticket = auftrag.ticket
    if rechnung.organisation_id != ticket.organisation_id:
        raise ValidationError('Die Rechnung gehört nicht zur Organisation des Tickets.',
                              code='fremde_organisation')
    if rechnung.status == 'storniert':
        raise ValidationError('Eine stornierte Rechnung kann nicht verknüpft werden.',
                              code='storniert')
    abgeschlossen = False
    with transaction.atomic():
        auftrag.kreditoren_rechnung = rechnung
        if auftrag.kosten_effektiv is None and rechnung.betrag is not None:
            auftrag.kosten_effektiv = rechnung.betrag
        auftrag.save()
        _protokoll(ticket, f"Handwerkerrechnung {rechnung.lieferant} "
                           f"(CHF {rechnung.betrag}) mit Auftrag #{auftrag.id} verknüpft.")
        if abschliessen and not auftraege_ohne_rechnung(ticket):
            if ticket.status in ('in_bearbeitung', 'warte_auf_handwerker'):
                wechsle_status(ticket, 'wartet_auf_rechnung')
            if ticket.status in ('neu', 'in_bearbeitung', 'warte_auf_mieter',
                                 'wartet_auf_rechnung'):
                # Mail erst NACH dem Commit: ein Rollback darf keine
                # «Schaden behoben»-Mail hinterlassen.
                wechsle_status(ticket, 'erledigt')
                abgeschlossen = True
    if abgeschlossen:
        melder_benachrichtigen(ticket, 'ticket_erledigt')
    return auftrag


# ---------------------------------------------------------------------------
# Freitext an den Handwerker, Termine, eingehende Antworten
# ---------------------------------------------------------------------------

def nachricht_an_handwerker(auftrag, text, absender='Verwaltung'):
    """Freitext-Mail an den Handwerker eines Auftrags; Verlaufseintrag.

    Der Betreff trägt «Ticket #N» — seine Antwort landet über ``fetch_replies``
    wieder im Ticket. Gibt True zurück, wenn versendet wurde.
    """
    from core.utils.email_service import send_ticket_email
    from .models import TicketNachricht
    text = (text or '').strip()
    hw, ticket = auftrag.handwerker, auftrag.ticket
    if not text or not hw.email:
        return False
    betreff = f"{ticket.titel} (Ticket #{ticket.pk})"
    try:
        ok = send_ticket_email(hw.email, betreff, text, reply_to=reply_to(ticket))
    except Exception:
        logger.exception("Mail an Handwerker zu Ticket #%s fehlgeschlagen", ticket.pk)
        ok = False
    TicketNachricht.objects.create(
        ticket=ticket, absender_name=absender, typ='handwerker_mail',
        empfaenger_handwerker=hw, is_intern=True, is_von_verwaltung=True,
        nachricht=text if ok else f"[NICHT versendet] {text}")
    return ok


def _ics(auftrag, termin_am, absagen=False):
    """Kalendereintrag (iCalendar) für den Termin; 1 Stunde, UTC."""
    from datetime import timedelta, timezone as dt_tz
    t = auftrag.ticket
    start = termin_am.astimezone(dt_tz.utc)
    fmt = '%Y%m%dT%H%M%SZ'
    def esc(x):
        return str(x).replace('\\', '\\\\').replace(';', '\;').replace(',', '\\,').replace('\n', '\\n')
    zeilen = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//swissImmo//Ticket//DE',
              'METHOD:CANCEL' if absagen else 'METHOD:PUBLISH', 'BEGIN:VEVENT',
              f'UID:auftrag-{auftrag.pk}@swissimmo',
              f"DTSTAMP:{start.strftime(fmt)}", f"DTSTART:{start.strftime(fmt)}",
              f"DTEND:{(start + timedelta(hours=1)).strftime(fmt)}",
              f"SUMMARY:{esc(f'Reparatur: {t.titel} (Ticket #{t.pk})')}",
              f"DESCRIPTION:{esc(f'{auftrag.handwerker.firma} — Ticket #{t.pk}')}",
              'STATUS:CANCELLED' if absagen else 'STATUS:CONFIRMED',
              'END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(zeilen) + '\r\n'


def _termin_text(termin_am):
    from django.utils import timezone
    return timezone.localtime(termin_am).strftime('%d.%m.%Y, %H:%M Uhr')


def _termin_mails(auftrag, termin_am, kat_mieter, kat_hw, absagen=False):
    """Mails an Mieter und Handwerker; gibt (mieter_ok, hw_ok) zurück."""
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_via_hoststar
    ticket, hw = auftrag.ticket, auftrag.handwerker
    ics = [('Termin.ics', _ics(auftrag, termin_am, absagen), 'text/calendar')]
    text = _termin_text(termin_am)

    def senden(adresse, kat):
        if not adresse:
            return False
        try:
            betreff, inhalt = vorlage_text(kat, ticket, handwerker=hw, termin=text)
            html = ("<html><body style='font-family:Arial,sans-serif'>"
                    + inhalt.replace('\n', '<br>') + "</body></html>")
            return send_via_hoststar(adresse, betreff, html, weitere_anhaenge=ics,
                                     reply_to=reply_to(ticket))
        except Exception:
            logger.exception("Termin-Mail zu Ticket #%s fehlgeschlagen", ticket.pk)
            return False
    return senden(melder_adresse(ticket), kat_mieter), senden(hw.email, kat_hw)


def termin_festlegen(auftrag, termin_am):
    """Termin setzen oder verschieben: Mieter und Handwerker bekommen Mail + Kalendereintrag.

    Das Ticket geht (falls «in Bearbeitung») auf «Warte auf Handwerker».
    """
    from django.utils import timezone
    if termin_am is None:
        raise ValidationError('Kein Termin angegeben.', code='termin_fehlt')
    if timezone.is_naive(termin_am):
        termin_am = timezone.make_aware(termin_am)
    if auftrag.status == AUFTRAG_STORNIERT:
        raise ValidationError('Der Auftrag ist storniert.', code='storniert')
    ticket = auftrag.ticket
    with transaction.atomic():
        auftrag.termin_am, auftrag.termin_status = termin_am, 'vereinbart'
        auftrag.save(update_fields=['termin_am', 'termin_status'])
        if ticket.status == 'in_bearbeitung':
            wechsle_status(ticket, 'warte_auf_handwerker')
    m_ok, h_ok = _termin_mails(auftrag, termin_am, 'ticket_termin', 'ticket_termin_handwerker')
    _protokoll(ticket, f"Termin {auftrag.handwerker.firma}: {_termin_text(termin_am)} "
                       f"(Mieter {'informiert' if m_ok else 'NICHT informiert'}, "
                       f"Handwerker {'informiert' if h_ok else 'NICHT informiert'}).")
    return m_ok, h_ok


def termin_absagen(auftrag):
    """Termin absagen: beide Seiten erfahren es (Kalendereintrag wird storniert)."""
    if auftrag.termin_status != 'vereinbart' or not auftrag.termin_am:
        raise ValidationError('Es gibt keinen vereinbarten Termin.', code='kein_termin')
    alt = auftrag.termin_am
    auftrag.termin_status = 'abgesagt'
    auftrag.save(update_fields=['termin_status'])
    m_ok, h_ok = _termin_mails(auftrag, alt, 'ticket_termin_abgesagt',
                               'ticket_termin_abgesagt', absagen=True)
    _protokoll(auftrag.ticket, f"Termin {_termin_text(alt)} abgesagt "
                               f"(Mieter {'informiert' if m_ok else 'NICHT informiert'}, "
                               f"Handwerker {'informiert' if h_ok else 'NICHT informiert'}).")
    return m_ok, h_ok


def antwort_zuordnen(ticket, absender, inhalt):
    """Eingehende Mail einem Ticket zuordnen und den Fluss nachführen.

    ``absender`` ist der rohe From-Header. Kommt er von der Adresse eines
    Handwerkers, der einen Auftrag am Ticket hat, wird die Nachricht als
    Handwerker-Antwort geführt; sonst als Antwort des Melders. Wartete das
    Ticket auf genau diese Seite, geht es zurück auf «In Bearbeitung» — die
    Verwaltung ist wieder am Zug. Gibt ``'handwerker'`` oder ``'melder'`` zurück.
    """
    from email.utils import parseaddr
    from .models import TicketNachricht
    adresse = parseaddr(absender)[1].strip().lower()
    hw = None
    if adresse:
        for a in ticket.handwerker_auftraege.select_related('handwerker'):
            if a.handwerker.email and a.handwerker.email.strip().lower() == adresse:
                hw = a.handwerker
                break
    if hw is not None:
        TicketNachricht.objects.create(
            ticket=ticket, absender_name=hw.firma, typ='handwerker_mail',
            empfaenger_handwerker=hw, nachricht=inhalt, is_intern=True,
            is_von_verwaltung=False, gelesen=False)
        wartet_auf = 'warte_auf_handwerker'
        seite = 'handwerker'
    else:
        TicketNachricht.objects.create(
            ticket=ticket, absender_name=absender, typ='mail_antwort',
            nachricht=inhalt, gelesen=False)
        wartet_auf = 'warte_auf_mieter'
        seite = 'melder'
    ticket.gelesen = False
    ticket.save(update_fields=['gelesen'])
    if ticket.status == wartet_auf:
        try:
            wechsle_status(ticket, 'in_bearbeitung')
        except ValidationError:
            logger.exception("Ticket #%s: Rückwechsel nach Antwort nicht möglich", ticket.pk)
    return seite


def auftrag_stornieren(auftrag, grund=''):
    """Auftrag stornieren: Handwerker informieren, Termin absagen, Ticket zurück auf «In Bearbeitung».

    Nicht stornierbar: ein erledigter oder schon stornierter Auftrag und einer mit
    verknüpfter Rechnung (die Rechnung wurde gestellt — erst die Verknüpfung klären).
    Ein offener Eigentümer-Freigabe-Antrag verfällt (``nicht_noetig``): zu einem
    stornierten Auftrag gibt es nichts freizugeben. Wartete das Ticket nur auf diesen
    Auftrag (``Warte auf Handwerker`` / ``Wartet auf Rechnung``) und gibt es keinen
    anderen aktiven, geht es zurück auf «In Bearbeitung» — die Verwaltung ist am Zug.
    """
    from core.services.ticket_workflow import vorlage_text
    from core.utils.email_service import send_ticket_email
    ticket, hw = auftrag.ticket, auftrag.handwerker
    if auftrag.status in (AUFTRAG_STORNIERT, 'erledigt'):
        raise ValidationError('Der Auftrag ist schon abgeschlossen oder storniert.', code='nicht_stornierbar')
    if auftrag.kreditoren_rechnung_id:
        raise ValidationError('Zum Auftrag ist schon eine Rechnung verknüpft — kein Storno.', code='rechnung')
    mit_termin = auftrag.termin_status == 'vereinbart' and auftrag.termin_am
    with transaction.atomic():
        if mit_termin:
            termin_absagen(auftrag)
        auftrag.status = AUFTRAG_STORNIERT
        if auftrag.freigabe_status == 'ausstehend':
            auftrag.freigabe_status = 'nicht_noetig'
            auftrag.freigabe_datum = None
        auftrag.save(update_fields=['status', 'freigabe_status', 'freigabe_datum'])
        grund = (grund or '').strip()
        _protokoll(ticket, f"Auftrag #{auftrag.id} an {hw.firma} storniert"
                           + (f": {grund}" if grund else "."))
        aktive = ticket.handwerker_auftraege.exclude(status=AUFTRAG_STORNIERT).exclude(status='erledigt')
        if (not aktive.exists()
                and ticket.status in ('warte_auf_handwerker', 'wartet_auf_rechnung')):
            wechsle_status(ticket, 'in_bearbeitung')
    ok = False
    if hw.email:
        try:
            betreff, text = vorlage_text('ticket_auftrag_storniert', ticket, handwerker=hw)
            if grund:
                text += f"\n\nGrund: {grund}"
            ok = send_ticket_email(hw.email, betreff, text, reply_to=reply_to(ticket))
        except Exception:
            logger.exception("Storno-Mail zu Ticket #%s fehlgeschlagen", ticket.pk)
    from .models import TicketNachricht
    TicketNachricht.objects.create(
        ticket=ticket, absender_name='System', typ='handwerker_mail', empfaenger_handwerker=hw,
        is_intern=True, is_von_verwaltung=True,
        nachricht=(f"Storno an {hw.firma} per E-Mail gesendet." if ok else
                   f"Storno an {hw.firma} NICHT versendet "
                   f"({'keine E-Mail-Adresse' if not hw.email else 'Versand fehlgeschlagen'})."))
    return ok
