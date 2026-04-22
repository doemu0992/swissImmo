import threading
import os
from django.core.mail import EmailMessage
from django.conf import settings

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

    subject = f"Eingang Bestätigung: {ticket.titel} [Ticket #{ticket.id}]"

    html_msg = f"""
    <html><body>
    <h2>Wir haben Ihre Meldung erhalten</h2>
    <p>Ticket ID: #{ticket.id}<br>Thema: {ticket.titel}</p>
    <p>Wir melden uns, sobald ein Handwerker beauftragt wurde.</p>
    <p>Freundliche Grüsse<br>ImmoSwiss Verwaltung</p>
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
        mandant_info = "Keine Rechnungsadresse"
        if ticket.liegenschaft.mandant:
            m = ticket.liegenschaft.mandant
            mandant_info = f"{m.firma_oder_name}, {m.strasse}, {m.plz} {m.ort}"
        elif ticket.liegenschaft.verwaltung:
            v = ticket.liegenschaft.verwaltung
            mandant_info = f"{v.firma}, {v.strasse}, {v.plz} {v.ort}"

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
                <tr><td><strong>Rechnung an:</strong></td><td>{mandant_info}</td></tr>
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
                pass

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

def send_payment_reminder(vertrag, monat_datum, offener_betrag):
    """
    Versendet eine E-Mail-Mahnung an den Mieter.
    """
    mieter = vertrag.mieter
    if not mieter or not mieter.email:
        return False

    monat_str = monat_datum.strftime('%B %Y')
    subject = f"Zahlungserinnerung: Miete {monat_str} - {vertrag.einheit.bezeichnung}"

    html_msg = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #2c3e50;">Zahlungserinnerung</h2>
        <p>Guten Tag {mieter.vorname} {mieter.nachname},</p>
        <p>Bei der Kontrolle unserer Konten haben wir festgestellt, dass die Miete für den Monat <strong>{monat_str}</strong> für das Objekt <strong>{vertrag.einheit.bezeichnung}</strong> noch nicht vollständig beglichen wurde.</p>
        <div style="background: #fdf2f2; border-left: 4px solid #ef4444; padding: 15px; margin: 20px 0;">
            <p style="margin: 0; font-weight: bold; color: #991b1b;">Ausstehender Betrag: CHF {offener_betrag:,.2f}</p>
        </div>
        <p>Sollten Sie die Zahlung bereits getätigt haben, betrachten Sie dieses Schreiben bitte als gegenstandslos. Andernfalls bitten wir Sie um eine zeitnahe Überweisung.</p>
        <p>Freundliche Grüsse,<br>Ihre Liegenschaftsverwaltung</p>
    </body></html>
    """
    threading.Thread(target=send_via_hoststar, args=(mieter.email, subject, html_msg)).start()
    return True