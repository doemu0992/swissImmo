import logging
import threading
import os
from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import dateformat, translation
from django.utils.translation import gettext

from core.services.dokumentsprache import in_sprache, sprache_von

logger = logging.getLogger(__name__)


# Helper to send mail via Hoststar
def send_via_hoststar(to_email, subject, html_content, attachment_name=None, attachment_content=None, cc_list=None):
    try:
        from_email = settings.DEFAULT_FROM_EMAIL
        reply_addr = os.environ.get('EMAIL_REPLY_USER', 'reply@immoswiss.app')

        email = EmailMessage(
            subject=subject,
            body=html_content,
            from_email=from_email,
            to=[to_email],
            cc=cc_list or [],
            reply_to=[reply_addr]
        )
        email.content_subtype = "html"

        if attachment_name and attachment_content:
            mime_type = 'application/pdf' if attachment_name.endswith('.pdf') else 'image/jpeg'
            email.attach(attachment_name, attachment_content, mime_type)

        email.send(fail_silently=False)
        print(f"✅ Mail sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Mail Error: {e}")
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

    _text1 = gettext('Wir haben Ihre Meldung erhalten')
    _text2 = gettext('Ticket-Nr.')
    _text3 = gettext('Thema')
    _text4 = gettext('Wir melden uns, sobald ein Handwerker beauftragt wurde.')
    _text5 = gettext('Freundliche Grüsse')
    html_msg = f"""
    <html><body>
    <h2>{_text1}</h2>
    <p>{_text2}: #{ticket.id}<br>{_text3}: {ticket.titel}</p>
    <p>{_text4}</p>
    <p>{_text5}<br>ImmoSwiss Verwaltung</p>
    </body></html>
    """
    threading.Thread(target=send_via_hoststar, args=(ticket.email_melder, subject, html_msg)).start()


def send_handyman_notification(auftrag):
    """
    Sends detailed order to Handyman AND info to Tenant.
    """
    ticket = auftrag.ticket
    hw = auftrag.handwerker

    # 1. MAIL TO HANDYMAN
    if hw.email:
        subject = f"Auftrag: {ticket.liegenschaft.strasse} (Ticket #{ticket.id})"

        # Safe attribute access
        eigentuemer_info = "Keine Rechnungsadresse"
        if ticket.liegenschaft.eigentuemer:
            m = ticket.liegenschaft.eigentuemer
            eigentuemer_info = f"{m.firma_oder_name}, {m.strasse}, {m.plz} {m.ort}"
        elif ticket.liegenschaft.organisation:
            v = ticket.liegenschaft.organisation
            eigentuemer_info = f"{v.firma}, {v.strasse}, {v.plz} {v.ort}"

        auftrags_text = auftrag.bemerkung if auftrag.bemerkung else "Bitte Auftrag ausführen."

        html_hw = f"""
        <html><body style="font-family: Arial, sans-serif;">
            <p>Guten Tag,</p>
            <p>{auftrags_text.replace(chr(10), '<br>')}</p>
            <hr>
            <table width="100%" cellpadding="5" style="border:1px solid #ddd;">
                <tr style="background:#eee;"><td><strong>Objekt:</strong></td><td>{ticket.liegenschaft.strasse}, {ticket.liegenschaft.ort}</td></tr>
                <tr><td><strong>Schaden:</strong></td><td>{ticket.titel}<br>{ticket.beschreibung}</td></tr>
                <tr style="background:#eee;"><td><strong>Kontakt vor Ort:</strong></td><td>{ticket.gemeldet_von}<br>{ticket.tel_melder}</td></tr>
                <tr><td><strong>Rechnung an:</strong></td><td>{eigentuemer_info}</td></tr>
            </table>
            <p style="font-size:0.8em; color:gray;">Bitte Ticket #{ticket.id} als Referenz nutzen.</p>
        </body></html>
        """

        # Handle Photo
        att_name = None
        att_content = None
        if ticket.foto:
            try:
                with ticket.foto.open('rb') as f:
                    att_content = f.read()
                    att_name = os.path.basename(ticket.foto.name)
            except:
                logger.debug("Fehler bewusst übergangen", exc_info=True)

        threading.Thread(target=send_via_hoststar, args=(hw.email, subject, html_hw, att_name, att_content)).start()

    # 2. MAIL TO TENANT
    if ticket.email_melder:
        sub_m = f"Handwerker beauftragt [Ticket #{ticket.id}]"
        html_m = f"""
        <html><body>
        <p>Guten Tag,</p>
        <p>Ein Handwerker wurde beauftragt:</p>
        <div style="background:#f9f9f9; padding:10px; border:1px solid #ddd;">
            <strong>{hw.firma}</strong><br>Tel: {hw.telefon}
        </div>
        <p>Die Firma meldet sich für einen Termin.</p>
        </body></html>
        """
        threading.Thread(target=send_via_hoststar, args=(ticket.email_melder, sub_m, html_m)).start()

def send_neue_meldung_intern(ticket, to_emails):
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
    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#0f172a;line-height:1.6;">
      <h2 style="color:#4338ca;">Neue Schadenmeldung aus dem Mieterportal</h2>
      <table cellpadding="6" style="border-collapse:collapse;">
        <tr><td style="color:#64748b;">Ticket</td><td><strong>#{ticket.id}</strong></td></tr>
        <tr><td style="color:#64748b;">Titel</td><td><strong>{ticket.titel}</strong></td></tr>
        <tr><td style="color:#64748b;">Objekt</td><td>{objekt} · {einheit}</td></tr>
        <tr><td style="color:#64748b;">Raum</td><td>{ticket.raum or '—'}</td></tr>
        <tr><td style="color:#64748b;">Melder</td><td>{melder}<br>{ticket.email_melder or ''} {ticket.tel_melder or ''}</td></tr>
      </table>
      <p style="margin-top:12px;white-space:pre-line;">{ticket.beschreibung or ''}</p>
      <p style="color:#94a3b8;font-size:12px;margin-top:20px;">Diese Meldung erscheint in der Software unter Schadensfälle.</p>
    </body></html>
    """
    betreff = f"Neue Schadenmeldung #{ticket.id}: {ticket.titel}"
    ok = False
    for adr in empf:
        ok = send_via_hoststar(adr, betreff, html) or ok
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


def send_ticket_email(to_email, betreff, inhalt_text, foto_field=None):
    """Sendet eine Ticket-Mail (aus Vorlage) synchron. inhalt_text ist Klartext
    mit Zeilenumbrüchen; wird zu HTML gewandelt. Gibt True/False zurück."""
    if not to_email:
        return False
    html = "<html><body style='font-family:Arial,sans-serif;color:#333;line-height:1.5;'>"
    html += inhalt_text.replace('\n', '<br>')
    html += "</body></html>"
    att_name = att_content = None
    if foto_field:
        try:
            with foto_field.open('rb') as f:
                att_content = f.read()
                att_name = os.path.basename(foto_field.name)
        except Exception:
            att_name = att_content = None
    return send_via_hoststar(to_email, betreff, html, att_name, att_content)


def send_mieter_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma='',
                              sprache='de'):
    """Sendet dem Mieter seine Portal-Zugangsdaten (Benutzername, Passwort,
    Erklärung, Login-Link). Gibt True/False zurück.

    `sprache`: Korrespondenzsprache des Mieters (D11), nicht die der
    Sachbearbeitung, die den Zugang anlegt."""
    if not to_email:
        return False
    with in_sprache(sprache):
        return _mieter_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma)


def _mieter_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma):
    betreff = gettext('Ihr Zugang zum Mieterportal')
    firma_zeile = f"<p style='margin:24px 0 0;color:#94a3b8;font-size:13px;'>{absender_firma}</p>" if absender_firma else ""
    _text1 = gettext('Ihr Mieterportal')
    _text2 = gettext('Guten Tag %(name)s') % {'name': anrede_name}
    _text3 = gettext('Für Sie wurde ein persönlicher Zugang zum Mieterportal eingerichtet. Dort sehen Sie jederzeit Ihren Mietvertrag, offene Rechnungen (inkl. QR-Einzahlschein), Ihren Kontoauszug und Ihre Dokumente — und Sie können bequem eine Reparatur oder einen Schaden melden.')
    _text4 = gettext('Benutzername')
    _text5 = gettext('Passwort')
    _text6 = gettext('Jetzt einloggen')
    _text7 = gettext('Oder öffnen Sie diese Adresse im Browser:')
    _text8 = gettext('Bitte ändern Sie Ihr Passwort nach dem ersten Login und bewahren Sie diese Angaben sicher auf. Diese E-Mail wurde automatisch erstellt.')
    html = f"""<html><body style="font-family:Arial,Helvetica,sans-serif;color:#0f172a;line-height:1.6;background:#f1f5f9;padding:24px;">
      <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;">
        <div style="background:#4338ca;color:#fff;padding:20px 28px;font-size:18px;font-weight:600;">🔑 {_text1}</div>
        <div style="padding:28px;">
          <p>{_text2}</p>
          <p>{_text3}</p>
          <table style="margin:20px 0;border-collapse:collapse;">
            <tr><td style="padding:6px 16px 6px 0;color:#64748b;">{_text4}</td>
                <td style="padding:6px 0;font-weight:700;font-family:monospace;">{username}</td></tr>
            <tr><td style="padding:6px 16px 6px 0;color:#64748b;">{_text5}</td>
                <td style="padding:6px 0;font-weight:700;font-family:monospace;">{passwort}</td></tr>
          </table>
          <p style="margin:24px 0;">
            <a href="{login_url}" style="background:#4338ca;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;display:inline-block;">{_text6}</a>
          </p>
          <p style="color:#64748b;font-size:13px;">{_text7}<br>
            <a href="{login_url}" style="color:#4338ca;">{login_url}</a></p>
          <p style="color:#94a3b8;font-size:12px;margin-top:20px;">{_text8}</p>
          {firma_zeile}
        </div>
      </div>
    </body></html>"""
    return send_via_hoststar(to_email, betreff, html)


def send_report_mail(to_email, betreff, html_inhalt, anhaenge=None):
    """Sendet eine HTML-Mail mit mehreren PDF-Anhängen. anhaenge = Liste von
    (dateiname, bytes). Gibt True/False zurück."""
    if not to_email:
        return False
    try:
        from_email = settings.DEFAULT_FROM_EMAIL
        reply_addr = os.environ.get('EMAIL_REPLY_USER', 'reply@immoswiss.app')
        email = EmailMessage(subject=betreff, body=html_inhalt, from_email=from_email,
                             to=[to_email], reply_to=[reply_addr])
        email.content_subtype = "html"
        for name, inhalt in (anhaenge or []):
            if inhalt:
                mime = 'application/pdf' if name.lower().endswith('.pdf') else 'application/octet-stream'
                email.attach(name, inhalt, mime)
        email.send(fail_silently=False)
        print(f"✅ Report-Mail an {to_email} ({len(anhaenge or [])} Anhang/Anhänge)")
        return True
    except Exception as e:
        print(f"❌ Report-Mail Fehler: {e}")
        return False


def send_eigentuemer_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma='',
                                   sprache='de'):
    """Sendet dem Eigentümer seine Portal-Zugangsdaten. True/False.

    `sprache`: Korrespondenzsprache des Eigentümers (D11)."""
    if not to_email:
        return False
    with in_sprache(sprache):
        return _eigentuemer_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma)


def _eigentuemer_portal_zugang(to_email, anrede_name, username, passwort, login_url, absender_firma):
    betreff = gettext('Ihr Zugang zum Eigentümer-Portal')
    _kopf = gettext('Ihr Eigentümer-Portal')
    _gruss = gettext('Guten Tag %(name)s') % {'name': anrede_name}
    _einleitung = gettext('Für Sie wurde ein persönlicher Zugang zum Eigentümer-Portal eingerichtet. Dort sehen Sie jederzeit den Stand Ihrer Liegenschaften: Rendite-Cockpit, offene Reparatur-Freigaben, Portfolio-Report und Steuerauszug.')
    _benutzer = gettext('Benutzername')
    _passwort = gettext('Passwort')
    _login = gettext('Jetzt einloggen')
    _adresse = gettext('Oder öffnen Sie diese Adresse im Browser:')
    _hinweis = gettext('Bitte ändern Sie Ihr Passwort nach dem ersten Login und bewahren Sie diese Angaben sicher auf. Diese E-Mail wurde automatisch erstellt.')
    firma_zeile = f"<p style='margin:24px 0 0;color:#94a3b8;font-size:13px;'>{absender_firma}</p>" if absender_firma else ""
    html = f"""<html><body style="font-family:Arial,Helvetica,sans-serif;color:#0f172a;line-height:1.6;background:#f1f5f9;padding:24px;">
      <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;">
        <div style="background:#1e3a8a;color:#fff;padding:20px 28px;font-size:18px;font-weight:600;">🏠 {_kopf}</div>
        <div style="padding:28px;">
          <p>{_gruss}</p>
          <p>{_einleitung}</p>
          <table style="margin:20px 0;border-collapse:collapse;">
            <tr><td style="padding:6px 16px 6px 0;color:#64748b;">{_benutzer}</td>
                <td style="padding:6px 0;font-weight:700;font-family:monospace;">{username}</td></tr>
            <tr><td style="padding:6px 16px 6px 0;color:#64748b;">{_passwort}</td>
                <td style="padding:6px 0;font-weight:700;font-family:monospace;">{passwort}</td></tr>
          </table>
          <p style="margin:24px 0;">
            <a href="{login_url}" style="background:#1e3a8a;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;display:inline-block;">{_login}</a>
          </p>
          <p style="color:#64748b;font-size:13px;">{_adresse}<br>
            <a href="{login_url}" style="color:#1e3a8a;">{login_url}</a></p>
          <p style="color:#94a3b8;font-size:12px;margin-top:20px;">{_hinweis}</p>
          {firma_zeile}
        </div>
      </div>
    </body></html>"""
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
    name = f"{mieter.vorname} {mieter.nachname}"
    with in_sprache(sprache_von(mieter)):
        monat_str = dateformat.format(monat_datum, 'F Y')
        subject = gettext('Zahlungserinnerung: Miete %(monat)s - %(objekt)s') % {'monat': monat_str, 'objekt': objekt}
        _text1 = gettext('Zahlungserinnerung')
        _text2 = gettext('Guten Tag %(name)s,') % {'name': name}
        _text3 = gettext('Bei der Kontrolle unserer Konten haben wir festgestellt, dass die Miete für den Monat <strong>%(monat)s</strong> für das Objekt <strong>%(objekt)s</strong> noch nicht vollständig beglichen wurde.') % {'monat': monat_str, 'objekt': objekt}
        _text4 = gettext('Ausstehender Betrag: CHF %(betrag)s') % {'betrag': betrag}
        _text5 = gettext('Sollten Sie die Zahlung bereits getätigt haben, betrachten Sie dieses Schreiben bitte als gegenstandslos. Andernfalls bitten wir Sie um eine zeitnahe Überweisung.')
        _text6 = gettext('Freundliche Grüsse,')
        _text7 = gettext('Ihre Liegenschaftsverwaltung')
        html_msg = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #2c3e50;">{_text1}</h2>
        <p>{_text2}</p>
        <p>{_text3}</p>
        <div style="background: #fdf2f2; border-left: 4px solid #ef4444; padding: 15px; margin: 20px 0;">
            <p style="margin: 0; font-weight: bold; color: #991b1b;">{_text4}</p>
        </div>
        <p>{_text5}</p>
        <p>{_text6}<br>{_text7}</p>
    </body></html>
    """
    threading.Thread(target=send_via_hoststar, args=(mieter.email, subject, html_msg)).start()
    # Das Journal liest die Verwaltung: deutsch, unabhängig von der Mieter-Sprache.
    with translation.override('de'):
        monat_de = dateformat.format(monat_datum, 'F Y')
    journal_email(subject,
                  f"Zahlungserinnerung Miete {monat_de} · offen CHF {betrag}",
                  mieter=mieter, vertrag=vertrag, empfaenger=mieter.email)
    return True