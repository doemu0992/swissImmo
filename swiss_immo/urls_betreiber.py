"""Betreiber-Konsole unter /betreiber/ (Kunden, Abo, CSP, LIK-Werte, Sicherheit).

Aus `swiss_immo/urls.py` ausgelagert, Reihenfolge der Routen unverändert (die Reihenfolge entscheidet bei
überlappenden Mustern). Die Namen bleiben global (kein Namensraum): `reverse('fw_…')` und `{% url %}` ändern sich nicht.
"""
from core.views.fw.betreiber import (
    fw_betreiber,
    fw_betreiber_csp,
    fw_betreiber_kunde,
    fw_betreiber_kunde_abo,
    fw_betreiber_kunde_bearbeiten,
    fw_betreiber_lik,
    fw_betreiber_neu,
    fw_betreiber_rechnung_pdf)
from core.views.fw.sicherheit import fw_sicherheit
from django.urls import path
from core.views.zweifaktor import zweifaktor_login


urlpatterns = [
    # Betreiber-Portal: eigener Bereich wie das Eigentümer- und das Mieterportal, nicht Teil der Verwaltungs-Oberfläche.
    path('betreiber/login/', lambda r: zweifaktor_login(r, template_name='core/portal_login.html'), name='betreiber_login'),
    path('betreiber/', fw_betreiber, name='betreiber'),
    path('betreiber/neu/', fw_betreiber_neu, name='fw_betreiber_neu'),
    path('betreiber/sicherheit/', fw_sicherheit, name='fw_sicherheit'),
    path('betreiber/csp/', fw_betreiber_csp, name='fw_betreiber_csp'),
    path('betreiber/lik/', fw_betreiber_lik, name='fw_betreiber_lik'),
    path('betreiber/<int:pk>/', fw_betreiber_kunde, name='fw_betreiber_kunde'),
    path('betreiber/<int:pk>/bearbeiten/', fw_betreiber_kunde_bearbeiten, name='fw_betreiber_kunde_bearbeiten'),
    path('betreiber/<int:pk>/abo/', fw_betreiber_kunde_abo, name='fw_betreiber_kunde_abo'),
    path('betreiber/<int:pk>/rechnung/<int:rechnung>/pdf/', fw_betreiber_rechnung_pdf, name='fw_betreiber_rechnung_pdf'),
]
