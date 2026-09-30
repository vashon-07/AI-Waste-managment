import os
import sys
from urllib.parse import parse_qs

# Ensure root directory is on the path so app can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# WSGI Middleware to reliably map Vercel route rewrites to Flask
original_wsgi_app = app.wsgi_app


def wsgi_app_wrapper(environ, start_response):
    query = environ.get("QUERY_STRING", "")
    params = parse_qs(query)

    if "__path" in params:
        raw_path = params.get("__path", [""])[0].strip("/")
        environ["PATH_INFO"] = "/" + raw_path if raw_path else "/"
    elif not environ.get("PATH_INFO") or environ.get("PATH_INFO") in ("/api/index", "/api"):
        environ["PATH_INFO"] = "/"

    return original_wsgi_app(environ, start_response)


app.wsgi_app = wsgi_app_wrapper
