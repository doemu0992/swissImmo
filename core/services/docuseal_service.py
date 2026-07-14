"""Zentraler DocuSeal-Versand: generiert das Vertrags-PDF und schickt es zur
digitalen Unterschrift an den Mieter. Von Wizard, Vertrag-Detail und Alt-View
gemeinsam genutzt. Gibt (ok, meldung) zurück statt Redirect/Messages, damit die
Aufrufer die UX selbst steuern. Der Rücklauf (unterschriebenes PDF) kommt per
Webhook (core/views/docuseal.py) und wird via ablage_signierter_vertrag zentral
abgelegt."""
import base64
import io
import logging

from django.conf import settings
from django.template.loader import get_template
from django.utils import timezone

logger = logging.getLogger(__name__)


def docuseal_konfiguriert():
    return bool(getattr(settings, 'DOCUSEAL_API_KEY', None))


def docuseal_senden(vertrag):
    """Sendet den Vertrag zur Unterschrift. Returns (ok: bool, meldung: str)."""
    api_key = getattr(settings, 'DOCUSEAL_API_KEY', None)
    if not api_key:
        return (False, "DocuSeal ist nicht konfiguriert (API-Key fehlt). "
                       "Unter Integrationen hinterlegen.")
    mieter = vertrag.mieter
    if not mieter or not (mieter.email or '').strip():
        return (False, "Der Mieter hat keine E-Mail-Adresse — Versand nicht möglich.")

    try:
        import requests
        from xhtml2pdf import pisa
        from django.contrib.staticfiles import finders
        from core.views.docuseal import link_callback, sanitize_filename

        einheit = vertrag.einheit
        liegenschaft = einheit.liegenschaft
        mandant = getattr(liegenschaft, 'mandant', None)
        template_path = ('core/mietvertrag_garage.html'
                         if einheit.typ in ('pp', 'bas', 'gar')
                         else 'core/mietvertrag_pdf.html')

        unterschrift_path = None
        if mandant and getattr(mandant, 'unterschrift_bild', None):
            try:
                unterschrift_path = mandant.unterschrift_bild.path
            except Exception:
                unterschrift_path = None
        if not unterschrift_path:
            dummy = finders.find("img/unterschrift_dummy.png")
            if dummy:
                unterschrift_path = dummy

        netto = vertrag.netto_mietzins or 0
        nk = vertrag.nebenkosten or 0
        context = {
            'vertrag': vertrag, 'mieter': mieter, 'einheit': einheit,
            'liegenschaft': liegenschaft, 'mandant': mandant,
            'verwaltungs_name': getattr(settings, 'VERWALTUNG_NAME', 'SwissImmo Verwaltung'),
            'heute': timezone.now().date(),
            'miete_fmt': f"{netto:.2f}", 'nk_fmt': f"{nk:.2f}",
            'brutto_fmt': f"{(netto + nk):.2f}",
            'kaution_fmt': f"{(vertrag.kautions_betrag or 0):.2f}",
            'unterschrift_path': unterschrift_path,
        }
        html = get_template(template_path).render(context)
        pdf_file = io.BytesIO()
        status = pisa.CreatePDF(html, dest=pdf_file, link_callback=link_callback)
        if status.err:
            return (False, "Vertrags-PDF konnte nicht erzeugt werden.")

        b64 = base64.b64encode(pdf_file.getvalue()).decode('ascii').replace('\n', '')
        filename = f"{sanitize_filename(f'mietvertrag_{mieter.nachname}_{vertrag.id}')}.pdf"
        payload = {
            "name": f"Mietvertrag {vertrag.id}", "send_email": True,
            "documents": [{"name": filename, "file": b64, "fields": [{
                "name": "Unterschrift_Mieter", "type": "signature", "role": "Mieter",
                "required": True,
                "areas": [{"x": 300, "y": 650, "w": 180, "h": 60, "page": 2}]}]}],
            "submitters": [{"role": "Mieter", "email": mieter.email, "send_email": True,
                            "name": f"{mieter.vorname} {mieter.nachname}".strip() or mieter.display_name}],
        }
        resp = requests.post("https://api.docuseal.com/submissions/pdf",
                             headers={"X-Auth-Token": api_key, "Content-Type": "application/json"},
                             json=payload, timeout=30)
        if resp.status_code in (200, 201):
            vertrag.sign_status = 'gesendet'
            vertrag.save(update_fields=['sign_status'])
            return (True, f"Vertrag an {mieter.email} zur Unterschrift gesendet.")
        return (False, f"DocuSeal-Fehler {resp.status_code}.")
    except Exception as e:
        logger.error(f"DocuSeal-Versand fehlgeschlagen: {e}")
        return (False, f"Versand fehlgeschlagen: {e}")
