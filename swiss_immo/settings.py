from pathlib import Path
import os
from dotenv import load_dotenv

# ==========================================
# 1. BASIS & ENVIRONMENT LADEN
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent

# .env Datei laden
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(env_path)

# ==========================================
# 2. SICHERHEIT
# ==========================================

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key')
DEBUG = os.getenv('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['swissimmo.pythonanywhere.com', '127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = ['https://*.pythonanywhere.com']

# ==========================================
# 3. APPS
# ==========================================

INSTALLED_APPS = [
    'core',  # Muss oben stehen
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
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
# 4. TEMPLATES (HIER WAR DER FEHLER)
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
                # --- DIESE ZEILE HAT GEFEHLT FÜR DEN STAMMBAUM ---
                'core.context_processors.admin_baum_navigation',
            ],
        },
    },
]

WSGI_APPLICATION = 'swiss_immo.wsgi.application'

# ==========================================
# 5. DATENBANK
# ==========================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ==========================================
# 6. SPRACHE & ZEIT
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
# 7. STATIC & MEDIA
# ==========================================

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CKEDITOR_CONFIGS = {'default': {'toolbar': 'full', 'height': 300, 'width': '100%',},}

# ==========================================
# 8. EXTERNE DIENSTE (API KEYS)
# ==========================================

# DOCUSEAL
DOCUSEAL_API_KEY = os.getenv('DOCUSEAL_API_KEY')
DOCUSEAL_URL = "https://api.docuseal.com"

# E-MAIL (BREVO)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp-relay.brevo.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL')