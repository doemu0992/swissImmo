# finance/urls.py
from django.urls import path
from . import views

# Beide neuen Funktionen aus unserer email_views.py importieren!
from core.views.email_views import send_mahnung_email_view, generate_mahnung_pdf_view

urlpatterns = [
    # Nebenkosten
    path('abrechnungen/', views.abrechnung_liste, name='abrechnung_liste'),
    path('abrechnung/<int:pk>/', views.abrechnung_detail, name='abrechnung_detail'),

    # Mieten & Kontrolle (SaaS Features)
    path('zahlungen/', views.zahlung_liste, name='zahlung_liste'),
    path('kontrolle/', views.mietzins_kontrolle, name='mietzins_kontrolle'),

    # 1. E-Mail Mahnung (Soft)
    path('kontrolle/mahnung/mail/<int:vertrag_id>/', send_mahnung_email_view, name='send_mahnung_mail'),

    # 🔥 2. NEU: PDF Mahnung gem. Art. 257d OR (Hard)
    path('kontrolle/mahnung/pdf/<int:vertrag_id>/', generate_mahnung_pdf_view, name='generate_mahnung_pdf'),
]