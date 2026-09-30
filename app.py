from flask import Flask, render_template, request, send_from_directory
import sqlite3
import os

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


def init_db():
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_path TEXT,
            description TEXT,
            latitude REAL,
            longitude REAL,
            address TEXT,
            waste_type TEXT,
            severity TEXT,
            priority_score REAL,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.commit()
    connection.close()


# Ensure DB schema is initialized
init_db()


@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path):
    target = request.args.get("__path") or path or ""
    target = target.strip("/").lower()

    if target in ("report", "api/report"):
        return render_template("report.html")
    elif target in ("login", "api/login", "register", "api/register"):
        if request.method == "POST":
            action = request.form.get("action", "login")
            role = request.form.get("role", "Citizen")
            if action == "register":
                import re
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
                return render_template("login.html", message=f"✓ Signed in successfully as {role.capitalize()} ({user_name})")
        return render_template("login.html")

    elif target in ("submit-report", "api/submit-report") and request.method == "POST":
        return submit_report()
    elif target.startswith("static/"):
        return serve_static(target[7:])
    elif target.startswith("css/"):
        return serve_css(target[4:])

    return render_template("index.html")






@app.route("/submit-report", methods=["POST"])
def submit_report():
    image = request.files.get("image")
    image_path = None

    if image and image.filename:
        image_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            image.filename
        )
        image.save(image_path)

    description = request.form.get("description")
    address = request.form.get("address")
    latitude = request.form.get("latitude")
    longitude = request.form.get("longitude")

    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO reports
        (image_path, description, address, latitude, longitude, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        image_path,
        description,
        address,
        latitude,
        longitude,
        "Pending"
    ))

    connection.commit()
    connection.close()

    return "Report submitted successfully!"


if __name__ == "__main__":
    app.run(debug=True)