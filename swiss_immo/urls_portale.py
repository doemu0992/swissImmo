"""Portale und Token-Zugänge: Eigentümer, Mieter, Handwerker (Auftrag, Direktkanal).

Aus `swiss_immo/urls.py` ausgelagert, Reihenfolge der Routen unverändert (die Reihenfolge entscheidet bei
überlappenden Mustern). Die Namen bleiben global (kein Namensraum): `reverse('fw_…')` und `{% url %}` ändern sich nicht.
"""
from core.views.direkt_link import direkt_link
from core.views.eigentuemer_portal import (
    fw_ablage_portal_toggle,
    portal_abrechnung_pdf,
    portal_abrechnungen,
    portal_dokumente,
    portal_liegenschaft,
    portal_liegenschaften,
    portal_mitteilungen,
    portal_profil,
    portal_schaden,
    portal_schaeden)
from core.views.fw.schaeden import fw_auftrag_link
from core.views.handwerker_portal import handwerker_auftrag, handwerker_auftrag_foto, handwerker_auftrag_pdf
from django.urls import include, path
from core.views.portal import (
    mieter_anfragen_view,
    mieter_daten_view,
    mieter_dokument_download,
    mieter_dokumente_view,
    mieter_konto_view,
    mieter_kontoauszug_pdf,
    mieter_kuendigung,
    mieter_kuendigung_pdf,
    mieter_mietbestaetigung_pdf,
    mieter_passwort_view,
    mieter_portal_view,
    mieter_rechnung_qr,
    mieter_rechnungen_view,
    mieter_schaden_formular,
    mieter_schaden_melden,
    mieter_ticket_detail,
    mieter_ticket_direkt,
    mieter_ticket_nachricht,
    mieter_tickets_view,
    mieter_zaehler_view,
    portal_dokument_download,
    portal_freigabe,
    portal_kontokorrent_pdf,
    portal_report_pdf,
    portal_steuerauszug_pdf,
    portal_view)


urlpatterns = [

    # --- EIGENTÜMER-PORTAL (read-only, nur eigener Eigentuemer) ---
    path('portal/stweg/', include('stweg.portal_urls')),
    path('portal/', portal_view, name='portal'),
    # Eigentümerportal v2 (core/views/eigentuemer_portal.py)
    path('portal/liegenschaften/', portal_liegenschaften, name='portal_liegenschaften'),
    path('portal/liegenschaften/<int:pk>/', portal_liegenschaft, name='portal_liegenschaft'),
    path('portal/schaeden/', portal_schaeden, name='portal_schaeden'),
    path('portal/schaeden/<int:pk>/', portal_schaden, name='portal_schaden'),
    path('portal/abrechnungen/', portal_abrechnungen, name='portal_abrechnungen'),
    path('portal/abrechnungen/pdf/', portal_abrechnung_pdf, name='portal_abrechnung_pdf'),
    path('portal/dokumente/', portal_dokumente, name='portal_dokumente'),
    path('portal/mitteilungen/', portal_mitteilungen, name='portal_mitteilungen'),
    path('portal/profil/', portal_profil, name='portal_profil'),
    path('neu/dokumente/<int:pk>/eigentuemerportal/', fw_ablage_portal_toggle, name='fw_ablage_portal_toggle'),
    path('portal/dokument/<int:pk>/', portal_dokument_download, name='portal_dokument_download'),
    path('portal/report/', portal_report_pdf, name='portal_report_pdf'),
    path('portal/steuerauszug/', portal_steuerauszug_pdf, name='portal_steuerauszug_pdf'),
    path('portal/kontokorrent/', portal_kontokorrent_pdf, name='portal_kontokorrent_pdf'),
    path('portal/freigabe/<int:pk>/', portal_freigabe, name='portal_freigabe'),
    path('mieter/', mieter_portal_view, name='mieter_portal'),
    path('mieter/dokument/<int:pk>/', mieter_dokument_download, name='mieter_dokument_download'),
    path('mieter/schaden/', mieter_schaden_melden, name='mieter_schaden_melden'),
    path('mieter/schaden/neu/', mieter_schaden_formular, name='mieter_schaden_formular'),
    path('mieter/rechnungen/', mieter_rechnungen_view, name='mieter_rechnungen'),
    path('mieter/dokumente/', mieter_dokumente_view, name='mieter_dokumente'),
    path('mieter/tickets/', mieter_tickets_view, name='mieter_tickets'),
    path('mieter/ticket/<int:pk>/', mieter_ticket_detail, name='mieter_ticket_detail'),
    path('mieter/ticket/<int:pk>/nachricht/', mieter_ticket_nachricht, name='mieter_ticket_nachricht'),
    path('mieter/ticket/<int:pk>/direkt/<int:auftrag_id>/', mieter_ticket_direkt, name='mieter_ticket_direkt'),
    path('mieter/rechnung/<int:pk>/', mieter_rechnung_qr, name='mieter_rechnung_qr'),
    path('mieter/kontoauszug/', mieter_kontoauszug_pdf, name='mieter_kontoauszug_pdf'),
    path('mieter/konto/', mieter_konto_view, name='mieter_konto'),
    path('mieter/anfragen/', mieter_anfragen_view, name='mieter_anfragen'),
    path('mieter/zaehler/', mieter_zaehler_view, name='mieter_zaehler'),
    path('mieter/mietbestaetigung/<int:pk>/pdf/', mieter_mietbestaetigung_pdf, name='mieter_mietbestaetigung_pdf'),
    path('mieter/daten/', mieter_daten_view, name='mieter_daten'),
    path('mieter/passwort/', mieter_passwort_view, name='mieter_passwort'),
    path('mieter/kuendigung/', mieter_kuendigung, name='mieter_kuendigung'),
    path('mieter/kuendigung/<int:pk>/brief/', mieter_kuendigung_pdf, name='mieter_kuendigung_pdf'),

    # --- MODUL 3: HANDWERKERPORTAL (öffentlich, Token statt Konto; E6) ---
    path('auftrag/<str:token>/', handwerker_auftrag, name='handwerker_auftrag'),
    path('direkt/<str:signiert>/', direkt_link, name='direkt_link'),
    path('auftrag/<str:token>/pdf/', handwerker_auftrag_pdf, name='handwerker_auftrag_pdf'),
    path('auftrag/<str:token>/foto/<int:nr>/', handwerker_auftrag_foto, name='handwerker_auftrag_foto'),
    path('neu/auftrag/<int:pk>/link/', fw_auftrag_link, name='fw_auftrag_link'),
]
