from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

# Views importieren
from core.views.dashboard import dashboard_view
from core.views.contracts import mietzins_anpassung_view, generiere_amtliches_formular
from core.views.issues import ticket_erstellen, ticket_detail_public, ticket_detail_admin # NEU
from core.views.pdf import abrechnung_pdf_view, generate_pdf_view
from core.views.docuseal import send_via_docuseal, docuseal_webhook

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Dashboard
    path('', dashboard_view, name='index'),
    path('dashboard/', dashboard_view, name='dashboard'),

    # Prozesse: Mietzins
    path('mietzins/<int:vertrag_id>/', mietzins_anpassung_view, name='mietzins_anpassung'),
    path('formular/amtlich/<int:vertrag_id>/', generiere_amtliches_formular, name='amtliches_formular'),

    # Prozesse: Tickets & Chat (NEU)
    path('schaden/melden/', ticket_erstellen, name='ticket_erstellen'),
    path('ticket/status/<uuid:uuid>/', ticket_detail_public, name='ticket_detail_public'),
    path('ticket/admin/<int:pk>/', ticket_detail_admin, name='ticket_detail_admin'),

    # PDFs
    path('pdf/abrechnung/<int:pk>/', abrechnung_pdf_view, name='abrechnung_pdf'),
    path('vertrag/<int:vertrag_id>/pdf/', generate_pdf_view, name='generate_pdf'),

    # DocuSeal
    path('vertrag/<int:vertrag_id>/senden/', send_via_docuseal, name='send_docuseal'),
    path('docuseal/webhook/', docuseal_webhook, name='docuseal_webhook'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)