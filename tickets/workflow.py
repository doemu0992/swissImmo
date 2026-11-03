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

DER AUSDRÜCKLICHE WEG «OHNE RECHNUNG ABSCHLIESSEN»

Es gibt reale Fälle ohne Handwerkerrechnung (Garantie/Kulanz, Rechnung geht an den
Eigentümer, Auftrag nicht ausgeführt, Eigenleistung, Rechnung folgt). Die Sperre
wird dafür nicht umgangen, sondern ihr wird eine Freigabe vorgelegt:
``ohne_rechnung_freigeben`` hält am Auftrag Grund, Bemerkung, Person und Zeit fest;
``auftraege_ohne_rechnung`` (und damit ``abschluss_pruefen``) zählt einen so
freigegebenen Auftrag nicht mehr. ``ohne_rechnung_abschliessen`` ist der ganze Weg
in einem Griff (auch ab «Warte auf Handwerker»). «Rechnung folgt später» legt eine
Pendenz an, die das Verknüpfen der Rechnung erledigt.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

logger = logging.getLogger(__name__)

#: Ab diesem geschätzten Betrag (CHF) braucht eine Reparatur die Freigabe der
#: Eigentümerschaft. Stand bis Modul 3 lokal in `fw_auftrag_kosten`; hier,
#: damit die Offerte aus dem Handwerkerportal dieselbe Schwelle nimmt.
REPARATUR_FREIGABE_SCHWELLE = Decimal('1000')

#: Die Freigabe gilt für die geschätzte Summe. Liegt ein neuer Betrag mehr als
#: 20 % darüber, braucht es eine Nachfreigabe (Stresstest 30.09.2026).
ABWEICHUNG_NACHFREIGABE = Decimal('1.20')

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

#: Zusätzlich erlaubt, wenn der Abschluss ausdrücklich «ohne Rechnung» geschieht.
UEBERGAENGE_OHNE_RECHNUNG = {
    'warte_auf_handwerker': {'erledigt'},
}

AUFTRAG_STORNIERT = 'storniert'

#: Gründe, bei denen die Rechnung noch erwartet wird: Sie bekommen eine Pendenz.
OHNE_RECHNUNG_ERWARTET = ('folgt_spaeter', 'noch_nicht_erfasst')
#: Wählbare Fristen (Tage) für die Pendenz «Rechnung ausstehend».
OHNE_RECHNUNG_FRISTEN = (7, 14, 30, 60, 90)
OHNE_RECHNUNG_FRIST_STANDARD = 30


class UngueltigerUebergang(ValidationError):
    """Der Statuswechsel ist im Fluss nicht vorgesehen."""


class AbschlussGesperrt(ValidationError):
    """Abschluss verweigert: Handwerkerrechnung fehlt."""


def erlaubte_ziele(status):
    """Status, auf die ein Ticket von ``status`` aus wechseln darf (sortiert)."""
    return sorted(UEBERGAENGE.get(status, ()))


def auftraege_ohne_rechnung(ticket, freigegebene_mitzaehlen=False):
    """Aufträge des Tickets, die den Abschluss sperren: ohne (gültige) Kreditorenrechnung.

    Eine stornierte Rechnung zählt nicht als Rechnung. Ein Auftrag, den die
    Verwaltung ausdrücklich «ohne Rechnung» freigegeben hat, sperrt nicht mehr
    (``freigegebene_mitzaehlen=True`` liefert ihn trotzdem, für die Anzeige).
    """
    if not ticket.pk:
        return []
    qs = (ticket.handwerker_auftraege
          .filter(Q(kreditoren_rechnung__isnull=True) | Q(kreditoren_rechnung__status='storniert'))
          .exclude(status=AUFTRAG_STORNIERT)
          .select_related('handwerker', 'kreditoren_rechnung'))
    if not freigegebene_mitzaehlen:
        qs = qs.filter(ohne_rechnung_grund='')
    return list(qs)


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
        raise AbschlussGesperrt(sperre_text(ticket, offen), code='rechnung_fehlt')


def hat_sperrende_auftraege(ticket):
    """Wie ``auftraege_ohne_rechnung``, aber in Python über die (vorgeladenen) Aufträge — für Listen
    und das Board, ohne Abfrage je Ticket."""
    for a in ticket.handwerker_auftraege.all():
        if a.status == AUFTRAG_STORNIERT or a.ohne_rechnung_grund:
            continue
        if not a.kreditoren_rechnung_id or a.kreditoren_rechnung.status == 'storniert':
            return True
    return False


def passende_rechnungen(auftrag, kandidaten):
    """Von den unverknüpften Rechnungen die, die zum Auftrag passen könnten: gleicher Lieferant
    (Name enthält die Firma des Handwerkers oder umgekehrt, ohne Gross-/Kleinschreibung) oder
    Betrag gleich den effektiven bzw. geschätzten Kosten. Nur ein Hinweis — verknüpft wird per Klick."""
    firma = (auftrag.handwerker.firma or '').strip().lower()
    betraege = {b for b in (auftrag.kosten_effektiv, auftrag.kosten_geschaetzt) if b}
    treffer = []
    for r in kandidaten:
        lieferant = (r.lieferant or '').strip().lower()
        gleicher_lieferant = bool(firma and lieferant and (firma in lieferant or lieferant in firma))
        gleicher_betrag = r.betrag is not None and r.betrag in betraege
        if gleicher_lieferant or gleicher_betrag:
            treffer.append(r)
    return treffer


def sperre_text(ticket, offen=None, ohne_rechnung_moeglich=True):
    """Die Meldung der Sperre — mit den Wegen, wie es weitergeht (statt nur «gesperrt»)."""
    offen = auftraege_ohne_rechnung(ticket) if offen is None else offen
    namen = ', '.join(str(a.handwerker) for a in offen)
    text = (f"Ticket #{ticket.pk} kann nicht erledigt werden: Für den Auftrag an "
            f"{namen} ist noch keine Kreditorenrechnung verknüpft. Weiter: "
            f"(1) die Rechnung beim Auftrag verknüpfen (Reiter «Handwerker & Kosten»)")
    if ohne_rechnung_moeglich:
        text += (", oder (2) «Ohne Rechnung abschliessen» mit Begründung "
                 "(kostenlos/Garantie, Rechnung direkt an den Eigentümer, Rechnung folgt später, "
                 "Auftrag nicht ausgeführt, Eigenleistung).")
    else:
        text += ". Ohne Rechnung abschliessen darf nur die Verwaltung."
    return text


#: Statuswechsel, über die der Melder automatisch informiert wird, und die
#: Vorlage dafür. Alles andere (z. B. «wartet_auf_rechnung») ist intern: den
#: Mieter geht die Rechnungsstellung des Handwerkers nichts an.
MELDER_INFO = {
    'in_bearbeitung': 'ticket_melder_status',
    'warte_auf_mieter': 'ticket_melder_status',
    'erledigt': 'ticket_erledigt',
}


def wechsle_status(ticket, neu, melder_informieren=False, ohne_rechnung=False):
    """Statuswechsel nach dem Flussplan; speichert das Ticket.

    Gleicher Status ist ein No-op. Unbekannter Status oder nicht erlaubter
    Übergang -> ``UngueltigerUebergang``; fehlende Rechnung beim Abschluss ->
    ``AbschlussGesperrt`` (aus ``save()``). Bei einem Fehler bleibt der
    Status am Objekt unverändert.

    ``ohne_rechnung`` öffnet den ausdrücklichen Weg ``warte_auf_handwerker -> erledigt``
    (``UEBERGAENGE_OHNE_RECHNUNG``); die Sperre prüft trotzdem, ob die Aufträge
    eine Rechnung oder eine Freigabe haben. Nur ``ohne_rechnung_abschliessen`` setzt es.

    Mit ``melder_informieren`` geht nach erfolgreichem Wechsel automatisch eine
    Mail an den Melder (nur für Status aus ``MELDER_INFO``); Mailfehler
    verhindern den Statuswechsel nie.
    """
    alt = ticket.status
    if neu == alt:
        return ticket
    if neu not in UEBERGAENGE:
        raise UngueltigerUebergang(f"Unbekannter Status «{neu}».", code='unbekannt')
    erlaubt = set(UEBERGAENGE.get(alt, ()))
    if ohne_rechnung:
        erlaubt |= UEBERGAENGE_OHNE_RECHNUNG.get(alt, set())
    if neu not in erlaubt:
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
        # Handwerkerportal (Modul 3): Der Link öffnet genau diesen Auftrag. Er
        # entsteht nur, wenn eine Mail hinausgeht — der Klartext steht nirgends
        # sonst, ein Link ohne Empfänger wäre verloren. Ein erneuter Versand
        # ersetzt den alten Link.
        from .handwerker_zugang import link_erzeugen, link_url
        url = link_url(link_erzeugen(auftrag))
        inhalt = (f"{inhalt}\n\nAuftrag online ansehen, Termin bestätigen, Offerte oder "
                  f"Rechnung hochladen:\n{url}")
        html = ("<html><body style='font-family:Arial,sans-serif'>"
                + inhalt.replace('\n', '<br>').replace(url, f"<a href='{url}'>{url}</a>")
                + "</body></html>")
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
    if auftrag.kreditoren_rechnung_id and auftrag.kreditoren_rechnung_id != rechnung.pk \
            and auftrag.kreditoren_rechnung.status != 'storniert':
        raise ValidationError('Zum Auftrag ist schon eine Rechnung verknüpft.', code='doppelt')
    if rechnung.handwerker_auftraege.exclude(pk=auftrag.pk).exists():
        raise ValidationError('Die Rechnung hängt schon an einem anderen Auftrag.', code='vergeben')
    abgeschlossen = False
    with transaction.atomic():
        auftrag.kreditoren_rechnung = rechnung
        if auftrag.kosten_effektiv is None and rechnung.betrag is not None:
            auftrag.kosten_effektiv = rechnung.betrag
        auftrag.save()
        _protokoll(ticket, f"Handwerkerrechnung {rechnung.lieferant} "
                           f"(CHF {rechnung.betrag}) mit Auftrag #{auftrag.id} verknüpft.")
        _pendenz_rechnung_erledigen(auftrag)
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
# Abschluss ohne Rechnung (ausdrücklicher Weg)
# ---------------------------------------------------------------------------

def _pendenz_quelle(auftrag):
    # Bewusst NICHT «auto:…»: Die Automatik (core/services/automation.py) räumt
    # «auto:rechnung:…» nach dem Ticketstatus ab; diese Pendenz endet mit der Rechnung.
    return f"ticket:rechnung_ausstehend:{auftrag.pk}"


def _pendenz_rechnung_erledigen(auftrag):
    from django.utils import timezone

    from core.models import Pendenz
    Pendenz.objects.filter(quelle=_pendenz_quelle(auftrag), erledigt=False).update(
        erledigt=True, erledigt_am=timezone.localdate())


def ohne_rechnung_freigeben(auftrag, grund, text='', user=None, frist_tage=None):
    """Einen Auftrag ausdrücklich «ohne Rechnung» freigeben: Grund, Person und Zeit festhalten.

    ``grund`` aus ``HandwerkerAuftrag.OHNE_RECHNUNG_CHOICES``; «anderer» braucht eine
    Bemerkung. Bei «Rechnung folgt später» / «liegt vor, noch nicht erfasst» entsteht eine
    Pendenz «Rechnung ausstehend» (``frist_tage``, Standard 30), die das Verknüpfen der
    Rechnung erledigt. Der Verlauf des Tickets hält es fest. Ein Auftrag mit gültiger
    Rechnung oder ein stornierter braucht keine Freigabe -> ``ValidationError``.
    """
    from django.utils import timezone

    from core.models import Pendenz
    from .models import HandwerkerAuftrag
    if grund not in dict(HandwerkerAuftrag.OHNE_RECHNUNG_CHOICES):
        raise ValidationError('Bitte einen Grund wählen.', code='grund')
    text = (text or '').strip()
    if grund == 'anderer' and not text:
        raise ValidationError('Bei «Anderer Grund» bitte eine Bemerkung angeben.', code='text_fehlt')
    if auftrag.status == AUFTRAG_STORNIERT:
        raise ValidationError('Der Auftrag ist storniert.', code='storniert')
    if auftrag.kreditoren_rechnung_id and auftrag.kreditoren_rechnung.status != 'storniert':
        raise ValidationError('Zum Auftrag ist schon eine Rechnung verknüpft.', code='doppelt')
    if frist_tage is None:
        frist_tage = OHNE_RECHNUNG_FRIST_STANDARD
    if frist_tage not in OHNE_RECHNUNG_FRISTEN:
        raise ValidationError('Ungültige Frist.', code='frist')
    ticket = auftrag.ticket
    bezeichnung = dict(HandwerkerAuftrag.OHNE_RECHNUNG_CHOICES)[grund]
    wer = (user.get_full_name() or user.get_username()) if user is not None and user.pk else 'System'
    with transaction.atomic():
        auftrag.ohne_rechnung_grund = grund
        auftrag.ohne_rechnung_text = text
        auftrag.ohne_rechnung_von = user if user is not None and user.pk else None
        auftrag.ohne_rechnung_am = timezone.now()
        auftrag.save(update_fields=['ohne_rechnung_grund', 'ohne_rechnung_text',
                                    'ohne_rechnung_von', 'ohne_rechnung_am'])
        zusatz = ''
        if grund in OHNE_RECHNUNG_ERWARTET:
            faellig = timezone.localdate() + timedelta(days=frist_tage)
            Pendenz.objects.update_or_create(
                quelle=_pendenz_quelle(auftrag),
                defaults={
                    'titel': f"Rechnung ausstehend: Ticket #{ticket.pk} {ticket.titel}"[:200],
                    'beschreibung': (f"Ticket ohne Rechnung abgeschlossen ({bezeichnung}). Rechnung von "
                                     f"{auftrag.handwerker.firma} erfassen und mit Auftrag #{auftrag.pk} "
                                     f"verknüpfen."),
                    'kategorie': 'finanzen', 'faellig_am': faellig, 'erledigt': False,
                    'erledigt_am': None, 'liegenschaft': ticket.liegenschaft,
                    'erstellt_von': user if user is not None and user.pk else None})
            zusatz = f" Pendenz «Rechnung ausstehend» bis {faellig:%d.%m.%Y}."
        _protokoll(ticket, f"Auftrag #{auftrag.pk} an {auftrag.handwerker.firma} ohne Rechnung "
                           f"freigegeben ({bezeichnung}) von {wer}."
                           + (f" Bemerkung: {text}" if text else "") + zusatz)
    return auftrag


def ohne_rechnung_abschliessen(ticket, grund, text='', user=None, frist_tage=None,
                               melder_informieren=False):
    """Das Ticket ausdrücklich ohne Rechnung abschliessen.

    Gibt jedem Auftrag, der den Abschluss sperrt, die Freigabe (gleicher Grund) und setzt
    dann den Status — auch ab «Warte auf Handwerker». Alles in einer Transaktion: scheitert
    der Abschluss (z. B. STWEG: Kostenträger fehlt), bleibt auch keine Freigabe zurück.
    Der Melder bekommt die «erledigt»-Mail erst nach dem Commit. Ohne Aufträge hält der
    Verlauf den Grund fest. Gibt die Liste der freigegebenen Aufträge zurück.
    """
    from .models import HandwerkerAuftrag
    if ticket.status == 'erledigt':
        return []
    if grund not in dict(HandwerkerAuftrag.OHNE_RECHNUNG_CHOICES):
        raise ValidationError('Bitte einen Grund wählen.', code='grund')
    if grund == 'anderer' and not (text or '').strip():
        raise ValidationError('Bei «Anderer Grund» bitte eine Bemerkung angeben.', code='text_fehlt')
    freigegeben = []
    with transaction.atomic():
        for a in auftraege_ohne_rechnung(ticket):
            freigegeben.append(ohne_rechnung_freigeben(a, grund, text, user, frist_tage))
        if not freigegeben:
            wer = (user.get_full_name() or user.get_username()) if user is not None and user.pk else 'System'
            _protokoll(ticket, f"Ohne Rechnung abgeschlossen ({dict(HandwerkerAuftrag.OHNE_RECHNUNG_CHOICES)[grund]}) "
                               f"von {wer}." + (f" Bemerkung: {(text or '').strip()}" if (text or '').strip() else ''))
        wechsle_status(ticket, 'erledigt', ohne_rechnung=True)
    if melder_informieren:
        melder_benachrichtigen(ticket, MELDER_INFO['erledigt'])
    return freigegeben


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
    zeilen = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//immoswiss//Ticket//DE',
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
        from .handwerker_zugang import abschluss_vermerken
        abschluss_vermerken(auftrag)          # Link nur noch lesend, Ablauf in 30 Tagen (E6)
        auftrag.save(update_fields=['status', 'freigabe_status', 'freigabe_datum',
                                    'token_gueltig_bis'])
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


# ---------------------------------------------------------------------------
# Eigentümer-Freigabe und Handwerkerportal (Modul 3)
# ---------------------------------------------------------------------------

def eigentuemer_um_freigabe_bitten(auftrag):
    """Mail an die Eigentümerschaft: eine Reparatur wartet auf ihre Freigabe.

    Aus `fw_auftrag_kosten` hierher gezogen (Text unverändert), damit die
    Offerte aus dem Handwerkerportal denselben Weg nimmt. Gibt die Adresse
    zurück, an die versendet wurde, sonst ''.
    """
    from core.utils.email_service import send_ticket_email
    ticket = auftrag.ticket
    eigentuemer = getattr(ticket.liegenschaft, 'eigentuemer', None) if ticket.liegenschaft_id else None
    if not (eigentuemer and eigentuemer.email):
        return ''
    lg = ticket.liegenschaft
    kosten_txt = f"CHF {auftrag.kosten_geschaetzt}" if auftrag.kosten_geschaetzt else "noch offen"
    text = (f"Guten Tag {eigentuemer.kontaktperson or eigentuemer.firma_oder_name}\n\n"
            f"Für Ihre Liegenschaft {lg.strasse}, {lg.plz} {lg.ort} liegt eine Reparatur "
            f"zur Freigabe bereit:\n\n"
            f"Schaden: {ticket.titel}\n"
            f"Geschätzte Kosten: {kosten_txt}\n\n"
            f"Bitte melden Sie sich im Eigentümer-Portal an, um die Reparatur "
            f"freizugeben oder abzulehnen.\n\nFreundliche Grüsse\nIhre Verwaltung")
    if send_ticket_email(eigentuemer.email, f"Reparaturfreigabe angefragt — {lg.strasse}", text):
        return eigentuemer.email
    return ''


def _vom_handwerker(auftrag, text, datei=None):
    """Verlaufseintrag «vom Handwerker» — dieselbe Form wie eine Mail-Antwort
    (`antwort_zuordnen`): intern, ungelesen, der Handwerker als Absender."""
    from .models import TicketNachricht
    hw, ticket = auftrag.handwerker, auftrag.ticket
    n = TicketNachricht(ticket=ticket, absender_name=hw.firma, typ='handwerker_mail',
                        empfaenger_handwerker=hw, nachricht=text, is_intern=True,
                        is_von_verwaltung=False, gelesen=False)
    if datei is not None:
        n.datei = datei
    n.save()
    ticket.gelesen = False
    ticket.save(update_fields=['gelesen'])
    return n


def nachricht_von_handwerker(auftrag, text):
    """Nachricht aus dem Handwerkerportal. Wartete das Ticket auf den
    Handwerker, ist wieder die Verwaltung am Zug — dieselbe Regel wie bei
    einer Mail-Antwort (`antwort_zuordnen`)."""
    text = (text or '').strip()
    if not text:
        raise ValidationError('Bitte eine Nachricht eingeben.', code='leer')
    n = _vom_handwerker(auftrag, text)
    ticket = auftrag.ticket
    if ticket.status == 'warte_auf_handwerker':
        try:
            wechsle_status(ticket, 'in_bearbeitung')
        except ValidationError:
            logger.exception("Ticket #%s: Rückwechsel nach Handwerker-Nachricht nicht möglich", ticket.pk)
    return n


#: Was der Handwerker melden kann, und wohin das Ticket dann im Regelweg geht.
#: «begonnen»: der Handwerker ist am Zug. «erledigt»: Arbeit gemacht, die
#: Rechnung fehlt noch — abgeschlossen wird intern, nach der Rechnung.
HANDWERKER_MELDUNGEN = {
    'begonnen': ('warte_auf_handwerker', 'Arbeit begonnen'),
    'erledigt': ('wartet_auf_rechnung', 'Arbeit erledigt'),
}


def handwerker_meldet(auftrag, was):
    """«begonnen» bzw. «erledigt» aus dem Handwerkerportal.

    Nur über erlaubte Übergänge (`UEBERGAENGE`). Ist der Übergang vom
    aktuellen Status aus nicht vorgesehen, bleibt der Status, und ein interner
    Hinweis sagt der Verwaltung, was der Handwerker gemeldet hat. Gibt True
    zurück, wenn der Status gewechselt hat.
    """
    if was not in HANDWERKER_MELDUNGEN:
        raise ValidationError('Unbekannte Meldung.', code='unbekannt')
    ziel, text = HANDWERKER_MELDUNGEN[was]
    ticket = auftrag.ticket
    _vom_handwerker(auftrag, f"{auftrag.handwerker.firma} meldet: {text}.")
    if ticket.status == ziel:
        return False
    if ziel in UEBERGAENGE.get(ticket.status, ()):
        try:
            wechsle_status(ticket, ziel)
            return True
        except ValidationError:
            logger.exception("Ticket #%s: Handwerker-Meldung «%s» nicht umsetzbar", ticket.pk, was)
    _protokoll(ticket, f"Handwerker meldet «{text}», Status bleibt «{ticket.status}» "
                       f"(Übergang nach «{ziel}» nicht vorgesehen) — bitte prüfen.")
    return False


def termin_bestaetigen(auftrag):
    """Der Handwerker bestätigt den vereinbarten Termin. Keine Mails: Der
    Termin ist beiden Seiten schon bekannt; der Verlauf hält die Bestätigung fest."""
    if auftrag.termin_status != 'vereinbart' or not auftrag.termin_am:
        raise ValidationError('Es gibt keinen vereinbarten Termin.', code='kein_termin')
    return _vom_handwerker(auftrag, f"{auftrag.handwerker.firma} bestätigt den Termin "
                                    f"{_termin_text(auftrag.termin_am)}.")


def offerte_erfassen(auftrag, betrag, datei):
    """Offerte aus dem Handwerkerportal: Betrag und Dokument.

    Setzt `kosten_geschaetzt`. Ab `REPARATUR_FREIGABE_SCHWELLE` wird die
    Freigabe der Eigentümerschaft angefordert — dieselbe Regel wie in
    `fw_auftrag_kosten`. Lag schon eine Freigabe vor und übersteigt die neue
    Offerte die freigegebene Schätzung um mehr als 20 %, braucht es eine
    Nachfreigabe (`ABWEICHUNG_NACHFREIGABE`, wie bei den effektiven Kosten).
    Gibt True zurück, wenn eine Freigabe angefordert wurde.
    """
    if betrag is None or betrag <= 0:
        raise ValidationError('Bitte einen Betrag angeben.', code='betrag')
    alt = auftrag.kosten_geschaetzt or Decimal('0')
    anfordern = (
        (auftrag.freigabe_status in ('nicht_noetig', 'abgelehnt')
         and betrag >= REPARATUR_FREIGABE_SCHWELLE)
        or (auftrag.freigabe_status == 'freigegeben' and alt > 0
            and betrag > alt * ABWEICHUNG_NACHFREIGABE))
    with transaction.atomic():
        auftrag.kosten_geschaetzt = betrag
        felder = ['kosten_geschaetzt']
        if anfordern:
            auftrag.freigabe_status = 'ausstehend'
            auftrag.freigabe_datum = None
            felder += ['freigabe_status', 'freigabe_datum']
        auftrag.save(update_fields=felder)
        _vom_handwerker(auftrag, f"Offerte {auftrag.handwerker.firma}: CHF {betrag}"
                                 + (" — Eigentümer-Freigabe angefordert." if anfordern else "."),
                        datei=datei)
    if anfordern:
        try:
            eigentuemer_um_freigabe_bitten(auftrag)
        except Exception:
            logger.exception("Freigabe-Mail zu Auftrag #%s fehlgeschlagen", auftrag.pk)
    return anfordern


def rechnung_einreichen(auftrag, betrag, datei):
    """Rechnung aus dem Handwerkerportal: ein ENTWURF in den Kreditoren.

    `KreditorenRechnung(status='neu')` mit dem Beleg und dem Handwerker,
    verknüpft wie in `fw_auftrag_rechnung` über `rechnung_verknuepfen` — aber
    ohne Abschluss: Geprüft, freigegeben und abgeschlossen wird intern.
    Hängt am Auftrag schon eine Rechnung, wird abgelehnt.
    """
    from django.utils import timezone
    from finance.models import KreditorenRechnung
    if auftrag.kreditoren_rechnung_id:
        raise ValidationError('Zu diesem Auftrag ist schon eine Rechnung erfasst.', code='doppelt')
    if betrag is None or betrag <= 0:
        raise ValidationError('Bitte einen Betrag angeben.', code='betrag')
    ticket, hw = auftrag.ticket, auftrag.handwerker
    with transaction.atomic():
        kr = KreditorenRechnung(
            liegenschaft=ticket.liegenschaft, lieferant=hw.firma, handwerker=hw,
            betrag=betrag, datum=timezone.localdate(), status='neu')
        kr.beleg_scan = datei
        kr.save()
        rechnung_verknuepfen(auftrag, kr, abschliessen=False)
        _vom_handwerker(auftrag, f"Rechnung {hw.firma}: CHF {betrag} hochgeladen "
                                 f"(Kreditor #{kr.pk}, Entwurf zur Kontrolle).")
    return kr
