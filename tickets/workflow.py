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
        ok = send_ticket_email(adresse, betreff or v_betreff, text or v_text)
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
            weitere_anhaenge=anhaenge)
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
