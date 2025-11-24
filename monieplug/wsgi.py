"""
WSGI config for monieplug project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application
import dotenv
dotenv.load_dotenv()


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'monieplug.settings')

application = get_wsgi_application()
