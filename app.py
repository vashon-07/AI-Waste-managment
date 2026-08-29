from flask import Flask, render_template, request
import sqlite3
import os

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/report")
def report():
    return render_template("report.html")


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

    connection = sqlite3.connect("wastewatch.db")
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