import os
import sqlite3
import requests

# Load environment variables manually or from system
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Try reading from .env file if available
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_PATH):
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key == "SUPABASE_URL" and not SUPABASE_URL:
                        SUPABASE_URL = val.rstrip("/")
                    elif key == "SUPABASE_KEY" and not SUPABASE_KEY:
                        SUPABASE_KEY = val
    except Exception:
        pass

IS_VERCEL = bool(os.environ.get("VERCEL"))
LOCAL_DB_PATH = "/tmp/wastewatch.db" if IS_VERCEL else os.path.join(os.path.dirname(os.path.abspath(__file__)), "wastewatch.db")


def is_supabase_enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def get_supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def get_all_reports():
    """Fetch all reports ordered by id descending from Supabase (or fallback to SQLite)."""
    if is_supabase_enabled():
        try:
            url = f"{SUPABASE_URL}/rest/v1/reports?order=id.desc"
            resp = requests.get(url, headers=get_supabase_headers(), timeout=5)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"[Supabase Error] Fetch failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"[Supabase Connection Error]: {e}")

    # Fallback to SQLite
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports ORDER BY id DESC")
        reports = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return reports
    except Exception as e:
        print(f"[SQLite Fallback Error]: {e}")
        return []


def insert_report(data):
    """Insert a new citizen report into Supabase (or fallback to SQLite)."""
    if is_supabase_enabled():
        try:
            url = f"{SUPABASE_URL}/rest/v1/reports"
            payload = {
                "reporter_name": data.get("reporter_name", "Anonymous Citizen"),
                "reporter_phone": data.get("reporter_phone", ""),
                "image_path": data.get("image_path", ""),
                "description": data.get("description", ""),
                "address": data.get("address", ""),
                "latitude": float(data.get("latitude", 17.6868)),
                "longitude": float(data.get("longitude", 83.2185)),
                "waste_type": data.get("waste_type", "Mixed Municipal Waste"),
                "raw_label": data.get("raw_label", ""),
                "severity": data.get("severity", "Medium"),
                "priority_score": float(data.get("priority_score", 50.0)),
                "status": "Pending"
            }
            resp = requests.post(url, json=payload, headers=get_supabase_headers(), timeout=6)
            if resp.status_code in (200, 201):
                return True
            else:
                print(f"[Supabase Error] Insert failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"[Supabase Insert Error]: {e}")

    # Fallback to SQLite
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reports
            (reporter_name, reporter_phone, image_path, description, address, latitude, longitude, waste_type, raw_label, severity, priority_score, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("reporter_name", "Anonymous Citizen"),
            data.get("reporter_phone", ""),
            data.get("image_path", ""),
            data.get("description", ""),
            data.get("address", ""),
            data.get("latitude", 17.6868),
            data.get("longitude", 83.2185),
            data.get("waste_type", "Mixed Municipal"),
            data.get("raw_label", ""),
            data.get("severity", "Medium"),
            data.get("priority_score", 50.0),
            "Pending"
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[SQLite Insert Error]: {e}")
        return False


def update_report_status(report_id, new_status):
    """Update status of a report in Supabase (or fallback to SQLite)."""
    if is_supabase_enabled():
        try:
            url = f"{SUPABASE_URL}/rest/v1/reports?id=eq.{report_id}"
            resp = requests.patch(url, json={"status": new_status}, headers=get_supabase_headers(), timeout=5)
            if resp.status_code in (200, 204):
                return True
            else:
                print(f"[Supabase Error] Update failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"[Supabase Update Error]: {e}")

    # Fallback to SQLite
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE reports SET status = ? WHERE id = ?", (new_status, report_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[SQLite Update Error]: {e}")
        return False
