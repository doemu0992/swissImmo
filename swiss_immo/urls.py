# swiss_immo/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views  # <-- Import für den Login

# ========================================================
# 🚀 API SETUP (DJANGO NINJA)
# ========================================================
from ninja import NinjaAPI
from django.contrib.admin.views.decorators import staff_member_required
from core.auth import auth_lesen
# Router importieren
from portfolio.api import router as portfolio_router
from crm.api import router as crm_router
from rentals.api import router as rentals_router
from tickets.api import router as tickets_router
from finance.api import router as finance_router
from mietprozess.api import router as mietprozess_router

# Wir initialisieren die zentrale API mit dem Rollenkonzept (core/auth.py):
#   Standard (alle GETs):   auth_lesen      → Verwaltung, Sachbearbeitung, Lesend
#   Erfassen/Bearbeiten:    auth_schreiben  → Verwaltung, Sachbearbeitung
#   Löschen/Buchen/Senden:  auth_verwaltung → nur Verwaltung
# Öffentliche Ausnahmen sind am Endpoint mit auth=None markiert
# (Bewerbungsformular, DocuSeal-Webhook).
# docs_decorator: API-Dokumentation (/api/docs) nur für Staff sichtbar.
api = NinjaAPI(
    title="swissImmo API",
    version="1.0.0",
    description="REST API für das Vue.js Frontend",
    auth=auth_lesen,
    docs_decorator=staff_member_required,
)

# Wir registrieren die Module in der API
api.add_router("/portfolio", portfolio_router)
api.add_router("/crm", crm_router)
api.add_router("/rentals", rentals_router)
api.add_router("/tickets", tickets_router)
api.add_router("/finance", finance_router)
api.add_router("/mietprozess", mietprozess_router)


# ========================================================
# VIEWS IMPORTE (Klassisches Django / Legacy)
# ========================================================
# 1. Landing Page & Public Tickets
from core.views.ticket_public import public_ticket_view, generate_hallway_poster, index_view, public_schaden_melden_view
from core.views.application import public_application_view

# 2. Das neue Admin-Cockpit (Bereinigt um das alte Dashboard)
from core.views.dashboard_view import update_market_data_view, spa_master_view

# 2b. Eigentümer-Portal & Login-Weiche
from core.views.portal import (portal_view, nach_login_view, portal_dokument_download, portal_report_pdf, portal_freigabe,
                                portal_steuerauszug_pdf,
                                mieter_portal_view, mieter_dokument_download, mieter_schaden_melden, mieter_rechnung_qr,
                                mieter_kontoauszug_pdf, mieter_kuendigung, mieter_kuendigung_pdf,
                                mieter_tickets_view, mieter_ticket_detail, mieter_ticket_nachricht,
                                mieter_rechnungen_view, mieter_dokumente_view, mieter_schaden_formular)

# 2c. Fairwalter-Rebuild: neue Oberfläche (Etappe A: Shell + Dashboard)
from core.views.fw import (fw_dashboard, fw_finanzen, fw_berichte, fw_auswertung, fw_debitoren, fw_debitor_qr_pdf, fw_debitor_neu, fw_debitor_stornieren, fw_liegenschaften, fw_mieterspiegel, fw_objekte,
                           fw_personen, fw_vertraege, fw_mieterwechsel, fw_vermarktung, fw_objekt_ausschreiben, fw_expose_pdf,
                           fw_liegenschaft_detail, fw_objekt_detail, fw_objekt_foto_upload, fw_objekt_foto_loeschen, fw_vertrag_detail,
                           fw_ausstattung_add, fw_ausstattung_katalog, fw_ausstattung_del, fw_lebensdauer,
                           fw_wartungsfrist_neu, fw_wartungsfrist_loeschen,
                           fw_mahnwesen, fw_debitoren_aging, fw_mahnung_erfassen, fw_mahnlauf, fw_bankkonten,
                           fw_bankabgleich, fw_bankabgleich_verbuchen, fw_camt_import,
                           fw_person_detail, fw_person_form, fw_person_loeschen, fw_dokument_portal_toggle, fw_kommunikation_neu, fw_mieter_portal_zugang, fw_mieterkonto_pdf,
                           fw_mieterkonto, fw_mieterkonten, fw_lieferantenkonten, fw_lieferantenkonto,
                           fw_kreditoren, fw_kreditoren_pain001, fw_kreditor_bezahlen, fw_kreditor_neu, fw_kreditor_freigeben, fw_weiterverrechnung,
                           fw_kreditor_zahlung_zuruecksetzen,
                           fw_dienstleister_neu, fw_asset_neu, fw_dokument_neu, fw_nebenkosten_neu,
                           fw_buchung_neu, fw_buchung_stornieren, fw_kommunikation_senden, fw_serienbrief_pdf,
                           fw_schaeden, fw_schaden_kosten, fw_schaden_detail, fw_schaden_foto_upload, fw_schaden_foto_loeschen, fw_auftrag_kosten, fw_auftrag_pdf,
                           fw_schaden_auftrag, fw_schaden_status, fw_schaden_antwort, fw_schaden_neu,
                           fw_dienstleister, fw_assets, fw_buchhaltung, fw_kontoblatt, fw_buchhaltung_export, fw_anlagen,
                           fw_sollstellung, fw_sollstellung_run,
                           fw_nebenkosten, fw_nebenkosten_detail, fw_nebenkosten_verbuchen, fw_nebenkosten_versand, fw_akonto_anpassen,
                           fw_mietzins, fw_mietzins_anpassung, fw_dokumente, fw_kommunikation,
                           fw_vertrag_neu, fw_vertrag_neu_speichern,
                           fw_vertrag_status, fw_vertrag_loeschen, fw_schlussabrechnung,
                           fw_abnahme_neu, fw_abnahme_detail, fw_abnahme_pdf,
                           fw_kuendigung_erfassen, fw_kuendigung_zuruecknehmen, fw_kuendigung_bestaetigen, fw_kuendigung_formular,
                           fw_verzug_257d,
                           fw_kautionen, fw_kaution_aktion, fw_mwst, fw_mwst_einstellungen, fw_mwst_estv_export,
                           fw_account, fw_marktdaten_aktualisieren, fw_marktdaten_live,
                           fw_benutzer, fw_logbuch, fw_rechtsgrundlagen, fw_mandate, fw_vorlagen, fw_vorlagen_standard, fw_integrationen, fw_abonnemente,
                           fw_liegenschaft_form, fw_liegenschaft_gwr, fw_liegenschaft_loeschen, fw_objekt_form, fw_suche,
                           fw_mandat_form, fw_mandat_loeschen, fw_mandat_abrechnung, fw_mandant_portal_zugang,
                           fw_eigentuemer_kontokorrent, fw_eigentuemer_auszahlung, fw_eigentuemer_honorar,
                           fw_benutzer_form, fw_benutzer_loeschen,
                           fw_vorlage_form, fw_vorlage_loeschen, fw_integration_test_email,
                           fw_vermarktung_feed, fw_integration_portal_token,
                           fw_bewerbungen, fw_bewerber_vergleich, fw_bewerber_entscheid, fw_bewerber_absage_uebrige, fw_bewerbung_detail, fw_bewerbung_status,
                           fw_bewerbung_zu_vertrag,
                           fw_pendenzen, fw_pendenz_neu, fw_pendenz_toggle, fw_pendenz_loeschen, fw_fristen,
                           fw_fristen_ical, fristen_ical_feed)

# 2d. Dossier-Seiten (Detailseiten pro Mieter/Liegenschaft/Vertrag)
from core.views.dossier import mieter_dossier, liegenschaft_dossier, vertrag_dossier

# 3. Verträge & Mietzins
from core.views.contracts import mietzins_anpassung_view, generiere_amtliches_formular

# 4. PDF (Mietvertrag + Begleitdokumente)
from core.views.pdf import generate_pdf_view, generate_dokument_view, generate_vertragspaket_zip

# 5. DocuSeal
from core.views.docuseal import send_via_docuseal, docuseal_webhook

# 6. Abrechnung, QR, Finanzen & Mahnungen
from core.views.billing import abrechnung_pdf_view, qr_rechnung_pdf
from core.views.email_views import send_abrechnung_email_view, send_mahnung_email_view, generate_mahnung_pdf_view

urlpatterns = [
    # --- STARTSEITE ---
    path('', index_view, name='index'),

    # --- EIGENER SAAS LOGIN ---
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    # Eigene Login-Seite für Mieter- und Eigentümer-Portal (gleiche Auth, eigenes Design)
    path('portal/login/', auth_views.LoginView.as_view(template_name='core/portal_login.html'), name='portal_login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('nach-login/', nach_login_view, name='nach_login'),

    # --- FAIRWALTER-REBUILD (neue Oberfläche, wächst etappenweise) ---
    path('neu/', fw_dashboard, name='fw_dashboard'),
    path('neu/debitoren/', fw_debitoren, name='fw_debitoren'),
    path('neu/debitoren/neu/', fw_debitor_neu, name='fw_debitor_neu'),
    path('neu/debitoren/<int:pk>/stornieren/', fw_debitor_stornieren, name='fw_debitor_stornieren'),
    path('neu/debitoren/<int:pk>/qr-pdf/', fw_debitor_qr_pdf, name='fw_debitor_qr_pdf'),
    path('neu/liegenschaften/', fw_liegenschaften, name='fw_liegenschaften'),
    path('neu/mieterspiegel/', fw_mieterspiegel, name='fw_mieterspiegel'),
    path('neu/berichte/', fw_berichte, name='fw_berichte'),
    path('neu/auswertung/', fw_auswertung, name='fw_auswertung'),
    path('neu/liegenschaften/neu/', fw_liegenschaft_form, name='fw_liegenschaft_neu'),
    path('neu/liegenschaften/<int:pk>/bearbeiten/', fw_liegenschaft_form, name='fw_liegenschaft_bearbeiten'),
    path('neu/liegenschaften/<int:pk>/gwr-import/', fw_liegenschaft_gwr, name='fw_liegenschaft_gwr'),
    path('neu/liegenschaften/<int:pk>/loeschen/', fw_liegenschaft_loeschen, name='fw_liegenschaft_loeschen'),
    path('neu/objekte/', fw_objekte, name='fw_objekte'),
    path('neu/objekte/neu/', fw_objekt_form, name='fw_objekt_neu'),
    path('neu/objekte/<int:pk>/bearbeiten/', fw_objekt_form, name='fw_objekt_bearbeiten'),
    path('neu/personen/', fw_personen, name='fw_personen'),
    path('neu/personen/neu/', fw_person_form, name='fw_person_neu'),
    path('neu/personen/<int:pk>/bearbeiten/', fw_person_form, name='fw_person_bearbeiten'),
    path('neu/vertraege/', fw_vertraege, name='fw_vertraege'),
    path('neu/mieterwechsel/', fw_mieterwechsel, name='fw_mieterwechsel'),
    path('neu/vermarktung/', fw_vermarktung, name='fw_vermarktung'),
    path('neu/objekte/<int:einheit_id>/ausschreiben/', fw_objekt_ausschreiben, name='fw_objekt_ausschreiben'),
    path('neu/vermarktung/<int:pk>/expose/', fw_expose_pdf, name='fw_expose_pdf'),
    path('neu/vertraege/neu/', fw_vertrag_neu, name='fw_vertrag_neu'),
    path('neu/vertraege/neu/speichern/', fw_vertrag_neu_speichern, name='fw_vertrag_neu_speichern'),
    path('neu/liegenschaften/<int:pk>/', fw_liegenschaft_detail, name='fw_liegenschaft_detail'),
    path('neu/liegenschaften/<int:pk>/frist/', fw_wartungsfrist_neu, name='fw_wartungsfrist_neu'),
    path('neu/frist/<int:pk>/loeschen/', fw_wartungsfrist_loeschen, name='fw_wartungsfrist_loeschen'),
    path('neu/objekte/<int:pk>/', fw_objekt_detail, name='fw_objekt_detail'),
    path('neu/objekte/<int:pk>/foto/', fw_objekt_foto_upload, name='fw_objekt_foto_upload'),
    path('neu/objekte/foto/<int:pk>/loeschen/', fw_objekt_foto_loeschen, name='fw_objekt_foto_loeschen'),
    path('neu/objekte/<int:pk>/ausstattung/', fw_ausstattung_add, name='fw_ausstattung_add'),
    path('neu/objekte/<int:pk>/ausstattung/katalog/', fw_ausstattung_katalog, name='fw_ausstattung_katalog'),
    path('neu/ausstattung/<int:pk>/loeschen/', fw_ausstattung_del, name='fw_ausstattung_del'),
    path('neu/lebensdauer/', fw_lebensdauer, name='fw_lebensdauer'),
    path('neu/vertraege/<int:pk>/', fw_vertrag_detail, name='fw_vertrag_detail'),
    path('neu/vertraege/<int:pk>/status/', fw_vertrag_status, name='fw_vertrag_status'),
    path('neu/vertraege/<int:vertrag_id>/schlussabrechnung/', fw_schlussabrechnung, name='fw_schlussabrechnung'),
    path('neu/kuendigung/<int:pk>/formular/', fw_kuendigung_formular, name='fw_kuendigung_formular'),
    path('neu/vertraege/<int:pk>/loeschen/', fw_vertrag_loeschen, name='fw_vertrag_loeschen'),
    path('neu/vertraege/<int:vertrag_id>/kuendigen/', fw_kuendigung_erfassen, name='fw_kuendigung_erfassen'),
    path('neu/vertraege/<int:vertrag_id>/verzug/', fw_verzug_257d, name='fw_verzug_257d'),
    path('neu/kuendigung/<int:pk>/zuruecknehmen/', fw_kuendigung_zuruecknehmen, name='fw_kuendigung_zuruecknehmen'),
    path('neu/kuendigung/<int:pk>/bestaetigen/', fw_kuendigung_bestaetigen, name='fw_kuendigung_bestaetigen'),
    path('neu/kautionen/', fw_kautionen, name='fw_kautionen'),
    path('neu/mwst/', fw_mwst, name='fw_mwst'),
    path('neu/mwst/einstellungen/', fw_mwst_einstellungen, name='fw_mwst_einstellungen'),
    path('neu/mwst/estv-export/', fw_mwst_estv_export, name='fw_mwst_estv_export'),
    path('neu/vertraege/<int:vertrag_id>/kaution/', fw_kaution_aktion, name='fw_kaution_aktion'),
    path('neu/personen/<int:pk>/', fw_person_detail, name='fw_person_detail'),
    path('neu/personen/<int:pk>/loeschen/', fw_person_loeschen, name='fw_person_loeschen'),
    path('neu/dokument/<int:pk>/portal-sichtbar/', fw_dokument_portal_toggle, name='fw_dokument_portal_toggle'),
    path('neu/personen/<int:pk>/portal-zugang/', fw_mieter_portal_zugang, name='fw_mieter_portal_zugang'),
    path('neu/mieterkonten/', fw_mieterkonten, name='fw_mieterkonten'),
    path('neu/mieterkonten/<int:pk>/', fw_mieterkonto, name='fw_mieterkonto'),
    path('neu/lieferantenkonten/', fw_lieferantenkonten, name='fw_lieferantenkonten'),
    path('neu/lieferantenkonto/', fw_lieferantenkonto, name='fw_lieferantenkonto'),
    path('neu/personen/<int:pk>/kontoauszug/', fw_mieterkonto_pdf, name='fw_mieterkonto_pdf'),
    path('neu/kommunikation/notiz/', fw_kommunikation_neu, name='fw_kommunikation_neu'),
    path('neu/kreditoren/', fw_kreditoren, name='fw_kreditoren'),
    path('neu/kreditoren/<int:kreditor_id>/weiterverrechnen/', fw_weiterverrechnung, name='fw_weiterverrechnung'),
    path('neu/kreditoren/<int:pk>/zahlung-zuruecksetzen/', fw_kreditor_zahlung_zuruecksetzen, name='fw_kreditor_zahlung_zuruecksetzen'),
    path('neu/kreditoren/pain001/', fw_kreditoren_pain001, name='fw_kreditoren_pain001'),
    path('neu/kreditoren/neu/', fw_kreditor_neu, name='fw_kreditor_neu'),
    path('neu/kreditoren/<int:pk>/freigeben/', fw_kreditor_freigeben, name='fw_kreditor_freigeben'),
    path('neu/kreditoren/bezahlen/', fw_kreditor_bezahlen, name='fw_kreditor_bezahlen'),
    path('neu/schaeden/', fw_schaeden, name='fw_schaeden'),
    path('neu/schaeden/kosten/', fw_schaden_kosten, name='fw_schaden_kosten'),
    path('neu/schaeden/neu/', fw_schaden_neu, name='fw_schaden_neu'),
    path('neu/schaeden/<int:pk>/', fw_schaden_detail, name='fw_schaden_detail'),
    path('neu/auftrag/<int:pk>/kosten/', fw_auftrag_kosten, name='fw_auftrag_kosten'),
    path('neu/auftrag/<int:pk>/pdf/', fw_auftrag_pdf, name='fw_auftrag_pdf'),
    path('neu/schaeden/<int:pk>/foto/', fw_schaden_foto_upload, name='fw_schaden_foto_upload'),
    path('neu/schaeden/foto/<int:pk>/loeschen/', fw_schaden_foto_loeschen, name='fw_schaden_foto_loeschen'),
    path('neu/schaeden/<int:pk>/auftrag/', fw_schaden_auftrag, name='fw_schaden_auftrag'),
    path('neu/schaeden/<int:pk>/status/', fw_schaden_status, name='fw_schaden_status'),
    path('neu/schaeden/<int:pk>/antwort/', fw_schaden_antwort, name='fw_schaden_antwort'),
    path('neu/dienstleister/', fw_dienstleister, name='fw_dienstleister'),
    path('neu/dienstleister/neu/', fw_dienstleister_neu, name='fw_dienstleister_neu'),
    path('neu/assets/', fw_assets, name='fw_assets'),
    path('neu/assets/neu/', fw_asset_neu, name='fw_asset_neu'),
    path('neu/finanzen/', fw_finanzen, name='fw_finanzen'),
    path('neu/buchhaltung/', fw_buchhaltung, name='fw_buchhaltung'),
    path('neu/buchhaltung/export/', fw_buchhaltung_export, name='fw_buchhaltung_export'),
    path('neu/buchhaltung/konto/<str:nummer>/', fw_kontoblatt, name='fw_kontoblatt'),
    path('neu/anlagen/', fw_anlagen, name='fw_anlagen'),
    path('neu/buchhaltung/buchung/', fw_buchung_neu, name='fw_buchung_neu'),
    path('neu/buchhaltung/buchung/<int:pk>/stornieren/', fw_buchung_stornieren, name='fw_buchung_stornieren'),
    path('neu/sollstellung/', fw_sollstellung, name='fw_sollstellung'),
    path('neu/sollstellung/starten/', fw_sollstellung_run, name='fw_sollstellung_run'),
    path('neu/nebenkosten/', fw_nebenkosten, name='fw_nebenkosten'),
    path('neu/nebenkosten/neu/', fw_nebenkosten_neu, name='fw_nebenkosten_neu'),
    path('neu/nebenkosten/<int:pk>/', fw_nebenkosten_detail, name='fw_nebenkosten_detail'),
    path('neu/nebenkosten/<int:pk>/verbuchen/', fw_nebenkosten_verbuchen, name='fw_nebenkosten_verbuchen'),
    path('neu/nebenkosten/<int:pk>/versand/', fw_nebenkosten_versand, name='fw_nebenkosten_versand'),
    path('neu/nebenkosten/<int:pk>/akonto/', fw_akonto_anpassen, name='fw_akonto_anpassen'),
    path('neu/pendenzen/', fw_pendenzen, name='fw_pendenzen'),
    path('neu/fristen/', fw_fristen, name='fw_fristen'),
    path('neu/fristen/export.ics', fw_fristen_ical, name='fw_fristen_ical'),
    path('fristen.ics', fristen_ical_feed, name='fristen_ical_feed'),
    path('neu/pendenzen/neu/', fw_pendenz_neu, name='fw_pendenz_neu'),
    path('neu/pendenzen/<int:pk>/toggle/', fw_pendenz_toggle, name='fw_pendenz_toggle'),
    path('neu/pendenzen/<int:pk>/loeschen/', fw_pendenz_loeschen, name='fw_pendenz_loeschen'),
    path('neu/bewerbungen/', fw_bewerbungen, name='fw_bewerbungen'),
    path('neu/vermarktung/<int:einheit_id>/bewerber/', fw_bewerber_vergleich, name='fw_bewerber_vergleich'),
    path('neu/bewerbungen/<int:pk>/entscheid/', fw_bewerber_entscheid, name='fw_bewerber_entscheid'),
    path('neu/vermarktung/<int:einheit_id>/bewerber/absage-uebrige/', fw_bewerber_absage_uebrige, name='fw_bewerber_absage_uebrige'),
    path('neu/bewerbungen/<int:pk>/', fw_bewerbung_detail, name='fw_bewerbung_detail'),
    path('neu/bewerbungen/<int:pk>/status/', fw_bewerbung_status, name='fw_bewerbung_status'),
    path('neu/bewerbungen/<int:pk>/vertrag/', fw_bewerbung_zu_vertrag, name='fw_bewerbung_zu_vertrag'),
    path('neu/mietzins/', fw_mietzins, name='fw_mietzins'),
    path('neu/mietzins/<int:vertrag_id>/anpassung/', fw_mietzins_anpassung, name='fw_mietzins_anpassung'),
    path('neu/vertraege/<int:vertrag_id>/abnahme/neu/', fw_abnahme_neu, name='fw_abnahme_neu'),
    path('neu/abnahme/<int:pk>/', fw_abnahme_detail, name='fw_abnahme_detail'),
    path('neu/abnahme/<int:pk>/pdf/', fw_abnahme_pdf, name='fw_abnahme_pdf'),
    path('neu/dokumente/', fw_dokumente, name='fw_dokumente'),
    path('neu/dokumente/neu/', fw_dokument_neu, name='fw_dokument_neu'),
    # Profil-Menü
    path('neu/suche/', fw_suche, name='fw_suche'),
    path('neu/account/', fw_account, name='fw_account'),
    path('neu/marktdaten/aktualisieren/', fw_marktdaten_aktualisieren, name='fw_marktdaten_aktualisieren'),
    path('neu/marktdaten/live/', fw_marktdaten_live, name='fw_marktdaten_live'),
    path('neu/benutzer/', fw_benutzer, name='fw_benutzer'),
    path('neu/benutzer/neu/', fw_benutzer_form, name='fw_benutzer_neu'),
    path('neu/benutzer/<int:pk>/bearbeiten/', fw_benutzer_form, name='fw_benutzer_bearbeiten'),
    path('neu/benutzer/<int:pk>/loeschen/', fw_benutzer_loeschen, name='fw_benutzer_loeschen'),
    path('neu/logbuch/', fw_logbuch, name='fw_logbuch'),
    path('neu/rechtsgrundlagen/', fw_rechtsgrundlagen, name='fw_rechtsgrundlagen'),
    path('neu/mandate/', fw_mandate, name='fw_mandate'),
    path('neu/mandate/neu/', fw_mandat_form, name='fw_mandat_neu'),
    path('neu/mandate/<int:pk>/bearbeiten/', fw_mandat_form, name='fw_mandat_bearbeiten'),
    path('neu/mandate/<int:pk>/loeschen/', fw_mandat_loeschen, name='fw_mandat_loeschen'),
    path('neu/mandate/<int:pk>/abrechnung/', fw_mandat_abrechnung, name='fw_mandat_abrechnung'),
    path('neu/mandate/<int:pk>/kontokorrent/', fw_eigentuemer_kontokorrent, name='fw_eigentuemer_kontokorrent'),
    path('neu/mandate/<int:pk>/auszahlung/', fw_eigentuemer_auszahlung, name='fw_eigentuemer_auszahlung'),
    path('neu/mandate/<int:pk>/honorar/', fw_eigentuemer_honorar, name='fw_eigentuemer_honorar'),
    path('neu/mandate/<int:pk>/portal-zugang/', fw_mandant_portal_zugang, name='fw_mandant_portal_zugang'),
    path('neu/vorlagen/', fw_vorlagen, name='fw_vorlagen'),
    path('neu/vorlagen/standard/', fw_vorlagen_standard, name='fw_vorlagen_standard'),
    path('neu/vorlagen/neu/', fw_vorlage_form, name='fw_vorlage_neu'),
    path('neu/vorlagen/<int:pk>/bearbeiten/', fw_vorlage_form, name='fw_vorlage_bearbeiten'),
    path('neu/vorlagen/<int:pk>/loeschen/', fw_vorlage_loeschen, name='fw_vorlage_loeschen'),
    path('neu/integrationen/', fw_integrationen, name='fw_integrationen'),
    path('neu/integrationen/test-email/', fw_integration_test_email, name='fw_integration_test_email'),
    path('neu/integrationen/portal-token/', fw_integration_portal_token, name='fw_integration_portal_token'),
    path('neu/vermarktung/feed.json', fw_vermarktung_feed, name='fw_vermarktung_feed'),
    path('neu/abonnement/', fw_abonnemente, name='fw_abonnemente'),
    path('neu/kommunikation/', fw_kommunikation, name='fw_kommunikation'),
    path('neu/kommunikation/senden/', fw_kommunikation_senden, name='fw_kommunikation_senden'),
    path('neu/kommunikation/serienbrief/', fw_serienbrief_pdf, name='fw_serienbrief_pdf'),
    path('neu/mahnwesen/', fw_mahnwesen, name='fw_mahnwesen'),
    path('neu/mahnwesen/aging/', fw_debitoren_aging, name='fw_debitoren_aging'),
    path('neu/mahnwesen/erfassen/', fw_mahnung_erfassen, name='fw_mahnung_erfassen'),
    path('neu/mahnwesen/lauf/', fw_mahnlauf, name='fw_mahnlauf'),
    path('neu/bankkonten/', fw_bankkonten, name='fw_bankkonten'),
    path('neu/bankabgleich/', fw_bankabgleich, name='fw_bankabgleich'),
    path('neu/bankabgleich/verbuchen/', fw_bankabgleich_verbuchen, name='fw_bankabgleich_verbuchen'),
    path('neu/bankabgleich/camt-import/', fw_camt_import, name='fw_camt_import'),

    # --- DIE NEUE WEB-APP (SPA) ---
    path('app/', spa_master_view, name='spa_master'),

    # --- EIGENTÜMER-PORTAL (read-only, nur eigener Mandant) ---
    path('portal/', portal_view, name='portal'),
    path('portal/dokument/<int:pk>/', portal_dokument_download, name='portal_dokument_download'),
    path('portal/report/', portal_report_pdf, name='portal_report_pdf'),
    path('portal/steuerauszug/', portal_steuerauszug_pdf, name='portal_steuerauszug_pdf'),
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
    path('mieter/rechnung/<int:pk>/', mieter_rechnung_qr, name='mieter_rechnung_qr'),
    path('mieter/kontoauszug/', mieter_kontoauszug_pdf, name='mieter_kontoauszug_pdf'),
    path('mieter/kuendigung/', mieter_kuendigung, name='mieter_kuendigung'),
    path('mieter/kuendigung/<int:pk>/brief/', mieter_kuendigung_pdf, name='mieter_kuendigung_pdf'),

    # --- DOSSIER-SEITEN (Team-intern: alles zu einem Mieter/Objekt/Vertrag) ---
    path('dossier/mieter/<int:mieter_id>/', mieter_dossier, name='dossier_mieter'),
    path('dossier/liegenschaft/<int:liegenschaft_id>/', liegenschaft_dossier, name='dossier_liegenschaft'),
    path('dossier/vertrag/<int:vertrag_id>/', vertrag_dossier, name='dossier_vertrag'),

    # --- ADMIN-ZUGÄNGE & SYSTEM ---
    path('admin/update-marktdaten/', update_market_data_view, name='update_marktdaten'),
    path('admin/', admin.site.urls),

    # ==========================================
    # 🔌 DIE NEUE SCHNITTSTELLE FÜR VUE.JS
    # ==========================================
    path('api/', api.urls),

    # --- PROZESSE ---
    path('mietzins/<int:vertrag_id>/', mietzins_anpassung_view, name='mietzins_anpassung'),
    path('formular/amtlich/<int:vertrag_id>/', generiere_amtliches_formular, name='amtliches_formular'),

    # --- PDF & E-MAIL ---
    path('vertrag/<int:vertrag_id>/pdf/', generate_pdf_view, name='generate_pdf'),
    path('vertrag/<int:vertrag_id>/dokumente-zip/', generate_vertragspaket_zip, name='generate_vertragspaket_zip'),
    path('vertrag/<int:vertrag_id>/dokument/<slug:doc_type>/', generate_dokument_view, name='generate_dokument'),
    path('abrechnung/<int:periode_id>/pdf/', abrechnung_pdf_view, name='abrechnung_pdf'),
    path('abrechnung/<int:periode_id>/send-mail/', send_abrechnung_email_view, name='abrechnung_send_mail'),

    # --- MAHNUNGEN MIT KÜNDIGUNGSANDROHUNG (Art. 257d OR) ---
    path('vertrag/<int:vertrag_id>/mahnung/', generate_mahnung_pdf_view, name='generate_mahnung_pdf'),
    path('vertrag/<int:vertrag_id>/mahnung/mail/', send_mahnung_email_view, name='send_mahnung_mail'),

    # --- QR RECHNUNG ---
    path('vertrag/<int:vertrag_id>/qr/', qr_rechnung_pdf, name='generate_qr'),

    # --- DOCUSEAL ---
    path('vertrag/<int:vertrag_id>/senden/', send_via_docuseal, name='send_docuseal'),
    path('docuseal/webhook/', docuseal_webhook, name='docuseal_webhook'),

    # --- QR CODE SYSTEM (Aushang) ---
    path('report/<int:liegenschaft_id>/', public_ticket_view, name='public_report'),
    path('liegenschaft/<int:liegenschaft_id>/poster/', generate_hallway_poster, name='hallway_poster'),

    # --- ÖFFENTLICHES SCHADENSFORMULAR (NEU) ---
    path('schaden/melden/', public_schaden_melden_view, name='schaden_melden'),

    # --- ÖFFENTLICHES BEWERBUNGSFORMULAR ---
    path('bewerben/<int:einheit_id>/', public_application_view, name='public_bewerbung'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)