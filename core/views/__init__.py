# Das ist die "Zentrale", die alle Views sammelt

from .dashboard import dashboard_view
from .contracts import mietzins_anpassung_view, generiere_amtliches_formular
from .issues import ticket_erstellen, ticket_detail_public, ticket_detail_admin
from .pdf import abrechnung_pdf_view, generate_pdf_view
from .docuseal import send_via_docuseal, docuseal_webhook
from .billing import qr_rechnung_pdf  # <-- Hier ist unser neuer QR-View!