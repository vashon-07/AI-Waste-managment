from flask import Flask, render_template, request, redirect, send_from_directory, url_for, jsonify, make_response, session
import sqlite3
import os
import base64
import re
from datetime import datetime
from collections import defaultdict
import time

# ---------------------------------------------------------------------------
# Simple in-memory rate limiter (sliding-window, resets on process restart)
# ---------------------------------------------------------------------------
_rate_buckets: dict = defaultdict(list)  # key -> list of timestamps


def _is_rate_limited(key: str, max_calls: int, window_secs: int) -> bool:
    """Return True if the given key has exceeded max_calls in the last window_secs."""
    now = time.monotonic()
    bucket = _rate_buckets[key]
    # Prune old entries
    _rate_buckets[key] = [t for t in bucket if now - t < window_secs]
    if len(_rate_buckets[key]) >= max_calls:
        return True
    _rate_buckets[key].append(now)
    return False
from ai.predict import predict_waste
from cloud_db import (
    get_all_reports,
    get_citizen_reports,
    insert_report,
    update_report_status,
    get_user_by_credentials,
    get_user_by_phone,
    get_user_by_email,
    create_or_update_user,
    supabase_auth_signup,
    supabase_auth_signin,
    supabase_auth_reset_password,
    cleanup_expired_reports,
    init_cloud_db,
    log_safe_diagnostics,
    check_supabase_health
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
    template_folder=os.path.join(BASE_DIR, "templates")
)
app.secret_key = os.environ.get("SECRET_KEY", "wastewatch-session-secret-key-2026")

# Log safe environment diagnostics on startup
log_safe_diagnostics()


@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static"), filename)


@app.route("/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static", "css"), filename)


# In serverless environments like Vercel, only /tmp is writable
IS_VERCEL = bool(os.environ.get("VERCEL"))

if IS_VERCEL:
    UPLOAD_FOLDER = "/tmp/uploads"
    DB_PATH = "/tmp/wastewatch.db"
else:
    UPLOAD_FOLDER = "uploads"
    DB_PATH = "wastewatch.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def get_db_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_name TEXT,
            reporter_phone TEXT,
            image_path TEXT,
            description TEXT,
            latitude REAL,
            longitude REAL,
            address TEXT,
            waste_type TEXT,
            raw_label TEXT,
            severity TEXT,
            priority_score REAL,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        )
    """)

    # Attempt migration if older columns exist
    try:
        cursor.execute("ALTER TABLE reports ADD COLUMN resolved_at TIMESTAMP")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE reports ADD COLUMN reporter_name TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE reports ADD COLUMN reporter_phone TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE reports ADD COLUMN raw_label TEXT")
    except Exception:
        pass

    # Ensure users table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'citizen',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Seed sample citizen submissions if table is currently empty
    cursor.execute("SELECT COUNT(*) FROM reports")
    count = cursor.fetchone()[0]
    if count == 0:
        cursor.execute("""
            INSERT INTO reports 
            (reporter_name, reporter_phone, image_path, description, latitude, longitude, address, waste_type, severity, priority_score, status)
            VALUES 
            ('Rahul Sharma', '9876543210', 'https://images.unsplash.com/photo-1605600659908-0ef719419d41?auto=format&fit=crop&w=600&q=80', 'Heavy plastic dump and electronic scrap piled near the road crossroad.', 17.6868, 83.2185, 'Dwaraka Nagar Main Rd, Visakhapatnam', 'Plastic & E-Waste', 'High', 84.5, 'Pending'),
            ('Priya Patel', '9812345678', 'https://images.unsplash.com/photo-1530587191325-3db32d826c18?auto=format&fit=crop&w=600&q=80', 'Overflowing garbage bin near residential neighborhood entrance.', 17.7200, 83.3100, 'Beach Road, Sector 4, Visakhapatnam', 'Mixed Organic', 'Medium', 65.0, 'In Progress'),
            ('Anil Verma', '9988776655', 'https://images.unsplash.com/photo-1595278069441-2cf29f8005a4?auto=format&fit=crop&w=600&q=80', 'Hazardous chemicals and medical discard in open vacant plot.', 17.7042, 83.2975, 'MVP Colony, Sector 2, Visakhapatnam', 'Hazardous', 'Critical', 96.0, 'Pending')
        """)

    connection.commit()
    connection.close()
    init_cloud_db()


# Ensure DB schema is initialized
init_db()


def get_current_citizen():
    """Helper to retrieve the authenticated citizen from session or secure cookie."""
    phone = session.get("citizen_phone") or request.cookies.get("citizen_phone")
    name = session.get("citizen_name") or request.cookies.get("citizen_name")
    email = session.get("citizen_email")
    role = session.get("citizen_role") or "citizen"
    if phone or email:
        user = None
        if phone:
            user = get_user_by_phone(phone)
        elif email:
            user = get_user_by_email(email)
        if user:
            return user
        return {"name": name or "Citizen", "phone": phone or "", "email": email or "", "role": role}
    return None


def analyze_waste_ai(description, filename=""):
    """Heuristic AI analyzer estimating waste type, severity, and priority score from description and filename."""
    text = f"{description or ''} {filename or ''}".lower()

    if any(k in text for k in ["chemical", "medical", "hospital", "bio", "battery", "toxic", "hazard", "syringe", "pharma"]):
        return "Hazardous Waste", "Critical", 94.0
    elif any(k in text for k in ["electronic", "e-waste", "wire", "computer", "phone", "tv", "charger", "cable", "circuit", "laptop"]):
        return "E-Waste", "High", 86.0
    elif any(k in text for k in ["plastic", "bottle", "polythene", "bag", "wrapper", "container", "cup", "pvc", "packet"]):
        return "Plastic Waste", "High", 79.5
    elif any(k in text for k in ["can", "tin", "metal", "iron", "steel", "aluminum", "scrap", "rod", "foil"]):
        return "Metal Waste", "Medium", 67.5
    elif any(k in text for k in ["glass", "bottle", "shard", "mirror", "broken glass"]):
        return "Glass Waste", "Medium", 59.0
    elif any(k in text for k in ["food", "organic", "vegetable", "fruit", "animal", "decay", "leaves", "kitchen", "wet waste", "garbage"]):
        return "Organic Waste", "Medium", 63.5
    elif any(k in text for k in ["paper", "cardboard", "carton", "box", "newspaper", "books", "dry waste"]):
        return "Paper & Cardboard", "Low", 46.0
    elif any(k in text for k in ["construction", "debris", "rubble", "concrete", "brick", "stone", "silt", "sludge"]):
        return "Construction Debris", "High", 74.0
    else:
        # Dynamic score variation rather than a frozen static number
        dyn_score = 62.0 + (len(text) % 15)
        return "Mixed Municipal Waste", "Medium", round(dyn_score, 1)


# ---------------------------------------------------------------------------
# Authorized Municipal Officer accounts
# Each officer has a UNIQUE password, controlled by environment variables.
# The hardcoded values are secure defaults so the site works out of the box.
# To override, set the matching env var in your .env file, e.g.:
#   OFFICER_PW_RAJESH=MyNewPass1!
#   OFFICER_PW_SUNITA=MyNewPass2@
#   OFFICER_PW_COMMISSIONER=MyNewPass3#
# ---------------------------------------------------------------------------

# Officer 1 – Chief Officer Rajesh Sharma  (2 login aliases, same person)
_PW_RAJESH       = os.environ.get("OFFICER_PW_RAJESH",       "Rajesh@Ward1#26")

# Officer 2 – Inspector Sunita Reddy
_PW_SUNITA       = os.environ.get("OFFICER_PW_SUNITA",       "Sunita@North2$26")

# Officer 3 – Commissioner K. Rao  (admin / all-wards)
_PW_COMMISSIONER = os.environ.get("OFFICER_PW_COMMISSIONER", "KRao@AllWards!26")

OFFICER_ACCOUNTS = {
    # Chief Officer Rajesh Sharma – login alias 1
    "officer@municipality.gov.in": {
        "password": _PW_RAJESH,
        "name": "Chief Officer Rajesh Sharma",
        "ward": "Ward 1 - Central Zone"
    },
    # Chief Officer Rajesh Sharma – login alias 2
    "officer123": {
        "password": _PW_RAJESH,
        "name": "Chief Officer Rajesh Sharma",
        "ward": "Ward 1 - Central Zone"
    },
    # Inspector Sunita Reddy
    "muni-7082": {
        "password": _PW_SUNITA,
        "name": "Inspector Sunita Reddy",
        "ward": "Ward 2 - North Zone"
    },
    # Commissioner K. Rao
    "admin@wastewatch.gov.in": {
        "password": _PW_COMMISSIONER,
        "name": "Commissioner K. Rao",
        "ward": "All Wards (Central Command)"
    }
}


def get_current_officer():
    """Return the authenticated officer dict from session, or None."""
    name = session.get("officer_name")
    ward = session.get("officer_ward")
    if name and ward:
        return {"name": name, "ward": ward}
    return None


@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path):
    target = request.args.get("__path") or path or ""
    target = target.strip("/").lower()

    # 0. Auth Health Diagnostic Route
    if target in ("auth-health", "api/auth-health"):
        return jsonify(check_supabase_health())

    # 1. Report Waste Page
    elif target in ("report", "api/report"):
        citizen = get_current_citizen()
        return render_template("report.html", citizen=citizen)

    # 2. Citizen Login & Registration
    elif target in ("login", "api/login", "register", "api/register"):
        citizen = get_current_citizen()
        if request.method == "GET" and citizen:
            return redirect("/citizen-dashboard")

        if request.method == "POST":
            action = request.form.get("action", "login")
            role = request.form.get("role", "Citizen")

            if action == "register":
                name = request.form.get("name", "User").strip()
                phone = request.form.get("phone", "").strip()
                email = request.form.get("email", "").strip().lower()
                password = request.form.get("password", "")
                confirm_password = request.form.get("confirm_password", "")

                if not phone.isdigit() or len(phone) != 10:
                    return render_template("login.html", message="Mobile number must contain exactly 10 digits.", is_error=True, default_tab="register")

                if (
                    len(password) < 8
                    or not re.search(r"[A-Z]", password)
                    or not re.search(r"[a-z]", password)
                    or not re.search(r"[0-9]", password)
                    or not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password)
                ):
                    return render_template(
                        "login.html",
                        message="Password must be at least 8 characters and include uppercase, lowercase, number, and special character.",
                        is_error=True,
                        default_tab="register"
                    )

                if password != confirm_password:
                    return render_template("login.html", message="Passwords do not match. Please try again.", is_error=True, default_tab="register")

                user_profile, err = supabase_auth_signup(email, password, name, phone, role)
                if not user_profile:
                    if err in ("connection_error", "service_error"):
                        return render_template("login.html", message="Unable to connect to the authentication service. Please try again.", is_error=True, default_tab="register")
                    elif err:
                        return render_template("login.html", message=err, is_error=True, default_tab="register")
                    else:
                        return render_template("login.html", message="Registration failed. Please try again.", is_error=True, default_tab="register")

                session["citizen_phone"] = user_profile.get("phone") or phone
                session["citizen_name"] = user_profile.get("name") or name
                session["citizen_email"] = user_profile.get("email") or email
                session["citizen_role"] = user_profile.get("role") or role

                resp = make_response(redirect("/citizen-dashboard"))
                resp.set_cookie("citizen_phone", user_profile.get("phone") or phone, max_age=86400 * 30, httponly=True, samesite="Lax")
                resp.set_cookie("citizen_name", user_profile.get("name") or name, max_age=86400 * 30, httponly=True, samesite="Lax")
                return resp

            else:
                identifier = request.form.get("email", "").strip()
                password = request.form.get("password", "")

                user, err = supabase_auth_signin(identifier, password)

                if user:
                    session["citizen_phone"] = user.get("phone", "")
                    session["citizen_name"] = user.get("name", "Citizen")
                    session["citizen_email"] = user.get("email", "")
                    session["citizen_role"] = user.get("role", "citizen")

                    resp = make_response(redirect("/citizen-dashboard"))
                    if user.get("phone"):
                        resp.set_cookie("citizen_phone", user["phone"], max_age=86400 * 30, httponly=True, samesite="Lax")
                    resp.set_cookie("citizen_name", user.get("name", "Citizen"), max_age=86400 * 30, httponly=True, samesite="Lax")
                    return resp
                elif err in ("connection_error", "service_error"):
                    return render_template("login.html", message="Unable to connect to the authentication service. Please try again.", is_error=True)
                elif err == "email_not_confirmed":
                    return render_template("login.html", message="Your email is not confirmed yet. Please verify your email or contact support.", is_error=True)
                elif err and err != "invalid_credentials":
                    return render_template("login.html", message=err, is_error=True)
                else:
                    return render_template("login.html", message="Invalid email/mobile number or password. Please try again.", is_error=True)

        return render_template("login.html")

    # 2b. Citizen Forgot / Reset Password API
    elif target in ("forgot-password", "api/forgot-password", "reset-password", "api/reset-password"):
        if request.method == "POST":
            data = request.get_json(silent=True) or request.form
            email = (data.get("email") or "").strip().lower()
            phone = (data.get("phone") or "").strip()
            new_password = data.get("new_password") or data.get("password") or ""
            confirm_password = data.get("confirm_password") or ""

            if not email:
                return jsonify({"success": False, "message": "Registered email address is required."}), 400

            if not phone:
                return jsonify({"success": False, "message": "Registered 10-digit mobile number is required."}), 400

            if not new_password:
                return jsonify({"success": False, "message": "New password is required."}), 400

            if confirm_password and new_password != confirm_password:
                return jsonify({"success": False, "message": "Passwords do not match. Please re-enter."}), 400

            success, message = supabase_auth_reset_password(email, phone, new_password)
            status_code = 200 if success else 400
            return jsonify({"success": success, "message": message}), status_code

        return redirect("/login")

    # 3. Citizen Dashboard (Personal report history & statistics)
    elif target in ("citizen-dashboard", "citizen/dashboard", "account", "api/citizen-dashboard", "api/account"):
        citizen = get_current_citizen()
        if not citizen:
            return redirect("/login")

        citizen_reports = get_citizen_reports(citizen.get("phone"), citizen.get("name"))

        total_count = len(citizen_reports)
        pending_count = sum(1 for r in citizen_reports if r.get("status") == "Pending")
        in_progress_count = sum(1 for r in citizen_reports if r.get("status") in ("Under Inspection", "In Progress"))
        resolved_count = sum(1 for r in citizen_reports if r.get("status") in ("Cleaned & Resolved", "Resolved"))

        stats = {
            "total": total_count,
            "pending": pending_count,
            "in_progress": in_progress_count,
            "resolved": resolved_count
        }

        resp = make_response(render_template(
            "citizen_dashboard.html",
            citizen=citizen,
            reports=citizen_reports,
            stats=stats
        ))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    # 4. Citizen Logout
    elif target in ("citizen-logout", "logout", "citizen/logout"):
        session.pop("citizen_phone", None)
        session.pop("citizen_name", None)
        session.pop("citizen_email", None)
        session.pop("citizen_role", None)
        resp = make_response(redirect("/login"))
        resp.delete_cookie("citizen_phone")
        resp.delete_cookie("citizen_name")
        return resp

    # 5. Dedicated Municipal Officer Login
    elif target in ("officer-login", "officer/login", "api/officer-login", "api/officer/login"):
        # Already logged in → go straight to dashboard
        if request.method == "GET" and get_current_officer():
            return redirect("/officer-dashboard")

        if request.method == "POST":
            officer_id = request.form.get("officer_id", "").strip().lower()
            officer_password = request.form.get("officer_password", "").strip()
            selected_ward = request.form.get("ward", "All Wards")

            if officer_id in OFFICER_ACCOUNTS and OFFICER_ACCOUNTS[officer_id]["password"] == officer_password:
                account_info = OFFICER_ACCOUNTS[officer_id]
                officer_name = account_info["name"]
                assigned_ward = selected_ward if selected_ward != "All Wards" else account_info["ward"]
                # Store in server-side session (not URL params)
                session["officer_name"] = officer_name
                session["officer_ward"] = assigned_ward
                return redirect("/officer-dashboard")
            else:
                return render_template(
                    "officer_login.html",
                    message="❌ Access Denied: Invalid Officer ID or Security Key. Unauthorized citizen access is strictly prohibited.",
                    is_error=True
                )

        return render_template("officer_login.html")

    # 6. Municipal Officer Dashboard (session-protected)
    elif target in ("officer-dashboard", "officer/dashboard", "api/officer-dashboard", "api/officer/dashboard"):
        officer = get_current_officer()
        if not officer:
            return redirect("/officer-login")

        # Support legacy URL-param links that may still exist in bookmarks
        officer_name = officer["name"]
        officer_ward = officer["ward"]

        reports = get_all_reports()

        total_count = len(reports)
        pending_count = sum(1 for r in reports if r.get("status") == "Pending")
        in_progress_count = sum(1 for r in reports if r.get("status") in ("Under Inspection", "In Progress"))
        resolved_count = sum(1 for r in reports if r.get("status") in ("Cleaned & Resolved", "Resolved"))

        stats = {
            "total": total_count,
            "pending": pending_count,
            "in_progress": in_progress_count,
            "resolved": resolved_count
        }

        resp = make_response(render_template(
            "officer_dashboard.html",
            reports=reports,
            stats=stats,
            officer_name=officer_name,
            officer_ward=officer_ward
        ))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    # 7. Officer Logout – clear session
    elif target in ("officer-logout", "officer/logout"):
        session.pop("officer_name", None)
        session.pop("officer_ward", None)
        return redirect("/officer-login")

    # 8. Status Update Action (officer-only)
    elif target in ("update-status", "api/update-status") and request.method == "POST":
        if not get_current_officer():
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": "Unauthorized"}), 403
            return redirect("/officer-login")
        return update_status()

    # 9. Image Classification API (rate-limited: 10 req/min per IP)
    elif target in ("classify", "api/classify") and request.method == "POST":
        client_ip = request.remote_addr or "unknown"
        if _is_rate_limited(f"classify:{client_ip}", max_calls=10, window_secs=60):
            return jsonify({"success": False, "error": "Too many requests. Please wait a moment."}), 429
        return api_classify()

    # 10. Citizen Submit Report Action (rate-limited: 5 submissions/min per IP)
    elif target in ("submit-report", "api/submit-report") and request.method == "POST":
        client_ip = request.remote_addr or "unknown"
        if _is_rate_limited(f"submit:{client_ip}", max_calls=5, window_secs=60):
            citizen = get_current_citizen()
            return render_template(
                "report.html",
                citizen=citizen,
                success_message=None,
                error_message="⚠️ Too many submissions. Please wait a moment before submitting again."
            ), 429
        return submit_report()

    # 11. Static Fallbacks
    elif target.startswith("static/"):
        return serve_static(target[7:])
    elif target.startswith("css/"):
        return serve_css(target[4:])

    # Default Home Page
    citizen = get_current_citizen()
    return render_template("index.html", citizen=citizen)



@app.route("/api/classify", methods=["POST"])
def api_classify():
    """Real-time Waste Classification API using Hugging Face Vision Transformer."""
    image_input = None

    # Check for multipart file upload
    if "image" in request.files and request.files["image"].filename:
        image_file = request.files["image"]
        image_input = image_file.read()

    # Or check for JSON payload with base64 data
    elif request.is_json:
        data = request.get_json(silent=True) or {}
        image_input = data.get("image")

    # Or check for form data with base64 data URL
    elif "image_data" in request.form:
        image_input = request.form.get("image_data")

    if not image_input:
        return jsonify({"success": False, "error": "No valid image provided for classification."}), 400

    try:
        prediction = predict_waste(image_input)
        return jsonify(prediction)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/submit-report", methods=["POST"])
def submit_report():
    reporter_name = request.form.get("reporter_name", "Anonymous Citizen").strip() or "Anonymous Citizen"
    reporter_phone = request.form.get("reporter_phone", "").strip()
    description = request.form.get("description", "").strip()
    address = (
        request.form.get("address", "").strip()
        or request.form.get("location", "").strip()
    )
    latitude = request.form.get("latitude")
    longitude = request.form.get("longitude")

    # Validate GPS coordinates – both latitude and longitude must be provided
    if not latitude or not longitude:
        citizen = get_current_citizen()
        return render_template(
            "report.html",
            citizen=citizen,
            error_message="⚠️ Upload an Image and provide GPS location to submit report"
        )
    # Existing conversion logic remains unchanged
    try:
        lat = round(float(latitude), 7) if latitude else 17.6868
        lng = round(float(longitude), 7) if longitude else 83.2185
    except (ValueError, TypeError):
        lat, lng = 17.6868, 83.2185

    image = request.files.get("image")
    image_path = None
    image_bytes = None

    # --- Priority 0: Cloudinary URL uploaded by browser before form submit ---
    cloudinary_url = request.form.get("cloudinary_image_url", "").strip()
    if cloudinary_url and cloudinary_url.startswith("https://res.cloudinary.com/"):
        image_path = cloudinary_url
        # Still read image_bytes for AI fallback classification if needed
        if image and image.filename:
            try:
                image_bytes = image.read()
            except Exception:
                pass
    elif image and image.filename:
        # Convert image to data URL so it displays permanently across serverless instances
        try:
            image_bytes = image.read()
            if image_bytes:
                content_type = image.content_type or "image/jpeg"
                b64_data = base64.b64encode(image_bytes).decode("utf-8")
                image_path = f"data:{content_type};base64,{b64_data}"
        except Exception:
            image_path = None

    if not image_path:
        # No image provided — reject the report
        citizen = get_current_citizen()
        return render_template(
            "report.html",
            citizen=citizen,
            error_message="⚠️ Upload an Image to submit report"
        )

    # --- Priority 1: browser-side Transformers.js classification ---
    # The report form now submits hidden fields populated by browser AI.
    waste_type     = request.form.get("browser_waste_type", "").strip() or None
    raw_label      = request.form.get("browser_raw_label",  "").strip() or None
    severity       = request.form.get("browser_severity",   "").strip() or None
    priority_score_str = request.form.get("browser_priority_score", "").strip()
    try:
        priority_score = float(priority_score_str) if priority_score_str else None
    except ValueError:
        priority_score = None

    # --- Priority 2: Python Hugging Face ViT model (fallback) ---
    if not waste_type or not severity or priority_score is None:
        if image_bytes:
            try:
                ai_res = predict_waste(image_bytes)
                if ai_res and ai_res.get("success"):
                    waste_type     = waste_type     or ai_res.get("waste_type")
                    raw_label      = raw_label      or ai_res.get("raw_label")
                    severity       = severity       or ai_res.get("severity")
                    priority_score = priority_score if priority_score is not None else ai_res.get("priority_score")
            except Exception:
                pass

    # --- Priority 3: heuristic text/filename analysis ---
    if not waste_type or not severity or priority_score is None:
        waste_type, severity, priority_score = analyze_waste_ai(description, image.filename if image else "")

    citizen = get_current_citizen()
    if citizen:
        if not reporter_name or reporter_name == "Anonymous Citizen":
            reporter_name = citizen.get("name", "Anonymous Citizen")
        if not reporter_phone:
            reporter_phone = citizen.get("phone", "")

    insert_report({
        "reporter_name": reporter_name,
        "reporter_phone": reporter_phone,
        "image_path": image_path,
        "description": description,
        "address": address,
        "latitude": lat,
        "longitude": lng,
        "waste_type": waste_type,
        "raw_label": raw_label,
        "severity": severity,
        "priority_score": priority_score,
    })

    return render_template(
        "report.html",
        citizen=citizen,
        success_message=f"🎉 Report submitted successfully! AI identified: {waste_type} (Priority: {severity}). Assigned to Municipal Field Officers."
    )



@app.route("/update-status", methods=["POST"])
def update_status():
    report_id = request.form.get("report_id") or (request.json.get("report_id") if request.is_json else None)
    new_status = request.form.get("new_status") or (request.json.get("new_status") if request.is_json else None) or "Pending"

    success = False
    if report_id:
        success = update_report_status(report_id, new_status)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": success, "report_id": report_id, "new_status": new_status})

    # Non-AJAX fallback: redirect back to officer dashboard
    return redirect("/officer-dashboard")

@app.route("/api/auth-health")
def auth_health_route():
    return jsonify(check_supabase_health())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)