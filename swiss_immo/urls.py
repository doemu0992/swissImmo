from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

# Import der Views aus core/views.py
from core.views import (
    dashboard_view,
    mietzins_anpassung_view,
    schaden_melden_public,
    abrechnung_pdf_view,
    generate_pdf_view,            # PDF Generierung (Manuell)
    send_via_docuseal,            # Versand Funktion (DocuSeal API)
    docuseal_webhook,             # Webhook (Rückmeldung)
    generiere_amtliches_formular
)

urlpatterns = [
    # Admin-Bereich
    path('admin/', admin.site.urls),

    # Dashboard (Startseite)
    path('', dashboard_view, name='index'),
    path('dashboard/', dashboard_view, name='dashboard'),

    # Prozesse & Formulare
    path('mietzins/<int:vertrag_id>/', mietzins_anpassung_view, name='mietzins_anpassung'),
    path('schaden/melden/', schaden_melden_public, name='schaden_melden'),

    # PDF Generierung (Lokal Download für NK-Abrechnung)
    path('pdf/abrechnung/<int:pk>/', abrechnung_pdf_view, name='abrechnung_pdf'),

    # ==========================================
    # MIETVERTRAG & DOCUSEAL
    # ==========================================

    # 1. PDF Ansehen/Downloaden (Manuell)
    path('vertrag/<int:vertrag_id>/pdf/', generate_pdf_view, name='generate_pdf'),

    # 2. SENDEN via API
    path('vertrag/<int:vertrag_id>/senden/', send_via_docuseal, name='send_docuseal'),

    # 3. WEBHOOK
    # KORREKTUR: Pfad muss 'docuseal/webhook/' sein, damit er zur DocuSeal-Einstellung passt
    path('docuseal/webhook/', docuseal_webhook, name='docuseal_webhook'),

    # Helper / Platzhalter
    path('formular/amtlich/<int:vertrag_id>/', generiere_amtliches_formular, name='amtliches_formular'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)