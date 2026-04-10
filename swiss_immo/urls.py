from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# ========================================================
# VIEWS IMPORTE
# ========================================================

# 1. Landing Page & Public Tickets
from core.views.ticket_public import public_ticket_view, generate_hallway_poster, index_view

# 2. Das neue Admin-Cockpit
from core.views.dashboard_view import custom_dashboard_view

# 3. Verträge & Mietzins
from core.views.contracts import mietzins_anpassung_view, generiere_amtliches_formular

# 4. Ticket System
from core.views.issues import ticket_erstellen, ticket_detail_public, ticket_detail_admin

# 5. PDF (Nur Mietvertrag)
from core.views.pdf import generate_pdf_view

# 6. DocuSeal
from core.views.docuseal import send_via_docuseal, docuseal_webhook

# 7. Abrechnung, QR & Finanzen
from core.views.billing import abrechnung_pdf_view, qr_rechnung_pdf
from core.views.email_views import send_abrechnung_email_view


urlpatterns = [
    # --- STARTSEITE ---
    path('', index_view, name='index'),

    # --- DASHBOARD ---
    path('admin/dashboard/', custom_dashboard_view, name='admin_dashboard'),

    # --- ADMIN ---
    path('admin/', admin.site.urls),

    # --- PROZESSE ---
    path('mietzins/<int:vertrag_id>/', mietzins_anpassung_view, name='mietzins_anpassung'),
    path('formular/amtlich/<int:vertrag_id>/', generiere_amtliches_formular, name='amtliches_formular'),

    # Ticket System
    path('schaden/melden/', ticket_erstellen, name='ticket_erstellen'),
    path('ticket/status/<uuid:uuid>/', ticket_detail_public, name='ticket_detail_public'),
    path('ticket/admin/<int:pk>/', ticket_detail_admin, name='ticket_detail_admin'),

    # --- PDF & E-MAIL ---
    path('vertrag/<int:vertrag_id>/pdf/', generate_pdf_view, name='generate_pdf'),
    path('abrechnung/<int:periode_id>/pdf/', abrechnung_pdf_view, name='abrechnung_pdf'),
    path('abrechnung/<int:periode_id>/send-mail/', send_abrechnung_email_view, name='abrechnung_send_mail'),

    # --- QR RECHNUNG ---
    path('vertrag/<int:vertrag_id>/qr/', qr_rechnung_pdf, name='generate_qr'),

    # --- DOCUSEAL ---
    path('vertrag/<int:vertrag_id>/senden/', send_via_docuseal, name='send_docuseal'),
    path('docuseal/webhook/', docuseal_webhook, name='docuseal_webhook'),

    # --- QR CODE SYSTEM (Aushang) ---
    path('report/<int:liegenschaft_id>/', public_ticket_view, name='public_report'),
    path('liegenschaft/<int:liegenschaft_id>/poster/', generate_hallway_poster, name='hallway_poster'),

    # ==========================================
    # NEUES SAAS FRONTEND (SPA)
    # ==========================================
    path('portfolio/', include('portfolio.urls')),
    path('crm/', include('crm.urls')),
    path('rentals/', include('rentals.urls')),
    path('tickets/', include('tickets.urls')),
    path('finance/', include('finance.urls')),  # <--- 🔥 HIER IST DIE NEUE ZEILE FÜR DIE FINANZEN 🔥

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)