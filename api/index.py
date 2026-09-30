import os
import sys
from urllib.parse import parse_qs, urlparse

# Ensure root directory is on the path so app can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# WSGI Middleware to reliably map Vercel route rewrites to Flask
class VercelPathMiddleware:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        original_url = None

        # 1. Check HTTP_X_NOW_ROUTE_MATCHES (e.g. "1=report" or "1=login")
        if "HTTP_X_NOW_ROUTE_MATCHES" in environ:
            matches = parse_qs(environ["HTTP_X_NOW_ROUTE_MATCHES"])
            if "1" in matches and matches["1"][0]:
                original_url = "/" + matches["1"][0].lstrip("/")
            elif "0" in matches and matches["0"][0]:
                original_url = "/" + matches["0"][0].lstrip("/")

        # 2. Check query string __path
        if not original_url:
            query = environ.get("QUERY_STRING", "")
            params = parse_qs(query)
            if "__path" in params and params["__path"][0]:
                original_url = "/" + params["__path"][0].lstrip("/")

        # 3. Check X-Forwarded-Uri / Request-Uri / Vercel headers
        if not original_url:
            for header in ["HTTP_X_FORWARDED_URI", "REQUEST_URI", "RAW_URI", "HTTP_X_VERCEL_PATH"]:
                if header in environ and environ[header]:
                    path = urlparse(environ[header]).path
                    if path and path not in ("/api/index", "/api", "/api/"):
                        original_url = path
                        break

        if original_url:
            environ["PATH_INFO"] = original_url

        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
