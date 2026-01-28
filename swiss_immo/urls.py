from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

# WICHTIG: Jetzt importieren wir alles sauber direkt aus "core.views"
# Wir müssen nicht mehr wissen, ob es in "dashboard.py" oder "billing.py" liegt.
from core.views import (
    dashboard_view,
    mietzins_anpassung_view, generiere_amtliches_formular,
    ticket_erstellen, ticket_detail_public, ticket_detail_admin,
    abrechnung_pdf_view, generate_pdf_view,
    send_via_docuseal, docuseal_webhook,
    qr_rechnung_pdf  # <-- Neu dabei
)

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Dashboard
    path('', dashboard_view, name='index'),
    path('dashboard/', dashboard_view, name='dashboard'),

    # Prozesse: Mietzins
    path('mietzins/<int:vertrag_id>/', mietzins_anpassung_view, name='mietzins_anpassung'),
    path('formular/amtlich/<int:vertrag_id>/', generiere_amtliches_formular, name='amtliches_formular'),

    # Prozesse: Tickets & Chat
    path('schaden/melden/', ticket_erstellen, name='ticket_erstellen'),
    path('ticket/status/<uuid:uuid>/', ticket_detail_public, name='ticket_detail_public'),
    path('ticket/admin/<int:pk>/', ticket_detail_admin, name='ticket_detail_admin'),

    # PDFs (Verträge & Abrechnung)
    path('pdf/abrechnung/<int:pk>/', abrechnung_pdf_view, name='abrechnung_pdf'),
    path('vertrag/<int:vertrag_id>/pdf/', generate_pdf_view, name='generate_pdf'),

    # NEU: QR-Rechnung (Der Link für den roten Button)
    path('qr-rechnung/<int:vertrag_id>/', qr_rechnung_pdf, name='qr_rechnung_pdf'),

    # DocuSeal
    path('vertrag/<int:vertrag_id>/senden/', send_via_docuseal, name='send_docuseal'),
    path('docuseal/webhook/', docuseal_webhook, name='docuseal_webhook'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)