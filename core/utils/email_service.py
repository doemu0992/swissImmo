import logging
import threading
import os
from html import escape as html_escape
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import dateformat, translation
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext

from core.services.dokumentsprache import in_sprache, sprache_von
from core.utils.absender import anzeigename, kopfzeilen
from core.services.druckfarben import EMBER

logger = logging.getLogger(__name__)


def mail_html(vorlage, **kontext):
    """Rendert eine Mail aus `templates/emails/<vorlage>.html` (Roadmap Nr. 24).

    Layout und Stil stehen in den Vorlagen, nicht in Python-Strings; die Texte kommen übersetzt aus dem
    Aufrufer, die Werte werden von Django escaped. `EMBER` (Markenfarbe) ist immer da."""
    return render_to_string(f'emails/{vorlage}.html', {'EMBER': EMBER, **kontext})


# Helper to send mail via Hoststar
def _einzeilig(text):
    """Betreff ohne Zeilenumbruch: Django verwirft eine Mail mit Umbruch im Betreff (BadHeaderError,
    Schutz vor Header-Einschleusung) — der Titel einer öffentlichen Meldung darf das nicht auslösen."""
    return ' '.join(str(text or '').split())


def send_via_hoststar(to_email, subject, html_content, attachment_name=None, attachment_content=None, cc_list=None, weitere_anhaenge=None, reply_to=None, organisation=None, absender_name=None, headers=None):
    try:
        # Absender und Antwortadresse der VERWALTUNG, die schreibt (FUNK-12, core/utils/absender.py).
        # `organisation` (Objekt oder ID) ist nötig, wo kein Mandantenkontext besteht (eigener Thread).
        # `absender_name`: Direktkanal Mieter/Handwerker — «<Name> via immoswiss» statt der Firma der
        # Verwaltung; die Adresse der Gegenseite wird nie preisgegeben (Antworten laufen über das Postfach).
        kopf = kopfzeilen(organisation, reply_to)
        if absender_name:
            from core.utils.absender import absender_person
            kopf['from_email'] = absender_person(absender_name)
        email = EmailMessage(
            subject=_einzeilig(subject),
            body=html_content,
            to=[to_email],
            cc=cc_list or [],
            headers=headers or None,
            **kopf,
        )
        email.content_subtype = "html"

        if attachment_name and attachment_content:
            mime_type = 'application/pdf' if attachment_name.endswith('.pdf') else 'image/jpeg'
            email.attach(attachment_name, attachment_content, mime_type)
        for name, inhalt, mime in (weitere_anhaenge or []):
            email.attach(name, inhalt, mime)

        email.send(fail_silently=False)
        logger.info("Mail an %s gesendet: %s", to_email, email.subject)
        return True
    except Exception as e:
        # Eine Warnung mit Empfänger und Grund: Das Protokoll ist die einzige Spur, wenn der
        # Aufrufer (ein Thread, ein Hintergrundlauf) das False nicht beachtet.
        logger.warning("Mail an %s nicht gesendet (%s): %s", to_email, _einzeilig(subject), e, exc_info=True)
        return False

# ---------------------------------------------------------
# PUBLIC FUNCTIONS (Imported by views/admin)
# ---------------------------------------------------------

def send_ticket_receipt(ticket):
    """
    Sends confirmation to tenant.
    """
    if not ticket.email_melder:
        return

    # Sprache: die der laufenden Anfrage — die Bestätigung geht unmittelbar
    # nach dem Absenden des öffentlichen Formulars raus, in der Sprache, in der
    # die Person es ausgefüllt hat (D11: Sprache des Empfängers).
    subject = gettext('Eingangsbestätigung: %(titel)s [Ticket #%(id)s]') % {'titel': ticket.titel, 'id': ticket.id}

    from core.services.ticket_workflow import melder_gruss
    _gruss = melder_gruss(ticket)
    _text1 = gettext('Wir haben Ihre Meldung erhalten')
    _text2 = gettext('Ticket-Nr.')
    _text3 = gettext('Thema')
    _text4 = gettext('Wir melden uns, sobald ein Handwerker beauftragt wurde.')
    _text5 = gettext('Freundliche Grüsse')
    # Es schreibt die Verwaltung des Hauses, nicht die Plattform (FUNK-12): dieselbe Firma wie im Absendernamen.
    unterschrift = anzeigename(ticket.organisation) or 'immoswiss'
    html_msg = mail_html('ticket_eingang', titel_text=_text1, gruss=_gruss, nr_text=_text2, thema_text=_text3,
                         ticket=ticket, hinweis=_text4, schluss=_text5, unterschrift=unterschrift)
    from tickets.workflow import reply_to
    # Die Adresse wird HIER im Anfrage-Thread bestimmt: der Mail-Thread hat keinen Mandantenkontext.
    threading.Thread(target=send_via_hoststar, args=(ticket.email_melder, subject, html_msg),
                     kwargs={'reply_to': reply_to(ticket), 'organisation': ticket.organisation_id}).start()


def send_neue_meldung_intern(ticket, to_emails, herkunft='aus dem Mieterportal'):
    """Benachrichtigt die Verwaltung über eine neu eingegangene Schadenmeldung
    (z.B. aus dem Mieterportal). to_emails: Liste von Empfängeradressen."""
    empf = [e for e in (to_emails or []) if e]
    if not empf:
        return False
    lg = ticket.liegenschaft
    objekt = f"{lg.strasse}, {lg.ort}" if lg else '—'
    einheit = ticket.betroffene_einheit.bezeichnung if ticket.betroffene_einheit_id else '—'
    melder = (ticket.gemeldet_von.display_name if ticket.gemeldet_von_id
              else f"{ticket.melder_vorname or ''} {ticket.melder_nachname or ''}".strip() or '—')
    html = mail_html('neue_meldung_intern', ticket=ticket, herkunft=herkunft, objekt=objekt, einheit=einheit, melder=melder)
    betreff = f"Neue Schadenmeldung #{ticket.id}: {ticket.titel}"
    ok = False
    for adr in empf:
        ok = send_via_hoststar(adr, betreff, html, organisation=ticket.organisation_id) or ok
    return ok


def journal_email(betreff, inhalt, *, mieter=None, vertrag=None, liegenschaft=None,
                  user=None, empfaenger=''):
    """Dokumentiert eine versendete E-Mail im Kommunikations-Journal.

    Ohne diesen Eintrag ist der Verlauf lückenhaft: Rundschreiben, Mahnungen und
    Bewerber-Mails gingen raus, ohne dass die Akte des Kontakts sie zeigt.
    Darf einen Versand nie zum Scheitern bringen → defensiv (best effort)."""
    try:
        from crm.models import Kommunikation
        text = inhalt or ''
        if empfaenger:
            text = f"An: {empfaenger}\n\n{text}"
        Kommunikation.objects.create(
            mieter=mieter, vertrag=vertrag, liegenschaft=liegenschaft,
            typ='email', richtung='ausgehend',
            betreff=(betreff or '')[:200], inhalt=text, erstellt_von=user)
        return True
    except Exception:
        return False


def send_ticket_email(to_email, betreff, inhalt_text, foto_field=None, reply_to=None, organisation=None,
                      weitere_anhaenge=None):
    """Sendet eine Ticket-Mail (aus Vorlage) synchron. inhalt_text ist Klartext
    mit Zeilenumbrüchen; wird zu HTML gewandelt. Gibt True/False zurück.

    Der Text wird MASKIERT: Titel und Beschreibung stammen von Melderinnen und Meldern (öffentliches
    Formular, ohne Anmeldung) und stehen über die Platzhalter in Mails an Mieter, Handwerker und
    Eigentümer. Als HTML eingesetzt wären sie eine Einschleusung in eine Mail «der Verwaltung»."""
    if not to_email:
        return False
    html = mail_html('klartext', text=inhalt_text or '')      # maskiert, Zeilenumbrüche als <br>
    att_name = att_content = None
    if foto_field:
        try:
            with foto_field.open('rb') as f:
                att_content = f.read()
                att_name = os.path.basename(foto_field.name)
        except Exception:
            att_name = att_content = None
    return send_via_hoststar(to_email, betreff, html, att_name, att_content, reply_to=reply_to,
                             organisation=organisation, weitere_anhaenge=weitere_anhaenge)


def _klartext_als_html(text):
    """Klartext → HTML-Fragment: maskiert, Zeilenumbrüche als <br>."""
    return html_escape(text or '', quote=False).replace('\n', '<br>')


def send_mieter_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma='',
                              sprache='de', gruss=None):
    """Sendet dem Mieter seine Portal-Zugangsdaten (Benutzername, Passwort,
    Erklärung, Login-Link). Gibt True/False zurück.

    `sprache`: Korrespondenzsprache des Mieters (D11), nicht die der
    Sachbearbeitung, die den Zugang anlegt."""
    if not to_email:
        return False
    with in_sprache(sprache):
        return _mieter_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma, gruss)


def _mieter_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma, gruss=None):
    betreff = gettext('Ihr Zugang zum Mieterportal')
    _text1 = gettext('Ihr Mieterportal')
    _text2 = gruss or gettext('Guten Tag %(name)s') % {'name': anrede_name}
    _text3 = gettext('Für Sie wurde ein persönlicher Zugang zum Mieterportal eingerichtet. Dort sehen Sie jederzeit Ihren Mietvertrag, offene Rechnungen (inkl. QR-Einzahlschein), Ihren Kontoauszug und Ihre Dokumente — und Sie können bequem eine Reparatur oder einen Schaden melden.')
    _text4 = gettext('Benutzername')
    _text5 = gettext('Passwort')
    _text6 = gettext('Jetzt einloggen')
    _text7 = gettext('Oder öffnen Sie diese Adresse im Browser:')
    _text8 = gettext('Bitte ändern Sie Ihr Passwort nach dem ersten Login und bewahren Sie diese Angaben sicher auf. Diese E-Mail wurde automatisch erstellt.')
    html = mail_html('portal_zugang', zeichen='🔑', kopf=_text1, gruss=_text2, einleitung=_text3,
                     benutzer_text=_text4, passwort_text=_text5, login_text=_text6, adresse_text=_text7,
                     hinweis=_text8, username=username, passwort=passwort, login_url=login_url,
                     absender_firma=absender_firma)
    return send_via_hoststar(to_email, betreff, html)


def send_report_mail(to_email, betreff, html_inhalt, anhaenge=None, organisation=None):
    """Sendet eine HTML-Mail mit mehreren PDF-Anhängen. anhaenge = Liste von
    (dateiname, bytes). Gibt True/False zurück."""
    if not to_email:
        return False
    try:
        email = EmailMessage(subject=_einzeilig(betreff), body=html_inhalt, to=[to_email],
                             **kopfzeilen(organisation))
        email.content_subtype = "html"
        for name, inhalt in (anhaenge or []):
            if inhalt:
                mime = 'application/pdf' if name.lower().endswith('.pdf') else 'application/octet-stream'
                email.attach(name, inhalt, mime)
        email.send(fail_silently=False)
        logger.info("Report-Mail an %s gesendet (%s Anhänge)", to_email, len(anhaenge or []))
        return True
    except Exception as e:
        logger.warning("Report-Mail an %s nicht gesendet: %s", to_email, e, exc_info=True)
        return False


def send_eigentuemer_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma='',
                                   sprache='de', gruss=None):
    """Sendet dem Eigentümer seine Portal-Zugangsdaten. True/False.

    `sprache`: Korrespondenzsprache des Eigentümers (D11)."""
    if not to_email:
        return False
    with in_sprache(sprache):
        return _eigentuemer_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma, gruss)


def _eigentuemer_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma, gruss=None):
    betreff = gettext('Ihr Zugang zum Eigentümer-Portal')
    _kopf = gettext('Ihr Eigentümer-Portal')
    _gruss = gruss or gettext('Guten Tag %(name)s') % {'name': anrede_name}
    _einleitung = gettext('Für Sie wurde ein persönlicher Zugang zum Eigentümer-Portal eingerichtet. Dort sehen Sie jederzeit den Stand Ihrer Liegenschaften: Rendite-Cockpit, offene Reparatur-Freigaben, Portfolio-Report und Steuerauszug.')
    _benutzer = gettext('Benutzername')
    _passwort = gettext('Passwort')
    _login = gettext('Jetzt einloggen')
    _adresse = gettext('Oder öffnen Sie diese Adresse im Browser:')
    _hinweis = gettext('Bitte ändern Sie Ihr Passwort nach dem ersten Login und bewahren Sie diese Angaben sicher auf. Diese E-Mail wurde automatisch erstellt.')
    html = mail_html('portal_zugang', zeichen='🏠', kopf=_kopf, gruss=_gruss, einleitung=_einleitung,
                     benutzer_text=_benutzer, passwort_text=_passwort, login_text=_login, adresse_text=_adresse,
                     hinweis=_hinweis, username=username, passwort=passwort, login_url=login_url,
                     absender_firma=absender_firma)
    return send_via_hoststar(to_email, betreff, html)


def send_payment_reminder(vertrag, monat_datum, offener_betrag):
    """
    Versendet eine E-Mail-Mahnung an den Mieter.
    """
    mieter = vertrag.mieter
    if not mieter or not mieter.email:
        return False

    # Sprache des Mieters (D11). Monatsnamen über Djangos `dateformat`, nicht
    # `strftime` — das folgt der Server-Locale und lieferte «May» auch in der
    # deutschen Mail. Eine freundliche Zahlungserinnerung, keine Mahnung nach
    # Art. 257d OR: kein Rechtstext, deshalb übersetzt.
    betrag = f"{offener_betrag:,.2f}"
    objekt = vertrag.einheit.bezeichnung
    with in_sprache(sprache_von(mieter)):
        monat_str = dateformat.format(monat_datum, 'F Y')
        subject = gettext('Zahlungserinnerung: Miete %(monat)s - %(objekt)s') % {'monat': monat_str, 'objekt': objekt}
        _text1 = gettext('Zahlungserinnerung')
        from core.services.anrede import mieter_gruss
        _text2 = mieter_gruss(mieter) + ','
        # Die Werte werden escaped, die <strong>-Auszeichnung des Textes bleibt (Übersetzungs-Schlüssel unverändert).
        _text3 = mark_safe(gettext('Bei der Kontrolle unserer Konten haben wir festgestellt, dass die Miete für den Monat <strong>%(monat)s</strong> für das Objekt <strong>%(objekt)s</strong> noch nicht vollständig beglichen wurde.') % {'monat': escape(monat_str), 'objekt': escape(objekt)})
        _text4 = gettext('Ausstehender Betrag: CHF %(betrag)s') % {'betrag': betrag}
        _text5 = gettext('Sollten Sie die Zahlung bereits getätigt haben, betrachten Sie dieses Schreiben bitte als gegenstandslos. Andernfalls bitten wir Sie um eine zeitnahe Überweisung.')
        _text6 = gettext('Freundliche Grüsse,')
        _text7 = gettext('Ihre Liegenschaftsverwaltung')
        html_msg = mail_html('zahlungserinnerung', titel_text=_text1, gruss=_text2, einleitung=_text3,
                             betrag_text=_text4, hinweis=_text5, schluss=_text6, unterschrift=_text7)
    threading.Thread(target=send_via_hoststar, args=(mieter.email, subject, html_msg)).start()
    # Das Journal liest die Verwaltung: deutsch, unabhängig von der Mieter-Sprache.
    with translation.override('de'):
        monat_de = dateformat.format(monat_datum, 'F Y')
    journal_email(subject,
                  f"Zahlungserinnerung Miete {monat_de} · offen CHF {betrag}",
                  mieter=mieter, vertrag=vertrag, empfaenger=mieter.email)
    return True