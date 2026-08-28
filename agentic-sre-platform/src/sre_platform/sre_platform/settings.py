import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: never run with debug turned on in production!
DEBUG = 'True'  #os.environ.get('DJANGO_DEBUG', 'False') == 'True'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'fallback-dev-key-do-not-use-in-prod')

# Tell Django to trust the X-Forwarded-Proto header coming from AWS ALB
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Allow host matching for ALB DNS
ALLOWED_HOSTS = ['*']

# Optional security flags now that traffic is encrypted to the ALB
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Custom Apps
    'dashboard',
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

ROOT_URLCONF = 'sre_platform.urls'
WSGI_APPLICATION = 'sre_platform.wsgi.application'

# AWS RDS PostgreSQL Configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'sre_db'),
        'USER': os.environ.get('DB_USER', 'sre_admin'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'localdevpassword'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# AWS ElastiCache Redis Configuration
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"

# AWX Configurations

# sre_platform/settings.py

AWX_HOST = os.environ.get('AWX_BASE_URL', '')
AWX_TOKEN = os.environ.get('AWX_TOKEN', 'your-awx-personal-access-token')
AWX_VERIFY_SSL = os.environ.get('AWX_VERIFY_SSL', 'False').lower() in ('true', '1', 't')
AWX_DISK_CLEANUP_TEMPLATE_ID= os.environ.get('AWX_TEMPLATE_ID', '')

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')


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