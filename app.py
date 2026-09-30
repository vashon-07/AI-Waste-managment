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


@app.route("/")
@app.route("/api/index")
def home():
    return render_template("index.html")





@app.route("/report")
@app.route("/api/report")
def report():
    return render_template("report.html")


@app.route("/login", methods=["GET", "POST"])
@app.route("/api/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "")
        role = request.form.get("role", "Citizen")
        user_name = email.split("@")[0] if "@" in email else email
        return render_template("login.html", message=f"✓ Signed in successfully as {role.capitalize()} ({user_name})")
    return render_template("login.html")


@app.route("/debug")
def debug_route():
    import json
    return json.dumps({
        "path": request.path,
        "full_path": request.full_path,
        "query_string": request.query_string.decode("utf-8", errors="ignore"),
        "headers": dict(request.headers),
        "matched_environ": {k: str(v) for k, v in request.environ.items() if any(w in k for w in ["PATH", "URI", "VERCEL", "MATCH", "NOW", "URL"])}
    }, indent=2), 200, {"Content-Type": "application/json"}




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