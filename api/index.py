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
        if "__path" in params and params["__path"][0]:
            environ["PATH_INFO"] = "/" + params["__path"][0].lstrip("/")
        elif environ.get("HTTP_X_MATCHED_PATH"):
            environ["PATH_INFO"] = environ["HTTP_X_MATCHED_PATH"]
        elif environ.get("HTTP_X_NOW_ROUTE_MATCHES"):
            # x-now-route-matches e.g. "1=report"
            m = parse_qs(environ["HTTP_X_NOW_ROUTE_MATCHES"])
            if "1" in m and m["1"][0]:
                environ["PATH_INFO"] = "/" + m["1"][0].lstrip("/")
        elif environ.get("HTTP_X_VERCEL_PATH"):
            environ["PATH_INFO"] = environ["HTTP_X_VERCEL_PATH"]

        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
