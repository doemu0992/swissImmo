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
    # --- MODERNES DESIGN ---
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.import_export",

    # --- Deine Apps (NEUE ARCHITEKTUR) ---
    'core',         # utils & views
    'crm',          # Personendaten & Firmen
    'portfolio',    # Liegenschaften & Einheiten
    'rentals',      # Verträge & Leerstände
    'finance',      # Rechnungen & Buchhaltung
    'tickets',      # Schadensmeldungen

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
# 9. EXTERNE DIENSTE & E-MAIL
# ==========================================

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
DOCUSEAL_API_KEY = os.getenv('DOCUSEAL_API_KEY')
DOCUSEAL_URL = "https://api.docuseal.com"

# SMTP KONFIGURATION (HOSTSTAR)
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
    "SITE_URL": reverse_lazy("admin_dashboard"),
    "SITE_ICON": "real_estate_agent",

    # --- GLOBALER CLEAN-LOOK (RAHMENLOS) & INLINE-EDITING ---
    "STYLES": [
        lambda request: static("css/fairwalter_theme.css") + "?v=2",
        lambda request: static("css/custom_admin.css") + "?v=999",   # Der Cache-Zerstörer für CSS
    ],
    "SCRIPTS": [
        lambda request: static("js/section_toggle.js") + "?v=999",   # Der Cache-Zerstörer für JS
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
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Schreibtisch",
                "separator": True,
                "items": [
                    {"title": "Cockpit 🚀", "icon": "dashboard", "link": reverse_lazy("admin_dashboard")},
                    {
                        "title": "Tickets & Schäden",
                        "icon": "build",
                        "link": reverse_lazy("admin:tickets_schadenmeldung_changelist"),
                        "badge": badge_ticket_count,
                    },
                ],
            },
            {
                "title": "Portfolio & Vermietung",
                "separator": True,
                "items": [
                    {"title": "Liegenschaften", "icon": "domain", "link": reverse_lazy("admin:portfolio_liegenschaft_changelist")},
                    {"title": "Mietobjekte", "icon": "meeting_room", "link": reverse_lazy("admin:portfolio_einheit_changelist")},
                    {"title": "Mietverträge", "icon": "contract", "link": reverse_lazy("admin:rentals_mietvertrag_changelist")},
                    {"title": "Mietzinsanpassungen", "icon": "trending_up", "link": reverse_lazy("admin:rentals_mietzinsanpassung_changelist")},
                    {"title": "Leerstände", "icon": "key_off", "link": reverse_lazy("admin:rentals_leerstand_changelist")},
                ],
            },
            {
                "title": "CRM & Kontakte",
                "separator": True,
                "items": [
                    {"title": "Mieter", "icon": "groups", "link": reverse_lazy("admin:crm_mieter_changelist")},
                    {"title": "Handwerker", "icon": "engineering", "link": reverse_lazy("admin:crm_handwerker_changelist")},
                    {"title": "Mandanten (Eigentümer)", "icon": "business_center", "link": reverse_lazy("admin:crm_mandant_changelist")},
                ],
            },
            {
                "title": "Finanzen",
                "separator": True,
                "items": [
                    {"title": "Mieteinnahmen", "icon": "savings", "link": reverse_lazy("admin:finance_zahlungseingang_changelist")},
                    {"title": "Mietzins-Kontrolle", "icon": "fact_check", "link": reverse_lazy("admin:finance_mietzinskontrolle_changelist")},
                    {"title": "Kreditoren", "icon": "account_balance_wallet", "link": reverse_lazy("admin:finance_kreditorenrechnung_changelist")},
                    {"title": "Nebenkosten", "icon": "receipt_long", "link": reverse_lazy("admin:finance_abrechnungsperiode_changelist")},
                    {"title": "Erfolgsrechnung", "icon": "analytics", "link": reverse_lazy("admin:finance_jahresabschluss_changelist")},
                ],
            },
            {
                "title": "System",
                "separator": True,
                "items": [
                    {"title": "Kontenplan", "icon": "account_balance", "link": reverse_lazy("admin:finance_buchungskonto_changelist")},
                    {"title": "Eigene Verwaltung", "icon": "settings", "link": reverse_lazy("admin:crm_verwaltung_changelist")},
                    {"title": "Benutzer & Rechte", "icon": "lock", "link": reverse_lazy("admin:auth_user_changelist")},
                ],
            },
        ],
    },
}

# ==========================================
# 11. SYSTEM-CHECKS
# ==========================================
SILENCED_SYSTEM_CHECKS = ['ckeditor.W001']