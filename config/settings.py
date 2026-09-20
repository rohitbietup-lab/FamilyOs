"""Fail-closed deployment defaults; opt into loopback development explicitly."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEVELOPMENT = os.environ.get('FAMILYOS_ENV') == 'development'
SECRET_KEY = os.environ.get('FAMILYOS_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEVELOPMENT:
        raise ImproperlyConfigured('Set FAMILYOS_SECRET_KEY before starting FamilyOS.')
    SECRET_KEY = 'development-only-not-for-deployment-familyos-local-key'
if not DEVELOPMENT and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('FAMILYOS_SECRET_KEY must contain at least 50 random characters.')
DEBUG = False
ALLOWED_HOSTS = [v.strip() for v in os.environ.get(
    'FAMILYOS_ALLOWED_HOSTS', 'localhost,127.0.0.1' if DEVELOPMENT else ''
).split(',') if v.strip()]
if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('Set explicit FAMILYOS_ALLOWED_HOSTS.')
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.environ.get(
    'FAMILYOS_CSRF_TRUSTED_ORIGINS', ''
).split(',') if v.strip()]
INSTALLED_APPS = [
    'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles', 'core',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.PrivateAccessMiddleware',
]
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
data_dir = Path(os.environ.get('FAMILYOS_DATA_DIR', str(BASE_DIR / 'instance'))).resolve()
data_dir.mkdir(parents=True, exist_ok=True)
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3', 'NAME': data_dir / 'familyos.sqlite3',
    'OPTIONS': {'timeout': 20, 'transaction_mode': 'IMMEDIATE'},
}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
PASSWORD_HASHERS = ['django.contrib.auth.hashers.PBKDF2PasswordHasher']
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
WHITENOISE_USE_FINDERS = DEVELOPMENT
LOGIN_URL = '/login/'
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = 'familyos_session'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEVELOPMENT
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = False
SESSION_IDLE_SECONDS = 30 * 60
CSRF_COOKIE_SECURE = not DEVELOPMENT
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_SSL_REDIRECT = not DEVELOPMENT
SECURE_HSTS_SECONDS = 31536000 if not DEVELOPMENT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEVELOPMENT
SECURE_HSTS_PRELOAD = not DEVELOPMENT
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 32 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 20
