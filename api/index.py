import os
import sys
from urllib.parse import parse_qs

# Ensure root directory is on the path so app can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# WSGI Middleware to reliably map Vercel route rewrites to Flask
class VercelPathMiddleware:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        query = environ.get("QUERY_STRING", "")
        params = parse_qs(query)
        if "__path" in params:
            raw_path = params["__path"][0]
            environ["PATH_INFO"] = "/" + raw_path.lstrip("/")
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
