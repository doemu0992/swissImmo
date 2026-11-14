# swiss_immo/urls.py
from django.urls import path, include
from django.conf import settings
from django.contrib.auth import views as auth_views  # <-- Import für den Login

# ========================================================
# 🚀 API SETUP (DJANGO NINJA)
# ========================================================
from ninja import NinjaAPI
from core.auth import auth_lesen
# Seit E1c gibt es nur noch zwei Endpunkte, beide öffentlich (auth=None):
#   POST /api/mietprozess/public/bewerben   → Bewerbungsformular
#   POST /api/rentals/webhook/docuseal      → DocuSeal-Rücklauf
# Die 80 übrigen bedienten die in E1b entfernte Vue-Oberfläche und sind weg,
# mitsamt den Routern portfolio, crm, tickets und finance.
from rentals.api import router as rentals_router
from mietprozess.api import router as mietprozess_router
from core.finanz_api import router as finanz_router

# `auth=auth_lesen` bleibt als Standard stehen — nicht weil noch etwas darauf
# angewiesen wäre, sondern als Sicherung: Käme je ein Endpunkt dazu, ohne dass
# jemand an die Berechtigung denkt, wäre er session-pflichtig statt offen.
# `docs_url=None` schaltet /api/docs ab: Zwei öffentliche Endpunkte brauchen
# keinen Schema-Browser, und was es nicht gibt, muss nicht abgesichert werden
# (vorher hing die Seite an staff_member_required). `openapi_url=None` schaltet
# auch /api/openapi.json ab — das Schema war bis zum Security-Audit anonym
# abrufbar und beschrieb jedes Feld des Bewerbungsformulars samt Uploads.
api = NinjaAPI(
    title="immoswiss API",
    version="2.0.0",
    description="Öffentliche Endpunkte (Bewerbungsformular, DocuSeal-Webhook) und die lesende Finanz-API unter /v1 mit API-Schlüssel.",
    auth=auth_lesen,
    docs_url=None,
    openapi_url=None,
)

api.add_router("/rentals", rentals_router)
api.add_router("/mietprozess", mietprozess_router)
api.add_router("/v1", finanz_router)


# ========================================================
# VIEWS IMPORTE (Klassisches Django / Legacy)
# ========================================================
# 1. Landing Page & Public Tickets
from core.views.ticket_public import public_ticket_view, generate_hallway_poster, index_view, public_schaden_melden_view
from django.http import JsonResponse


def version_view(request):
    """Öffentlicher Deploy-Check: JSON mit Commit/Branch des laufenden Prozesses."""
    from core.version import deployed_version
    return JsonResponse(deployed_version())


def healthz_view(request):
    """Liveness/Readiness-Check für Uptime-Monitoring (UptimeRobot o. ä.).

    Prüft, was tatsächlich ausfällt: die Datenbankverbindung (ein simples
    SELECT 1). `/version/` sagt nur, welcher Commit läuft — nicht, ob die App
    noch bedienbar ist. 200 = gesund, 503 = DB nicht erreichbar. Bewusst ohne
    interne Details (kein Stacktrace, keine Query nach aussen)."""
    from django.db import connection
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
    return JsonResponse({'status': 'ok'})
from core.views.application import public_application_view, public_datenschutz_view
from core.csp import csp_bericht

# 2. Das neue Admin-Cockpit (Bereinigt um das alte Dashboard)

# 2b. Eigentümer-Portal & Login-Weiche
from core.views.passwort_reset import PasswortVergessenView
from core.views.zweifaktor import (zweifaktor_login, zweifaktor_bestaetigen,
                                  zweifaktor_uebersicht, zweifaktor_einrichten,
                                  zweifaktor_codes_neu, zweifaktor_aus,
                                  zweifaktor_pflicht_setzen)
from core.views.portal import nach_login_view
# Modul 3 (27.10.2026): Handwerkerportal (Magic-Link je Auftrag) und Link-Verwaltung im Schaden

# Abonnement: Rechnung als PDF mit QR-Einzahlungsschein (Funktionsfreigabe, Etappe 4)

# 2c. Fairwalter-Rebuild: neue Oberfläche (Etappe A: Shell + Dashboard)

# Modul 4 (27.10.2026): Bewerber-Board
# Modul 2 (27.10.2026): Schlüssel und Schliessanlage

import core.views.alte_adressen as _alt  # noqa: E402  Weiterleitungen entfallener Seiten

# 3. Verträge & Mietzins
from core.views.contracts import mietzins_anpassung_view, generiere_amtliches_formular

# Modul 5 (27.10.2026): Dokumenten-Automatisierung — Editor, Vorschau, Regeln, Fassungen

# 4. PDF (Mietvertrag + Begleitdokumente)
from core.views.pdf import generate_pdf_view, generate_dokument_view, generate_vertragspaket_zip

# 5. DocuSeal
from core.views.docuseal import send_via_docuseal, docuseal_webhook
from core.views.webhooks import brevo_inbound_webhook

# 6. Abrechnung, QR, Finanzen & Mahnungen
from core.views.billing import abrechnung_pdf_view, qr_rechnung_pdf
from core.views.email_views import send_abrechnung_email_view, send_mahnung_email_view, generate_mahnung_pdf_view

# 6b. Nebenkosten-Wizard (Modul 1, 27.10.2026) — sechs Schritte unter /neu/nebenkosten/<pk>/
from swiss_immo import (urls_neu_bestand, urls_betreiber, urls_neu_betrieb, urls_neu_mietprozess, urls_neu_verwaltung, urls_portale)

urlpatterns = [
    # --- STARTSEITE ---
    path('', index_view, name='index'),

    # --- DEPLOY-CHECK (öffentlich, ohne Login): zeigt den Commit des WIRKLICH
    #     laufenden Prozesses → belegt, ob der Auto-Deploy (pull + reload) griff.
    path('version/', version_view, name='version'),

    # --- HEALTHCHECK (öffentlich, ohne Login): prüft die DB-Verbindung für
    #     externes Uptime-Monitoring. 200 = gesund, 503 = DB weg.
    path('healthz/', healthz_view, name='healthz'),

    # --- EIGENER SAAS LOGIN ---
    # Eigene Anmeldung statt `auth_views.LoginView`: Sie meldet erst an,
    # wenn ein ausstehender zweiter Faktor bestaetigt ist. Ein Faktor, der
    # NACH `login()` abgefragt wird, ist keiner — siehe core/views/zweifaktor.py.
    path('login/', zweifaktor_login, name='login'),
    # Verstossmeldungen der Content-Security-Policy (offen, gedeckelt): siehe core/csp.py
    path('csp-bericht/', csp_bericht, name='csp_bericht'),
    # Sprachwahl (Baustein `core/_sprachwahl.html`): Djangos `set_language`,
    # nur POST, setzt das Sprach-Cookie. Offen ohne Anmeldung, damit auch die
    # Anmeldeseite umgestellt werden kann; `next` prüft Django selbst auf
    # eigene Adressen (kein offener Redirect).
    path('i18n/', include('django.conf.urls.i18n')),
    # Passwort vergessen (Self-Service für Mieter/Eigentümer-Logins): Djangos
    # eingebaute Reset-Kette mit eigenen, schlanken Templates.
    path('passwort/vergessen/', PasswortVergessenView.as_view(
        template_name='core/passwort_reset.html',
        email_template_name='core/passwort_reset_email.txt',
        subject_template_name='core/passwort_reset_subject.txt'), name='password_reset'),
    path('passwort/gesendet/', auth_views.PasswordResetDoneView.as_view(
        template_name='core/passwort_reset_done.html'), name='password_reset_done'),
    path('passwort/neu/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='core/passwort_reset_confirm.html'), name='password_reset_confirm'),
    path('passwort/fertig/', auth_views.PasswordResetCompleteView.as_view(
        template_name='core/passwort_reset_complete.html'), name='password_reset_complete'),
    # Eigene Login-Seite für Mieter- und Eigentümer-Portal (gleiche Auth, eigenes Design)
    path('portal/login/',
         lambda r: zweifaktor_login(r, template_name='core/portal_login.html'),
         name='portal_login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('nach-login/', nach_login_view, name='nach_login'),
    path('anmeldung/bestaetigen/', zweifaktor_bestaetigen, name='zweifaktor_bestaetigen'),
    path('konto/zwei-faktor/', zweifaktor_uebersicht, name='zweifaktor_uebersicht'),
    path('konto/zwei-faktor/einrichten/', zweifaktor_einrichten, name='zweifaktor_einrichten'),
    path('konto/zwei-faktor/codes/', zweifaktor_codes_neu, name='zweifaktor_codes_neu'),
    path('konto/zwei-faktor/aus/', zweifaktor_aus, name='zweifaktor_aus'),
    path('konto/zwei-faktor/pflicht/', zweifaktor_pflicht_setzen, name='zweifaktor_pflicht_setzen'),

    # --- Bestand, Personen, Verträge und Kreditoren unter /neu/ (Liegenschaften, Objekte, Personen, Verträge, Schlüssel, Staffeln, MWST).
    *urls_neu_bestand.urlpatterns,


    # --- Betreiber-Konsole unter /betreiber/ (Kunden, Abo, CSP, LIK-Werte, Sicherheit).
    *urls_betreiber.urlpatterns,


    # --- Betrieb unter /neu/: Einstellungen, Schäden, Nebenkosten, Fälle, Läufe, Termine, Anfragen, Aufträge.
    *urls_neu_betrieb.urlpatterns,


    # --- Mietprozess unter /neu/: Bewerbungen, Vermarktung, Mietzins, Anpassungen.
    *urls_neu_mietprozess.urlpatterns,


    # --- Verwaltung unter /neu/: Abnahme, Dokumente, Mandate, Vorlagen, Mahnwesen, Bankabgleich, Benutzer.
    *urls_neu_verwaltung.urlpatterns,


    # --- Portale und Token-Zugänge: Eigentümer, Mieter, Handwerker (Auftrag, Direktkanal).
    *urls_portale.urlpatterns,


    # --- ALTE DOSSIER-ADRESSEN (Etappe 3: die Seiten sind entfallen) ---
    # Lesezeichen und alte Mails landen in der Akte; dort gilt die Rollen- und
    # Mandantenpruefung. Die Zieladresse wird nicht geprueft: Eine fremde Nummer
    # ergibt in der Akte 404, nicht hier.
    path('dossier/mieter/<int:pk>/', _alt.dossier_mieter),
    path('dossier/liegenschaft/<int:pk>/', _alt.dossier_liegenschaft),
    path('dossier/vertrag/<int:pk>/', _alt.dossier_vertrag),

    # --- ADMIN-ZUGÄNGE & SYSTEM ---
    # Die alte Django-Admin gibt es nicht mehr: Sie war ein zweiter Passwort-Login ohne zweiten Faktor.
    # Alles läuft über /neu/ (Anmeldung: `login`).

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
    # Eingehende Mail-Antworten auf Schadenmeldungen. Die View gab es seit
    # Langem, sie war aber in KEINER URL-Zeile eingetragen — Antworten
    # landeten nirgends (Audit 18.08.2026). Scharfgeschaltet am 18.08.2026.
    #
    # Ohne gesetztes BREVO_WEBHOOK_SECRET weist die View JEDEN Aufruf mit
    # 403 ab — sie ist damit auch offen erreichbar nicht missbrauchbar.
    path('webhooks/brevo/inbound/', brevo_inbound_webhook,
         name='brevo_inbound_webhook'),

    # --- QR CODE SYSTEM (Aushang) ---
    path('report/<int:liegenschaft_id>/', public_ticket_view, name='public_report'),
    path('liegenschaft/<int:liegenschaft_id>/poster/', generate_hallway_poster, name='hallway_poster'),

    # --- ÖFFENTLICHES SCHADENSFORMULAR (NEU) ---
    path('schaden/melden/', public_schaden_melden_view, name='schaden_melden'),

    # --- ÖFFENTLICHES BEWERBUNGSFORMULAR ---
    path('bewerben/<int:einheit_id>/', public_application_view, name='public_bewerbung'),

    # --- DATENSCHUTZERKLÄRUNG (öffentlich, Art. 19 revDSG) ---
    path('datenschutz/', public_datenschutz_view, name='public_datenschutz'),
    # Mit Objektbezug: Die Erklaerung nennt den Verantwortlichen, und der ist je
    # Verwaltung ein anderer. Das Bewerbungsformular verlinkt diese Fassung.
    path('bewerben/<int:einheit_id>/datenschutz/', public_datenschutz_view,
         name='public_datenschutz_objekt'),
]

# Media zugriffskontrolliert ausliefern: sensible Dokumente (Verträge, Bewerber-
# Ausweise/Lohn/Betreibung, Belege) nur für eingeloggte Team-Mitglieder; öffentliche
# Objektfotos/Logos frei. Ersetzt das frühere ungeschützte static(MEDIA_URL).
from django.urls import re_path
from core.views.media_protected import geschuetzte_media
_media = settings.MEDIA_URL.lstrip('/')
urlpatterns += [re_path(rf'^{_media}(?P<pfad>.*)$', geschuetzte_media, name='geschuetzte_media')]