# swiss_immo/settings.py
from pathlib import Path
import os
from decimal import Decimal
from dotenv import load_dotenv

# ==========================================
# 1. BASIS & ENVIRONMENT LADEN
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent

# .env Datei laden
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(env_path)

# ==========================================
# 2. HELPER FUNKTIONEN (MÜSSEN OBEN STEHEN!)
# ==========================================

def badge_ticket_count(request):
    """Zählt ungelesene Tickets + neue Nachrichten für Sidebar-Badge (Backup-Admin)"""
    from tickets.models import SchadenMeldung, TicketNachricht

    try:
        # 1. Ungelesene Tickets
        cnt = SchadenMeldung.objects.filter(gelesen=False).count()

        # 2. Ungelesene Nachrichten (die nicht vom System sind)
        cnt += TicketNachricht.objects.filter(gelesen=False).exclude(typ='system').count()

        # Gib die Zahl zurück oder None (dann wird kein Badge angezeigt)
        return str(cnt) if cnt > 0 else None
    except:
        return None

# ==========================================
# 3. SICHERHEIT
# ==========================================

def _get_secret_key():
    """SECRET_KEY aus der Umgebung; sonst aus einer persistenten Datei
    (einmalig erzeugt). NIE ein hartkodierter unsicherer Key — der würde
    Sessions/Tokens fälschbar machen."""
    key = os.getenv('SECRET_KEY')
    if key:
        return key
    key_file = BASE_DIR / '.secret_key'
    from django.core.management.utils import get_random_secret_key
    try:
        if key_file.exists():
            saved = key_file.read_text().strip()
            if saved:
                return saved
        new_key = get_random_secret_key()
        key_file.write_text(new_key)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        return new_key
    except Exception:
        # Notfall: App soll starten (Warnung im Log), aber ohne festen Key
        return get_random_secret_key()


SECRET_KEY = _get_secret_key()
# Sicherer Default: Produktion (DEBUG=False). Zum lokalen Entwickeln DEBUG=True setzen.
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = ['www.immoswiss.app', 'swissimmo.pythonanywhere.com', '127.0.0.1', 'localhost']
# Weitere Hosts optional per Env (kommagetrennt), z.B. eigene Domain.
ALLOWED_HOSTS += [h.strip() for h in os.getenv('EXTRA_ALLOWED_HOSTS', '').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = ['https://*.pythonanywhere.com', 'https://www.immoswiss.app']
CSRF_TRUSTED_ORIGINS += [o.strip() for o in os.getenv('EXTRA_CSRF_ORIGINS', '').split(',') if o.strip()]

# Sagt Django, dass es HTTPS ist, wenn der Proxy (PythonAnywhere) das sagt.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Test-Modus erkennen (damit die HTTPS-Umleitung den Test-Client nicht bricht)
import sys as _sys
TESTING = ('test' in _sys.argv) or ('pytest' in _sys.argv[0] if _sys.argv else False)

# Nur für Testläufe: fester Schlüssel für verschlüsselte Felder (AHV-Nummer),
# damit Tests ohne .env laufen. In Betrieb kommt er ausschliesslich aus der
# Umgebung (IMAP_SCHLUESSEL) — dieser Wert schützt dort nichts und gilt nur,
# solange `manage.py test` läuft.
if TESTING:
    IMAP_SCHLUESSEL = os.getenv('IMAP_SCHLUESSEL') or 'EV9Cq9O_Bf3KXTtRNITG9iiMDSNs7KZen9YgQQmA29c='

# Verschlüsselungsschlüssel für AHV-Nummern und Postfach-Zugangsdaten: Ohne Angabe legt die Anwendung ihn selbst an
# (Datei `.geheimnis_schluessel` neben `.secret_key`, siehe core/services/geheimnis.py und docs/SCHLUESSEL.md).
# In Testläufen aus: Die Tests bringen ihren Schlüssel mit und prüfen auch den Fall «keiner».
GEHEIMNIS_AUTOSCHLUESSEL = os.getenv('GEHEIMNIS_AUTOSCHLUESSEL', 'True') == 'True' and not TESTING

# Zwei-Faktor-Pflicht nach Rolle (SICH-10, Etappe 2): Inhaber, Verwalter und
# Buchhaltung brauchen den zweiten Faktor, auch wenn die Verwaltung den Schalter
# nicht gesetzt hat. Im Betrieb an; in Testläufen und bei DEBUG (lokale
# Entwicklung, E2E) aus, damit Testkonten ohne Telefon arbeiten. Ausdrücklich
# übersteuerbar: ZWEIFAKTOR_ROLLENPFLICHT=True/False.
ZWEIFAKTOR_ROLLENPFLICHT = os.getenv(
    'ZWEIFAKTOR_ROLLENPFLICHT', str(not DEBUG and not TESTING)).strip().lower() in ('1', 'true', 'yes')

# Clickjacking-Schutz: SAMEORIGIN erlaubt der App, EIGENE Seiten zu framen
# (Cockpit-Modals laden /neu/-Seiten per iframe) — externes Framing bleibt
# blockiert. 'DENY' (Django-Default) würde auch die eigenen Popups leer lassen.
# Modul-Ebene, damit es in JEDER Umgebung gilt (auch DEBUG).
X_FRAME_OPTIONS = 'SAMEORIGIN'

# --- Produktions-Härtung (nur wenn DEBUG=False, damit lokale HTTP-Entwicklung läuft) ---
if not DEBUG and not TESTING:
    SESSION_COOKIE_SECURE = True          # Session-Cookie nur über HTTPS
    CSRF_COOKIE_SECURE = True             # CSRF-Cookie nur über HTTPS
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    # HSTS: Browser merkt sich HTTPS-Pflicht (1 Jahr). Per Env abschaltbar.
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # HTTP→HTTPS-Redirect (Standard an; hinter PythonAnywhere-Proxy via SSL-Header).
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True') == 'True'

# ==========================================
# 4. APPS
# ==========================================

INSTALLED_APPS = [
    # --- Deine Apps (NEUE SPA-ARCHITEKTUR) ---
    'benutzer',     # Benutzermodell (AUTH_USER_MODEL, siehe Etappe 3)
    'core',         # utils & views (Die Zentrale)
    'crm',          # Personendaten & Firmen
    'portfolio',    # Liegenschaften & Einheiten
    'rentals',      # Verträge & Leerstände
    'finance',      # Rechnungen & Buchhaltung
    'tickets',      # Schadensmeldungen
    'mietprozess',  # Bewerber- & Mietprozesse
    'faelle',       # Fallmaschine (Phase 4a)
    'stweg',        # Stockwerkeigentum: Wertquoten, Fonds, Abrechnung
    'abo',          # Abonnement, Funktionsfreigabe, Plattform-Rechnung

    # --- Standard Django ---
    # `django.contrib.admin` bleibt installiert, obwohl es keine Admin-Oberfläche mehr gibt: Die Tabelle
    # `django_admin_log` hat einen Fremdschlüssel auf den Benutzer. Ohne die App löschte der ORM beim Löschen
    # eines Kontos die Log-Zeilen nicht mit, und die Datenbank wiese das Löschen ab.
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # --- Tools ---
    'ckeditor',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # GANZ VORNE, direkt hinter der Sicherheits-Middleware: Passt das Schema
    # nicht zum Code, darf keine der folgenden Schichten mehr laufen —
    # Session und Authentifizierung lesen selbst aus der Datenbank und
    # scheiterten an genau derselben fehlenden Tabelle. Die Wartungsseite
    # braucht davon nichts (siehe docs/WARTUNGSSEITE.md).
    'core.wartung.WartungsMiddleware',
    # Vor allem, was Eingaben liest: PostgreSQL verträgt kein NUL-Byte.
    'core.middleware_nul.NulBytesMiddleware',
    # Antworten komprimiert ausliefern. Die Listenseiten bestehen fast nur aus
    # sich wiederholendem Markup (Tailwind-Klassen, je Zeile eine Karte fürs
    # Handy UND eine Tabellenzeile für den PC) — das lässt sich hervorragend
    # packen. Gemessen über alle 53 abrufbaren Seiten: 5.2 MB → 0.81 MB, bei
    # den grössten Seiten Faktor 13 (Debitoren 329 → 24 kB). Über Mobilfunk
    # ist das der grösste einzelne Hebel auf die Ladezeit.
    #
    # BREACH: Komprimierung neben einem Geheimnis in derselben Antwort ist nur
    # dann angreifbar, wenn das Geheimnis pro Antwort gleich bleibt. Django
    # maskiert den CSRF-Token seit 4.1 je Anfrage mit einem Zufallswert, genau
    # dagegen. Sonstige Geheimnisse stehen nicht im Seitenkörper.
    #
    # Komprimiert die Hosting-Schicht bereits, sieht sie hier ein gesetztes
    # Content-Encoding und reicht die Antwort unverändert durch — doppelt
    # gepackt wird nichts.
    'django.middleware.gzip.GZipMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # NACH der Authentifizierung, weil die Sprache am Benutzer haengt und den
    # erst diese Schicht kennt.
    #
    # Django empfiehlt Session -> Locale -> Common. Hier steht `Common` bereits
    # davor, und das bleibt so: Ein Umbau der Reihenfolge beruehrt die
    # Umleitungen (APPEND_SLASH) und die Wartungsschicht — Nebenwirkungen, die
    # in einer i18n-Etappe nichts zu suchen haben. Praktisch heisst es: Eine
    # Umleitung von `/neu` auf `/neu/` traegt noch keinen `Content-Language`.
    # Sichtbar ist das nirgends, denn umgeleitet wird ohne Inhalt.
    'django.middleware.locale.LocaleMiddleware',
    # Muss NACH AuthenticationMiddleware stehen — sie braucht `request.user`.
    # Und vor allem, was Mandantendaten liest: Ohne gesetzten Kontext wirft
    # der TenantManager, statt still den ganzen Bestand herauszugeben.
    'core.middleware_tenancy.OrganisationMiddleware',
    # Nach der Mandanten-Middleware: Sie braucht `request.user` (steht schon)
    # und darf erst greifen, wenn der Kontext gesetzt ist. Erzwingt die
    # Einrichtung des zweiten Faktors, wenn eine Verwaltung ihn verlangt.
    'core.middleware_zweifaktor.ZweiFaktorPflichtMiddleware',
    # Nach dem Mandantenkontext und der Anmeldung: Sie braucht beides. Sperrt
    # Module, die das Abonnement nicht enthält, und im Lesemodus (Zahlung lange
    # überfällig) jeden Schreibweg. Siehe abo/middleware.py.
    'abo.middleware.AboMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Nonce je Anfrage und Content-Security-Policy (zunächst nur melden, siehe core/csp.py).
    'core.csp.CspMiddleware',
    # Nach der Meldungs-Schicht (sie legt Meldungen ab, die der Rücksprung zeigt).
    # Macht aus Eingaben, die nicht in ihr Feld passen (zu lang, zu gross, keine
    # Zahl), eine Meldung statt einer 500-Seite — siehe core/middleware_eingabe.py.
    'core.middleware_eingabe.EingabeFehlerMiddleware',
    # Ganz innen, UNTER Common und GZip: Verbindet jedes `<label>` mit dem Feld daneben, damit ein
    # Screenreader «Jahr» liest statt «Auswahl» (DESIGN-27, siehe core/utils/feldnamen.py).
    'core.middleware_feldnamen.FeldnamenMiddleware',
]

ROOT_URLCONF = 'swiss_immo.urls'

# ==========================================
# 5. TEMPLATES
# ==========================================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.fw_badges',
                'core.navigation.fw_navigation',
                'abo.kontext.abo_hinweis',
                'core.csp.kontext',
            ],
        },
    },
]

WSGI_APPLICATION = 'swiss_immo.wsgi.application'

# Eigener Testläufer: führt jeden Test in einer Kopie des Kontexts aus, damit
# eine im Test gesetzte Organisation nicht in den nächsten Test überläuft.
# Begründung ausführlich in core/test_runner.py.
TEST_RUNNER = 'core.test_runner.MandantenTestRunner'

# ==========================================
# 6. DATENBANK
# ==========================================

# Standard: SQLite (kein Umbau nötig). Für Produktion/Skalierung PostgreSQL
# per Umgebungsvariablen aktivieren (DB_ENGINE=postgres + DB_NAME/USER/…).
# Der Treiber steht seit P0.5 in requirements.txt (psycopg[binary], Fassung 3 —
# die von Django 5.2 empfohlene). Vorher fehlte er: Wer DB_ENGINE=postgres
# setzte, bekam beim Start einen ImproperlyConfigured-Fehler (TS-13).
if os.getenv('DB_ENGINE', '').lower() in ('postgres', 'postgresql'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', ''),
            'USER': os.getenv('DB_USER', ''),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
            'CONN_MAX_AGE': 600,
            # Ohne diesen Schalter bricht die Website mit
            #   OperationalError: consuming input failed: SSL SYSCALL error: EOF detected
            # ab — gemessen am 18.08.2026, gleich nach dem Umzug, auf /neu/.
            #
            # Der Grund ist das Zusammenspiel mit der Zeile darüber:
            # `CONN_MAX_AGE = 600` hält die Verbindung über den Request hinaus
            # offen. Der PostgreSQL-Server (bzw. die Strecke dorthin) schliesst
            # eine untätige Verbindung aber früher. Django weiss davon nichts,
            # nimmt die tote Verbindung aus dem Bestand und schickt die erste
            # Abfrage des nächsten Requests hinein — hier die Sitzungsabfrage,
            # also noch bevor überhaupt ein View läuft.
            #
            # `CONN_HEALTH_CHECKS` (Django 4.1+) prüft die wiederverwendete
            # Verbindung zu Beginn jedes Requests mit einem billigen Ping und
            # baut sie bei Bedarf neu auf. Kosten: eine Rundreise pro Request.
            # Die Alternative wäre `CONN_MAX_AGE = 0` — dann aber ein voller
            # Verbindungsaufbau samt TLS-Handshake bei JEDEM Request.
            #
            # Auf SQLite stellte sich die Frage nie: dort ist die «Verbindung»
            # eine offene Datei. Der Fehler konnte deshalb erst nach dem Umzug
            # auftreten, und er tritt nur nach einer Pause auf — nicht sofort.
            'CONN_HEALTH_CHECKS': True,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            # SQLITE_NAME erlaubt eine separate DB-Datei (z.B. für E2E-Tests),
            # ohne die Entwickler-DB db.sqlite3 anzufassen.
            'NAME': os.getenv('SQLITE_NAME') or (BASE_DIR / 'db.sqlite3'),
            'OPTIONS': {
                # 30 s warten, statt sofort `database is locked` zu werfen.
                'timeout': 30,

                # WAL — der eigentliche Hebel für gleichzeitige Zugriffe.
                #
                # Im Standardmodus (`journal_mode=DELETE`) sperrt EIN Schreiber
                # die ganze Datei, auch für Leser. Mit WAL lesen beliebig viele
                # weiter, während einer schreibt. Bei einer Anwendung, in der
                # eine Verwaltung eine Liste öffnet, während eine andere eine
                # Rechnung bucht, ist das der Unterschied zwischen „läuft" und
                # `OperationalError: database is locked`.
                #
                # Was WAL NICHT ändert: Es bleibt bei genau EINEM Schreiber
                # gleichzeitig. SQLite trägt damit mehrere Mandanten mit
                # üblichem Aufkommen, aber keine parallelen Massenläufe (zwei
                # Sollstellungen zur selben Sekunde). Das ist die Grenze, an der
                # PostgreSQL (P1.4) nötig wird — nicht die Zahl der Mandanten.
                #
                # `synchronous=NORMAL` ist die zu WAL passende Einstellung:
                # dauerhaft sicher gegen Programmabstürze, ein Fenster von
                # Millisekunden nur bei Stromausfall des Servers.
                'init_command': (
                    'PRAGMA journal_mode=WAL;'
                    'PRAGMA synchronous=NORMAL;'
                ),

                # IMMEDIATE statt DEFERRED: Django öffnet Transaktionen sonst
                # lesend und will beim ersten Schreibzugriff hochstufen — genau
                # dann kollidieren zwei Anfragen und eine bekommt sofort
                # `database is locked`, OHNE dass `timeout` greift. Mit
                # IMMEDIATE wird die Schreibsperre gleich zu Beginn geholt und
                # das Warten funktioniert wie gedacht.
                'transaction_mode': 'IMMEDIATE',
            }
        }
    }

# ==========================================
# 7. SPRACHE, ZEIT & REDIRECTS
# ==========================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'de-ch'
TIME_ZONE = 'Europe/Zurich'
USE_I18N = True
USE_TZ = True

# --- MEHRSPRACHIGKEIT (E2) ---
# Die Schweiz hat vier Landessprachen, und eine Verwaltung in Freiburg oder
# Lugano schreibt an ihre Mieter nicht auf Deutsch. Die Projektanweisung
# verlangt DE/FR/IT/EN in Oberflaeche UND Dokumentvorlagen.
#
# STAND ZU BEGINN VON E2: Von 185 Vorlagen trug GENAU EINE `{% trans %}`.
# `USE_I18N` stand zwar auf True, aber ohne `LANGUAGES`, ohne `LOCALE_PATHS`
# und ohne Sprachordner — die Einstellung war eine Absichtserklaerung.
#
# WARUM DAS FUNDAMENT VOR DEM VORLAGENDURCHGANG KOMMT
# E2 stellt 135 Vorlagen auf die Komponentenschicht um. Wer dabei nicht
# gleichzeitig die Texte auszeichnet, fasst jede Datei zweimal an — und
# `docs/KONZEPT-UI.md` (13.1) hat genau deshalb entschieden, beides in EINEM
# Durchgang zu machen.
#
# NACHGEMESSEN AM 21.09.2026 — DER PLAN IST NICHT AUFGEGANGEN
# Die Farbhaelfte von E2 war zu diesem Zeitpunkt praktisch fertig, die
# Sprachhaelfte stand immer noch bei EINER Vorlage — und die eine war
# `admin/base.html` mit Djangos eigenem `{% translate 'Home' %}`, also nicht
# einmal eigener Text. «Beides in einem Durchgang» ist beim Durchgang selbst
# untergegangen; die Vorlagen sind jetzt umgestellt und muessen fuer die
# Sprache ein zweites Mal angefasst werden. Das ist der Preis, den dieser
# Absatz vermeiden wollte.
#
# E2.85 beginnt die Aufholung mit der Tranche «Heute» (`dashboard`, `zulauf`,
# `termine`, `abwesenheiten`): 100 Eintraege, DE/FR/IT/EN vollstaendig.
# Gemessen und bewacht von `core/tests/test_uebersetzung.py` — dort steht
# auch, warum die `.mo` im Repo liegen (`deploy.sh` ruft kein
# `compilemessages`) und was fuer eine neue Tranche zu tun ist.
#
# `makemessages`/`compilemessages` brauchen `gettext` (msgfmt/xgettext) auf
# dem Rechner. Fuer den BETRIEB genuegen die mitgelieferten `.mo`.
# ALLE VIER SPRACHEN WERDEN AUSGELIEFERT — entschieden am 23.09.2026
#
# E2.85 hat die ersten Kataloge angelegt und damit `LocaleMiddleware` zum
# ersten Mal wirksam gemacht; eingehaengt war sie laengst, nur hatte sie ohne
# Kataloge nichts zu tun. Im Browser gemessen:
#
#   Accept-Language: de-CH  ->  Aufgaben · Arbeitsvorrat
#   Accept-Language: en-US  ->  Tasks · Work queue
#   Accept-Language: fr-CH  ->  Tâches · Charge de travail
#
# Das heisst: Wer einen franzoesischen Browser hat, bekommt die bereits
# uebersetzten Teile auf Franzoesisch und den Rest weiter auf Deutsch. Der
# Anteil waechst mit jeder Tranche.
#
# Die Alternative waere gewesen, bis zum Ende des Durchgangs nur Deutsch
# auszuliefern. Bewusst verworfen: Der Fortschritt soll ankommen, sobald er
# da ist, statt monatelang im Repository zu liegen.
LANGUAGES = [
    ('de', 'Deutsch'),
    ('fr', 'Français'),
    ('it', 'Italiano'),
    ('en', 'English'),
]

# `de-ch` faellt in Django auf `de` zurueck, wenn kein eigener `de-ch`-Ordner
# existiert. Das ist gewollt: Schweizer Besonderheiten (Betrag mit
# Hochkomma, «ss» statt «ß») stecken in den Formatierungen und im Text
# selbst, nicht in einem zweiten Sprachordner.
LOCALE_PATHS = [os.path.join(BASE_DIR, 'locale')]

# --- BENUTZERMODELL ---
# Eigenes Benutzermodell statt `auth.User`. Der Wechsel ist nach Produktivgang
# praktisch nicht mehr möglich, deshalb steht er am Anfang der
# Mandantenfähigkeit — siehe docs/ETAPPE-3-USER-MODEL.md.
#
# Das Modell übernimmt die bestehende Tabelle `auth_user`; es wurde keine Zeile
# kopiert. Auf einer Bestandsdatenbank muss `manage.py benutzer_uebernahme`
# EINMAL vor `migrate` laufen — deploy.sh ruft das auf.
AUTH_USER_MODEL = 'benutzer.Benutzer'

# --- AUTHENTICATION ---
# Case-insensitive Login (Benutzername = E-Mail; Mobilgeräte gross-schreiben
# den ersten Buchstaben automatisch). Standard-Backend als Fallback.
AUTHENTICATION_BACKENDS = [
    'core.auth_backends.CaseInsensitiveModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# --- LOGIN / LOGOUT REDIRECTS ---
LOGIN_URL = '/login/'           # <-- Hierhin geht's, wenn man nicht eingeloggt ist
# Login-Weiche: Team-Rollen → /app/, Eigentümer-Logins → /portal/
LOGIN_REDIRECT_URL = '/nach-login/'
LOGOUT_REDIRECT_URL = '/'

# ==========================================
# 8. STATIC & MEDIA
# ==========================================

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

MEDIA_URL = '/media/'
# Ein Zähler für alle Prozesse (Login-Fehlversuche, Formular-Limits): siehe `core/cache_config.py`.
# Content-Security-Policy: report-only (Vorgabe) | enforce | aus — siehe core/csp.py
CSP_MODUS = os.getenv('CSP_MODUS', 'report-only')

from core.cache_config import caches_fuer  # noqa: E402
CACHES = caches_fuer(TESTING, BASE_DIR, os.getenv('CACHE_VERZEICHNIS') or None)

MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CKEDITOR_CONFIGS = {'default': {'toolbar': 'full', 'height': 300, 'width': '100%',}}

# ==========================================
# 9. EXTERNE DIENSTE & E-MAIL
# ==========================================

# GEMINI_API_KEY ist am 14.08.2026 entfallen (P0.5): Er wurde eingelesen und
# nirgends verwendet — die KI-Belegerkennung läuft über Groq. Eine tote
# Schlüssel-Variable ist nicht harmlos: Sie legt nahe, es gäbe eine
# Gemini-Anbindung, und lädt dazu ein, einen echten Schlüssel zu hinterlegen,
# der dann ohne Zweck in der Umgebung steht.
GROQ_API_KEY = os.getenv('GROQ_API_KEY')  # Für den KI-Rechnungs-Scanner (finance/utils.py)
# Modellnamen tauschbar, weil Groq Modelle abschaltet (leer = Standard in finance/utils.py)
GROQ_TEXT_MODEL = os.getenv('GROQ_TEXT_MODEL') or None
GROQ_VISION_MODEL = os.getenv('GROQ_VISION_MODEL') or None
DOCUSEAL_API_KEY = os.getenv('DOCUSEAL_API_KEY')
DOCUSEAL_URL = "https://api.docuseal.com"
# Optional: gemeinsames Secret für den DocuSeal-Webhook. Wenn gesetzt, muss
# DocuSeal denselben Wert als Header "X-Webhook-Secret" mitsenden.
DOCUSEAL_WEBHOOK_SECRET = os.getenv('DOCUSEAL_WEBHOOK_SECRET')
# Erlaubte Hosts für den PDF-Download im DocuSeal-Webhook (SSRF-Schutz).
DOCUSEAL_DOWNLOAD_HOSTS = {
    h.strip().lower() for h in os.getenv(
        'DOCUSEAL_DOWNLOAD_HOSTS', 'docuseal.com,api.docuseal.com,docuseal.eu'
    ).split(',') if h.strip()
}
# Optional: gemeinsames Secret für den Brevo-Inbound-Webhook (Query-Param ?token=
# oder Header "X-Webhook-Secret"). Wenn gesetzt, werden nur signierte Requests akzeptiert.
BREVO_WEBHOOK_SECRET = os.getenv('BREVO_WEBHOOK_SECRET')
# Domain der Antwortadressen (`<kennung>@<ANTWORT_DOMAIN>`, je Verwaltung). Die MX-Einträge dieser Domain
# zeigen auf Brevo Inbound Parsing; siehe docs/ANTWORTADRESSEN.md. Ohne BREVO_WEBHOOK_SECRET bleibt es beim
# bisherigen Reply-To (kein Versand an eine Adresse, die nichts empfängt).
ANTWORT_DOMAIN = (os.getenv('ANTWORT_DOMAIN') or 'immoswiss.app').strip().lower()
# API-Schluessel von Brevo, nur um die Anhaenge eingehender Rechnungsmails zu laden (Brevo liefert sie nicht
# im Webhook mit). Ohne ihn kommen Rechnungsmails an, aber ohne Anhang; das Logbuch der Verwaltung nennt es.
BREVO_API_KEY = os.getenv('BREVO_API_KEY')

# Plattform-Postfach (Variante A, kein neuer Anbieter): EIN Sammelpostfach beim Mailhoster, auf das der Hoster
# das Catch-all der ANTWORT_DOMAIN legt. `manage.py fetch_plattform_eingang` ruft es per IMAP ab und ordnet
# jede Mail ueber die Empfaengeradresse einer Verwaltung zu. Die Zugangsdaten stehen NUR hier (.env), nicht je
# Verwaltung in der Datenbank. Eingerichtet ist der Kanal erst, wenn Host, Benutzer und Passwort gesetzt sind.
# Siehe docs/ANTWORTADRESSEN.md.
PLATTFORM_IMAP_HOST = (os.getenv('PLATTFORM_IMAP_HOST') or '').strip()
PLATTFORM_IMAP_PORT = int(os.getenv('PLATTFORM_IMAP_PORT') or 993)
PLATTFORM_IMAP_BENUTZER = (os.getenv('PLATTFORM_IMAP_BENUTZER') or '').strip()
PLATTFORM_IMAP_PASSWORT = os.getenv('PLATTFORM_IMAP_PASSWORT') or ''
PLATTFORM_IMAP_ORDNER = (os.getenv('PLATTFORM_IMAP_ORDNER') or 'INBOX').strip() or 'INBOX'

# SMTP KONFIGURATION (HOSTSTAR) - BLEIBT AKTIV!
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'lx37.hoststar.hosting'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
# Ohne Timeout blockiert ein langsamer/nicht erreichbarer SMTP-Server den
# Arbeitsprozess UNBEGRENZT — und da mehrere Aktionen (Schaden melden,
# Bewerber-Entscheid, Portal-Zugang, Reparaturfreigabe) synchron im
# Request-Zyklus senden, hängt dann die ganze Seite, bis der Nutzer aufgibt
# und womöglich doppelt absendet. 15 s sind grosszügig für einen gesunden
# Server und begrenzen den Schaden, wenn er es nicht ist.
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '15'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = f'immoswiss <{os.getenv("EMAIL_HOST_USER", "info@immoswiss.app")}>'

# Basis-URL für Links in E-Mails (Portal-Login etc.) — unabhängig vom Request-Host,
# damit der Link auch aus Cron/Hintergrund-Jobs korrekt auf die Produktion zeigt.
PORTAL_BASE_URL = os.getenv('PORTAL_BASE_URL', 'https://swissimmo.pythonanywhere.com')

# ==========================================
# 9b. LOGGING (Fehler landen in Datei statt lautlos zu verschwinden)
# ==========================================
_LOG_DIR = BASE_DIR / 'logs'
try:
    _LOG_DIR.mkdir(exist_ok=True)
except Exception:
    _LOG_DIR = BASE_DIR
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'},
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(_LOG_DIR / 'swissimmo.log'),
            'maxBytes': 5 * 1024 * 1024, 'backupCount': 5,
            'formatter': 'standard', 'encoding': 'utf-8',
        },
    },
    'root': {'handlers': ['console', 'file'], 'level': 'INFO'},
    'loggers': {
        'django.request': {'handlers': ['console', 'file'], 'level': 'ERROR', 'propagate': False},
    },
}

# ==========================================
# 10b. ABONNEMENT UND PLATTFORM-RECHNUNG
# ==========================================
# Die Preise und Mengengrenzen der Stufen stehen in core/funktionen.py (eine Quelle, D7); Preisstand 29.09.2026, so auch
# auf https://immoswiss.app/preise.html. Vom Betreiber am 08.11.2026 freigegeben: Damit stellt der Abrechnungslauf
# (`manage.py abo_abrechnung`) Rechnungen aus — aber nur für Verwaltungen, deren «Abrechnung ab» gesetzt ist und erreicht
# wurde (Betreiber-Portal). Das Datum ist zugleich das Ende der Testphase: Bis dahin wird nichts in Rechnung gestellt.
ABO_PREISE_FESTGELEGT = True
# MWST auf Abo-Rechnungen: Der Betreiber ist NICHT mehrwertsteuerpflichtig (festgelegt am 09.11.2026). Rechnungen weisen
# deshalb keine MWST aus und sagen das. Wird er pflichtig: ABO_MWST_PFLICHTIG = True, ABO_MWST_SATZ = Decimal('8.1') (Normalsatz
# seit 1.1.2024) und die UID in ABO_STELLER_UID eintragen. Steht ABO_MWST_PFLICHTIG auf True und der Satz auf None, gilt die
# MWST als noch nicht entschieden (die Abo-Seite und die Rechnung weisen das aus).
ABO_MWST_PFLICHTIG = False
ABO_MWST_SATZ = None
# Abo-Rechnungen sind IM VORAUS zu bezahlen: Die Rechnung für eine Periode wird bis zu ABO_VORLAUF_TAGE Tage vor deren Beginn
# gestellt und ist am Periodenbeginn fällig (November: Rechnung Ende Oktober, fällig 1. November). Wird sie erst später
# gestellt (z. B. weil «Abrechnung ab» schon erreicht ist), gilt die Zahlungsfrist ABO_ZAHLUNGSFRIST_TAGE ab Rechnungsdatum.
# Beginn der Mahnung und des Lesemodus: Tage NACH Fälligkeit (Vorschlag aus docs/MARKT.md §7: Hinweis ab Tag 1, Lesemodus ab Tag 15).
ABO_VORLAUF_TAGE = 10
ABO_ZAHLUNGSFRIST_TAGE = 10
ABO_MAHNUNG_NACH_TAGEN = 1
ABO_LESEMODUS_NACH_TAGEN = 15
# Eskalation bei ausbleibender Zahlung, gemessen ab dem Fälligkeitstag der ältesten offenen Rechnung: 1. Mahnung nach
# ABO_MAHNUNG_NACH_TAGEN, 2. Mahnung (mit Mahngebühr) nach ABO_MAHNUNG2_NACH_TAGEN, Lesemodus nach ABO_LESEMODUS_NACH_TAGEN,
# gesperrter Zugang nach ABO_SPERRE_NACH_TAGEN. Auch im gesperrten Zugang bleiben Anmeldung, Abonnement (Rechnungen, PDF) und
# der Datenexport erreichbar; es wird nichts gelöscht. Mit dem Zahlungseingang ist alles wieder offen.
ABO_MAHNUNG2_NACH_TAGEN = 10
ABO_SPERRE_NACH_TAGEN = 45
# Mahngebühr der 2. Mahnung in CHF. 0 = keine Gebühr. Eine Gebühr ohne Grundlage im Vertrag (AGB) ist anfechtbar: erst
# festlegen, wenn die AGB sie nennen.
ABO_MAHNGEBUEHR = Decimal(os.getenv('ABO_MAHNGEBUEHR', '0') or '0')
# Rechnungssteller («Plattform») und Zahlungsempfänger der QR-Rechnung.
# Die Angaben kommen aus der .env (ABO_STELLER_NAME …), damit sie ohne Codeänderung gesetzt werden können; leer = ohne
# Name und IBAN lässt sich keine Rechnung mit Einzahlungsschein erzeugen (die Seite weist darauf hin).
ABO_RECHNUNGSSTELLER = {
    'name': os.getenv('ABO_STELLER_NAME', ''),
    'strasse': os.getenv('ABO_STELLER_STRASSE', ''),
    'plz': os.getenv('ABO_STELLER_PLZ', ''),
    'ort': os.getenv('ABO_STELLER_ORT', ''),
    'iban': os.getenv('ABO_STELLER_IBAN', ''),   # QR-IBAN (Institut 30000–31999) für die QR-Referenz, sonst IBAN
    'uid': os.getenv('ABO_STELLER_UID', ''),     # MWST-/UID-Nummer (CHE-…), falls mehrwertsteuerpflichtig
    'email': os.getenv('ABO_STELLER_EMAIL', ''), # Absender der Zahlungserinnerung
}

# Support: Anfragen der Verwaltungen (Knopf auf der Abo-Seite) gehen an diese Adresse und stehen im Verlauf der Kundenkartei.
# Leer = die Absenderadresse der Rechnungen (ABO_STELLER_EMAIL), sonst DEFAULT_FROM_EMAIL.
ABO_SUPPORT_EMAIL = os.getenv('ABO_SUPPORT_EMAIL', '')

# ==========================================
# 11. SYSTEM-CHECKS
# ==========================================
SILENCED_SYSTEM_CHECKS = ['ckeditor.W001']