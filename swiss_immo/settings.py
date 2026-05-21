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

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key')
DEBUG = os.getenv('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['www.immoswiss.app', 'swissimmo.pythonanywhere.com', '127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = ['https://*.pythonanywhere.com', 'https://www.immoswiss.app']

# Sagt Django, dass es HTTPS ist, wenn der Proxy (PythonAnywhere) das sagt.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

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
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
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
            ],
        },
    },
]

WSGI_APPLICATION = 'swiss_immo.wsgi.application'

# ==========================================
# 6. DATENBANK
# ==========================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 30,
        }
    }
}

# ==========================================
# 7. SPRACHE, ZEIT & REDIRECTS
# ==========================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

LANGUAGE_CODE = 'de-ch'
TIME_ZONE = 'Europe/Zurich'
USE_I18N = True
USE_TZ = True

# --- LOGIN / LOGOUT REDIRECTS FÜR SPA ---
LOGIN_URL = '/login/'           # <-- NEU: Hierhin geht's, wenn man nicht eingeloggt ist
LOGIN_REDIRECT_URL = '/app/'
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

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
DOCUSEAL_API_KEY = os.getenv('DOCUSEAL_API_KEY')
DOCUSEAL_URL = "https://api.docuseal.com"

# SMTP KONFIGURATION (HOSTSTAR) - BLEIBT AKTIV!
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'lx37.hoststar.hosting'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = f'ImmoSwiss Verwaltung <{os.getenv("EMAIL_HOST_USER", "info@immoswiss.app")}>'

# ==========================================
# 10. MODERNES DESIGN KONFIGURATION (UNFOLD)
# ==========================================

UNFOLD = {
    "SITE_TITLE": "SwissImmo Verwaltung",
    "SITE_HEADER": "SwissImmo",
    "SITE_URL": reverse_lazy("spa_master"), # Leitet Logo-Klick direkt in die App
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
                    {"title": "Zurück zur App 🚀", "icon": "dashboard", "link": reverse_lazy("spa_master")},
                ],
            },
        ],
    },
}

# ==========================================
# 11. SYSTEM-CHECKS
# ==========================================
SILENCED_SYSTEM_CHECKS = ['ckeditor.W001']