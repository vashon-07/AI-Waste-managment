from flask import Flask, render_template, request, redirect, send_from_directory, url_for, jsonify, make_response
import sqlite3
import os
import base64
import re
from ai.predict import predict_waste
from cloud_db import get_all_reports, insert_report, update_report_status

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
    template_folder=os.path.join(BASE_DIR, "templates")
)


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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Attempt migration if older columns exist
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


# Ensure DB schema is initialized
init_db()


def analyze_waste_ai(description, filename=""):
    """Heuristic AI analyzer estimating waste type, severity, and priority score."""
    desc = (description or "").lower()
    
    if any(k in desc for k in ["chemical", "medical", "hospital", "bio", "battery", "toxic", "hazard"]):
        return "Hazardous Waste", "Critical", 95.0
    elif any(k in desc for k in ["electronic", "e-waste", "wire", "computer", "phone", "tv"]):
        return "E-Waste", "High", 85.0
    elif any(k in desc for k in ["plastic", "bottle", "polythene", "bag", "wrapper"]):
        return "Plastic Waste", "High", 78.0
    elif any(k in desc for k in ["food", "organic", "vegetable", "fruit", "animal", "decay"]):
        return "Organic Waste", "Medium", 62.0
    elif any(k in desc for k in ["glass", "bottle", "shard"]):
        return "Glass Waste", "Medium", 58.0
    elif any(k in desc for k in ["paper", "cardboard", "carton"]):
        return "Paper / Cardboard", "Low", 45.0
    else:
        return "Mixed Municipal Waste", "Medium", 68.0


# Authorized Municipal Officer accounts (Restricted from citizen login)
OFFICER_ACCOUNTS = {
    "officer@municipality.gov.in": {
        "password": "Officer@123",
        "name": "Chief Officer Rajesh Sharma",
        "ward": "Ward 1 - Central Zone"
    },
    "officer123": {
        "password": "Officer@123",
        "name": "Chief Officer Rajesh Sharma",
        "ward": "Ward 1 - Central Zone"
    },
    "muni-7082": {
        "password": "Officer@123",
        "name": "Inspector Sunita Reddy",
        "ward": "Ward 2 - North Zone"
    },
    "admin@wastewatch.gov.in": {
        "password": "Officer@2026",
        "name": "Commissioner K. Rao",
        "ward": "All Wards (Central Command)"
    }
}


@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path):
    target = request.args.get("__path") or path or ""
    target = target.strip("/").lower()

    # 1. Report Waste Page
    if target in ("report", "api/report"):
        return render_template("report.html")

    # 2. Citizen Login & Registration
    elif target in ("login", "api/login", "register", "api/register"):
        if request.method == "POST":
            action = request.form.get("action", "login")
            role = request.form.get("role", "Citizen")

            if action == "register":
                name = request.form.get("name", "User").strip()
                phone = request.form.get("phone", "").strip()
                password = request.form.get("password", "")
                confirm_password = request.form.get("confirm_password", "")

                if not phone.isdigit() or len(phone) != 10:
                    return render_template("login.html", message="Mobile number must contain exactly 10 digits.", is_error=True)

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
                        is_error=True
                    )

                if password != confirm_password:
                    return render_template("login.html", message="Passwords do not match. Please try again.", is_error=True)

                return render_template("login.html", message=f"✓ Account created successfully! Welcome, {name} ({role.capitalize()}).", is_error=False)

            else:
                email = request.form.get("email", "")
                user_name = email.split("@")[0] if "@" in email else email
                return render_template("login.html", message=f"✓ Signed in successfully as {role.capitalize()} ({user_name})", is_error=False)

        return render_template("login.html")

    # 3. Dedicated Municipal Officer Login (Restricted to authorized Officer accounts)
    elif target in ("officer-login", "officer/login", "api/officer-login", "api/officer/login"):
        if request.method == "POST":
            officer_id = request.form.get("officer_id", "").strip().lower()
            officer_password = request.form.get("officer_password", "").strip()
            selected_ward = request.form.get("ward", "All Wards")

            # Validate against official municipal staff accounts
            if officer_id in OFFICER_ACCOUNTS and OFFICER_ACCOUNTS[officer_id]["password"] == officer_password:
                account_info = OFFICER_ACCOUNTS[officer_id]
                officer_name = account_info["name"]
                assigned_ward = selected_ward if selected_ward != "All Wards" else account_info["ward"]
                return redirect(f"/officer-dashboard?officer_name={officer_name}&ward={assigned_ward}")
            else:
                return render_template(
                    "officer_login.html",
                    message="❌ Access Denied: Invalid Officer ID or Security Key. Unauthorized citizen access is strictly prohibited.",
                    is_error=True
                )

        return render_template("officer_login.html")


    # 4. Municipal Officer Dashboard (View all photos, locations & names)
    elif target in ("officer-dashboard", "officer/dashboard", "api/officer-dashboard", "api/officer/dashboard"):
        officer_name = request.args.get("officer_name", "Officer In-Charge")
        officer_ward = request.args.get("ward", "All Wards (Central Command)")

        reports = get_all_reports()

        resp = make_response(render_template(
            "officer_dashboard.html",
            reports=reports,
            officer_name=officer_name,
            officer_ward=officer_ward
        ))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    # 5. Officer Logout
    elif target in ("officer-logout", "officer/logout"):
        return redirect("/officer-login")

    # 6. Status Update Action
    elif target in ("update-status", "api/update-status") and request.method == "POST":
        return update_status()

    # 7. Image Classification API
    elif target in ("classify", "api/classify") and request.method == "POST":
        return api_classify()

    # 8. Citizen Submit Report Action
    elif target in ("submit-report", "api/submit-report") and request.method == "POST":
        return submit_report()

    # 9. Static Fallbacks
    elif target.startswith("static/"):
        return serve_static(target[7:])
    elif target.startswith("css/"):
        return serve_css(target[4:])

    # Default Home Page
    return render_template("index.html")


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
    address = request.form.get("address", "").strip()
    latitude = request.form.get("latitude")
    longitude = request.form.get("longitude")

    try:
        lat = float(latitude) if latitude else 17.6868
        lng = float(longitude) if longitude else 83.2185
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
            image_path = "https://images.unsplash.com/photo-1605600659908-0ef719419d41?auto=format&fit=crop&w=600&q=80"

    if not image_path:
        image_path = "https://images.unsplash.com/photo-1530587191325-3db32d826c18?auto=format&fit=crop&w=600&q=80"

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
        success_message=f"🎉 Report submitted successfully! AI identified: {waste_type} (Priority: {severity}). Assigned to Municipal Field Officers."
    )


@app.route("/update-status", methods=["POST"])
def update_status():
    report_id = request.form.get("report_id")
    new_status = request.form.get("new_status", "Pending")

    if report_id:
        update_report_status(report_id, new_status)

    return redirect("/officer-dashboard")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)