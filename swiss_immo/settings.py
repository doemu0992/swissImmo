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
    """Zählt ungelesene Tickets + neue Nachrichten für Sidebar-Badge"""
    # Import INNERHALB der Funktion, um Zirkelbezüge beim Start zu vermeiden
    from core.models import SchadenMeldung, TicketNachricht

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

# ==========================================
# 4. APPS
# ==========================================

INSTALLED_APPS = [
    # --- MODERNES DESIGN ---
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.import_export",

    # --- Deine App ---
    'core',

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
    }
}

# ==========================================
# 7. SPRACHE & ZEIT
# ==========================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

LANGUAGE_CODE = 'de-ch'
TIME_ZONE = 'Europe/Zurich'
USE_I18N = True
USE_TZ = True

# ==========================================
# 8. STATIC & MEDIA
# ==========================================

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CKEDITOR_CONFIGS = {'default': {'toolbar': 'full', 'height': 300, 'width': '100%',},}

# ==========================================
# 9. EXTERNE DIENSTE & E-MAIL (HOSTSTAR)
# ==========================================

DOCUSEAL_API_KEY = os.getenv('DOCUSEAL_API_KEY')
DOCUSEAL_URL = "https://api.docuseal.com"

# --- SMTP KONFIGURATION (HOSTSTAR) ---
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'lx37.hoststar.hosting'       # Hoststar Server
EMAIL_PORT = 587                      # TLS Port
EMAIL_USE_TLS = True                  # Verschlüsselung aktivieren
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')      # Lädt info@immoswiss.app aus .env
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD') # Lädt Passwort aus .env

# Standard Absender
DEFAULT_FROM_EMAIL = f'ImmoSwiss Verwaltung <{os.getenv("EMAIL_HOST_USER", "info@immoswiss.app")}>'

# ==========================================
# 10. MODERNES DESIGN KONFIGURATION (UNFOLD)
# ==========================================

UNFOLD = {
    "SITE_TITLE": "SwissImmo Verwaltung",
    "SITE_HEADER": "SwissImmo",
    "SITE_URL": "/admin/dashboard/",

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
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Übersicht",
                "separator": True,
                "items": [
                    {"title": "Cockpit 🚀", "icon": "dashboard", "link": "/admin/dashboard/"},
                ],
            },
            {
                "title": "Verwaltung",
                "separator": True,
                "items": [
                    {"title": "Liegenschaften", "icon": "domain", "link": "/admin/core/liegenschaft/"},
                    {"title": "Einheiten", "icon": "meeting_room", "link": "/admin/core/einheit/"},
                    {"title": "Mieter", "icon": "people", "link": "/admin/core/mieter/"},
                    {"title": "Verträge", "icon": "description", "link": "/admin/core/mietvertrag/"},
                ],
            },
            {
                "title": "Finanzen & Service",
                "separator": True,
                "items": [
                    {"title": "Nebenkosten", "icon": "receipt_long", "link": "/admin/core/abrechnungsperiode/"},

                    # Hier verwenden wir die Funktion, die OBEN definiert wurde!
                    {
                        "title": "Tickets & Schäden",
                        "icon": "build",
                        "link": "/admin/core/schadenmeldung/",
                        "badge": badge_ticket_count,
                    },

                    {"title": "Handwerker", "icon": "engineering", "link": "/admin/core/handwerker/"},
                ],
            },
            {
                "title": "System",
                "separator": True,
                "items": [
                    {"title": "Einstellungen (Verwaltung)", "icon": "settings", "link": "/admin/core/verwaltung/"},
                    {"title": "Mandanten", "icon": "admin_panel_settings", "link": "/admin/core/mandant/"},
                    {"title": "Benutzer & Rechte", "icon": "lock", "link": "/admin/auth/user/"},
                ],
            },
        ],
    },
}

# ==========================================
# 11. SYSTEM-CHECKS
# ==========================================
SILENCED_SYSTEM_CHECKS = ['ckeditor.W001']