import os
from django.core.wsgi import get_wsgi_application

# Points Gunicorn to your specific settings file
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sre_platform.settings')

# Exposes the WSGI application callable
application = get_wsgi_application()