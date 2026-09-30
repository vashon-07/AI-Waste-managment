import os
import sys
from urllib.parse import parse_qs

# Ensure root directory is on the path so app can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


def handler(environ, start_response):
    # Extract original path rewritten by Vercel (__path parameter)
    query = environ.get("QUERY_STRING", "")
    params = parse_qs(query)

    if "__path" in params and params["__path"][0]:
        path = "/" + params["__path"][0].lstrip("/")
        environ["PATH_INFO"] = path
    elif not environ.get("PATH_INFO") or environ.get("PATH_INFO") in ("/api/index", "/api"):
        environ["PATH_INFO"] = "/"

    return app(environ, start_response)


# Also expose app directly
app_handler = handler
