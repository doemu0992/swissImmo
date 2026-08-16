# swiss_immo/settings.py
from pathlib import Path
import os
from dotenv import load_dotenv
from django.templatetags.static import static
# WICHTIG: Lazy Import für Reverse URLs, damit Settings nicht crashen
from django.urls import reverse_lazy

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
    # --- MODERNES DESIGN (Für Fallback-Admin) ---
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.import_export",

    # --- Deine Apps (NEUE SPA-ARCHITEKTUR) ---
    'benutzer',     # Benutzermodell (AUTH_USER_MODEL, siehe Etappe 3)
    'core',         # utils & views (Die Zentrale)
    'crm',          # Personendaten & Firmen
    'portfolio',    # Liegenschaften & Einheiten
    'rentals',      # Verträge & Leerstände
    'finance',      # Rechnungen & Buchhaltung
    'tickets',      # Schadensmeldungen
    'mietprozess',  # Bewerber- & Mietprozesse

    # --- Standard Django ---
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
    # Muss NACH AuthenticationMiddleware stehen — sie braucht `request.user`.
    # Und vor allem, was Mandantendaten liest: Ohne gesetzten Kontext wirft
    # der TenantManager, statt still den ganzen Bestand herauszugeben.
    'core.middleware_tenancy.OrganisationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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
            ],
        },
    },
]

WSGI_APPLICATION = 'swiss_immo.wsgi.application'

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
DEFAULT_FROM_EMAIL = f'ImmoSwiss Verwaltung <{os.getenv("EMAIL_HOST_USER", "info@immoswiss.app")}>'

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
# 10. MODERNES DESIGN KONFIGURATION (UNFOLD)
# ==========================================

UNFOLD = {
    "SITE_TITLE": "SwissImmo Verwaltung",
    "SITE_HEADER": "SwissImmo",
    "SITE_URL": reverse_lazy("fw_dashboard"), # Logo-Klick fuehrt in die aktive Oberflaeche /neu/
    "SITE_ICON": "real_estate_agent",

    # --- GLOBALER CLEAN-LOOK (RAHMENLOS) & INLINE-EDITING ---
    "STYLES": [
        lambda request: static("css/fairwalter_theme.css") + "?v=2",
        lambda request: static("css/custom_admin.css") + "?v=999",
    ],
    "SCRIPTS": [
        lambda request: static("js/section_toggle.js") + "?v=999",
    ],

    "COLORS": {
        "primary": {
            "50": "239 246 255",
            "100": "219 234 254",
            "200": "191 219 254",
            "300": "147 197 253",
            "400": "96 165 250",
            "500": "59 130 246",
            "600": "37 99 235",
            "700": "29 78 216",
            "800": "30 64 175",
            "900": "30 58 138",
        },
    },

    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True, # Erlaubt Zugriff auf alle Daten im Notfall
        "navigation": [
            {
                "title": "Hauptsystem",
                "separator": True,
                "items": [
                    {"title": "Zur Verwaltung 🚀", "icon": "dashboard", "link": reverse_lazy("fw_dashboard")},
                ],
            },
        ],
    },
}

# ==========================================
# 11. SYSTEM-CHECKS
# ==========================================
SILENCED_SYSTEM_CHECKS = ['ckeditor.W001']