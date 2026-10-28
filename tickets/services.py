# tickets/services.py
import io
import segno
from django.core.mail import send_mail
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

from .models import SchadenMeldung, TicketNachricht, HandwerkerAuftrag
from core.utils.email_service import send_ticket_receipt

# --- 1. INTERNE VERWALTUNGS-LOGIK ---

def create_handwerker_auftrag(ticket, handwerker, bemerkung=""):
    """
    Erstellt einen Auftrag für einen Handwerker und postet automatisch
    eine interne Systemnachricht in den Chat.
    """
    auftrag = HandwerkerAuftrag.objects.create(
        ticket=ticket,
        handwerker=handwerker,
        bemerkung=bemerkung
    )

    # System-Meldung in den Chat
    TicketNachricht.objects.create(
        ticket=ticket,
        absender_name="System",
        typ='system',
        nachricht=f"Handwerker beauftragt: {handwerker}",
        is_intern=True
    )
    return auftrag

def add_chat_message(ticket, text, absender="Verwaltung", is_von_verwaltung=True):
    """
    Fügt eine Chatnachricht hinzu und aktualisiert den Ticket-Status.
    """
    msg = TicketNachricht.objects.create(
        ticket=ticket,
        absender_name=absender,
        typ='chat',
        nachricht=text,
        is_von_verwaltung=is_von_verwaltung
    )

    if is_von_verwaltung and ticket.status == 'neu':
        ticket.status = 'in_bearbeitung'
        ticket.save()

    return msg


# --- 2. ÖFFENTLICHE FORMULAR & PDF LOGIK ---

class MeldungUngueltig(ValueError):
    """Das öffentliche Meldeformular wurde unvollständig oder falsch ausgefüllt.

    `fehler` ist eine Liste lesbarer Meldungen für den Melder. Es wurde dabei
    NICHTS angelegt.
    """

    def __init__(self, fehler):
        super().__init__('; '.join(fehler))
        self.fehler = list(fehler)


#: Feldlängen des öffentlichen QR-Formulars. Sie folgen den Spalten von
#: `SchadenMeldung` (SICH-14: SQLite schweigt bei zu langem Text, PostgreSQL
#: antwortet mit 500) und lassen für `titel (nachname)` Platz in den 200 Zeichen
#: von `SchadenMeldung.titel`.
GRENZEN_QR = {
    'titel': 100, 'nachname': 70, 'vorname': 100, 'anrede': 20, 'email': 254,
    'telefon': 50, 'hersteller': 100, 'seriennummer': 100, 'beschreibung': 5000,
}


def pruefe_oeffentliche_meldung(liegenschaft, post_data, files_data):
    """Prüft das QR-Formular und gibt die bereinigten Werte zurück.

    Wirft `MeldungUngueltig`, ohne etwas anzulegen. Die Einheit wird NUR aus der
    Liegenschaft des Aushangs aufgelöst (SICH-08): Eine ID aus dem Formular, die
    zu einer anderen Liegenschaft oder gar einer fremden Verwaltung gehört,
    verknüpfte sonst das Ticket mit deren Einheit. Der Aufrufer setzt den
    Mandantenkontext der Liegenschaft (`kontext_des_objekts`).
    """
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    from django.utils.translation import gettext as _

    from core.utils.formularid import eigenes_objekt
    from core.utils.uploads import validiere_bild
    from portfolio.models import Einheit

    fehler = []

    def text(name, pflicht=False, bezeichnung=None):
        wert = (post_data.get(name) or '').strip()
        bez = bezeichnung or name
        if pflicht and not wert:
            fehler.append(_('Bitte füllen Sie das Feld «%(feld)s» aus.') % {'feld': bez})
        elif len(wert) > GRENZEN_QR[name]:
            fehler.append(_('«%(feld)s» ist zu lang (höchstens %(n)s Zeichen).')
                          % {'feld': bez, 'n': GRENZEN_QR[name]})
        return wert

    titel = text('titel', True, _('Anliegen'))
    beschreibung = text('beschreibung', True, _('Beschreibung'))
    anrede = text('anrede', False, _('Anrede'))
    vorname = text('vorname', True, _('Vorname'))
    nachname = text('nachname', True, _('Nachname'))
    email = text('email', True, _('E-Mail'))
    telefon = text('telefon', True, _('Telefon'))
    hersteller = text('hersteller', False, _('Marke / Hersteller'))
    seriennummer = text('seriennummer', False, _('Seriennummer'))
    if email and len(email) <= GRENZEN_QR['email']:
        try:
            validate_email(email)
        except ValidationError:
            fehler.append(_('Bitte geben Sie eine gültige E-Mail-Adresse an.'))

    einheit = None
    einheit_roh = (post_data.get('einheit_id') or '').strip()
    if einheit_roh:
        einheit = eigenes_objekt(Einheit, einheit_roh, liegenschaft=liegenschaft)
        if einheit is None:
            fehler.append(_('Die gewählte Einheit gibt es in dieser Liegenschaft nicht.'))

    foto = files_data.get('foto')
    if foto:
        ok, _grund = validiere_bild(foto)
        if not ok:
            fehler.append(_('Das Foto konnte nicht verwendet werden. Bitte wählen Sie ein Bild '
                            '(JPEG, PNG, WebP oder HEIC) bis 15 MB.'))

    if fehler:
        raise MeldungUngueltig(fehler)

    from .meldung import gueltige_zeitfenster
    return {
        'titel': titel, 'beschreibung': beschreibung, 'anrede': anrede,
        'vorname': vorname, 'nachname': nachname, 'email': email, 'telefon': telefon,
        'hersteller': hersteller, 'seriennummer': seriennummer, 'einheit': einheit,
        'foto': foto or None,
        'erreichbarkeit': gueltige_zeitfenster(post_data.getlist('erreichbarkeit')),
    }


def process_public_ticket_form(liegenschaft, post_data, files_data):
    """
    Verarbeitet das öffentliche QR-Formular, setzt die Beschreibung
    zusammen und speichert das Ticket.

    Wirft `MeldungUngueltig`, wenn Pflichtfelder fehlen, ein Text zu lang ist,
    die Einheit nicht zur Liegenschaft gehört oder das Foto kein Bild ist.
    """
    d = pruefe_oeffentliche_meldung(liegenschaft, post_data, files_data)

    melder_name = f"{d['anrede']} {d['vorname']} {d['nachname']}".strip()

    # Beschreibung zusammenbauen
    final_text = f"{d['beschreibung']}\n\n--- KONTAKT ---\n"
    final_text += f"Name: {melder_name}\nTel: {d['telefon']}\nEmail: {d['email']}\n"

    if d['erreichbarkeit']:
        from .meldung import erreichbarkeit_zeile
        final_text += f"{erreichbarkeit_zeile(d['erreichbarkeit'])}\n"

    if d['hersteller'] or d['seriennummer']:
        final_text += "\n--- GERÄT ---\n"
        if d['hersteller']:
            final_text += f"Marke: {d['hersteller']}\n"
        if d['seriennummer']:
            final_text += f"S/N: {d['seriennummer']}\n"

    # Speichern
    ticket = SchadenMeldung(
        titel=f"{d['titel']} ({d['nachname']})",
        beschreibung=final_text,
        prioritaet='mittel',
        status='neu',
        betroffene_einheit=d['einheit'],
        liegenschaft=liegenschaft,
        email_melder=d['email'],
        tel_melder=d['telefon'],
        gemeldet_von=None
    )
    if d['foto']:
        ticket.foto = d['foto']
    ticket.save()

    # Bestätigungs-Email via Brevo senden
    try:
        send_ticket_receipt(ticket)
    except Exception as e:
        print(f"Fehler beim Mailversand: {e}")

    return ticket

def generate_qr_poster(liegenschaft, domain):
    """
    Generiert das PDF für den Treppenhaus-Aushang mit QR-Code.
    Rückgabe ist ein BytesIO Buffer.
    """
    report_url = f"https://{domain}/report/{liegenschaft.id}/"

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header Balken (Blau)
    c.setFillColorRGB(0.1, 0.4, 0.8)
    c.rect(0, height - 60*mm, width, 60*mm, fill=1, stroke=0)

    # Header Text
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(width/2, height - 30*mm, "Haben Sie ein Anliegen?")
    c.setFont("Helvetica", 16)
    c.drawCentredString(width/2, height - 45*mm, f"Liegenschaft: {liegenschaft.strasse}, {liegenschaft.ort}")

    # QR Code generieren
    qr = segno.make(report_url, error='H')
    qr_img = io.BytesIO()
    qr.save(qr_img, kind='png', scale=10)
    qr_img.seek(0)

    # QR Code zeichnen
    c.drawImage(ImageReader(qr_img), (width/2) - 40*mm, height - 160*mm, width=80*mm, height=80*mm)

    # Anweisung Text
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width/2, height - 180*mm, "Scannen & Melden")

    c.setFont("Helvetica", 12)
    c.setFillColor(colors.darkgrey)
    lines = ["1. Kamera öffnen", "2. QR-Code scannen", "3. Problem direkt am Handy melden", "4. Wir kümmern uns darum!"]
    y = height - 200*mm
    for line in lines:
        c.drawCentredString(width/2, y, line)
        y -= 8*mm

    c.showPage()
    c.save()
    buffer.seek(0)

    return buffer