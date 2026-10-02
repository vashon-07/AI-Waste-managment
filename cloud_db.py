import os
import sqlite3
import requests
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables manually or from system
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SECRET_KEY")
    or ""
)

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
                    elif key in ("SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY") and not SUPABASE_KEY:
                        SUPABASE_KEY = val
    except Exception:
        pass

IS_VERCEL = bool(os.environ.get("VERCEL"))
LOCAL_DB_PATH = "/tmp/wastewatch.db" if IS_VERCEL else os.path.join(os.path.dirname(os.path.abspath(__file__)), "wastewatch.db")


def is_supabase_enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def verify_password(stored_password, provided_password):
    """Securely verify password against cryptographic hash, with fallback for legacy demo accounts."""
    if not stored_password or not provided_password:
        return False
    # Check if stored_password is a valid werkzeug hash format (e.g. scrypt:..., pbkdf2:...)
    if stored_password.startswith(("scrypt:", "pbkdf2:")):
        try:
            return check_password_hash(stored_password, provided_password)
        except Exception:
            return False
    # Fallback for legacy demo accounts seeded with raw string
    return stored_password == provided_password


def get_supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def init_cloud_db():
    """Ensure required tables and columns exist in SQLite database."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
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

        # Create users table for citizen accounts
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

        # Seed sample demo citizen accounts if none exist
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            sample_citizens = [
                ("Rahul Sharma", "9876543210", "rahul@gmail.com", "Password@123", "citizen"),
                ("Priya Patel", "9812345678", "priya@gmail.com", "Password@123", "citizen"),
                ("Anil Verma", "9988776655", "anil@gmail.com", "Password@123", "citizen"),
                ("Abhishek", "8555063716", "abhishek@wastewatch.org", "Password@123", "citizen"),
                ("Vashon", "8520970289", "vashon@wastewatch.org", "Password@123", "citizen"),
            ]
            cursor.executemany("""
                INSERT OR IGNORE INTO users (name, phone, email, password, role)
                VALUES (?, ?, ?, ?, ?)
            """, sample_citizens)

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[init_cloud_db Error]: {e}")


# Initialize schema immediately
init_cloud_db()


def cleanup_expired_reports():
    """Permanently delete resolved reports older than 10 days from resolution timestamp.
    Active reports (Pending, Under Inspection) and unresolved reports are never deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=10)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    # 1. Supabase cleanup if enabled
    if is_supabase_enabled():
        try:
            # Query and delete where status is resolved and resolved_at <= 10 days ago
            cutoff_iso = cutoff.isoformat()
            url = f"{SUPABASE_URL}/rest/v1/reports?status=in.(Cleaned%20%26%20Resolved,Resolved)&resolved_at=lte.{cutoff_iso}&resolved_at=not.is.null"
            requests.delete(url, headers=get_supabase_headers(), timeout=5)
        except Exception as e:
            print(f"[Supabase Cleanup Error]: {e}")

    # 2. SQLite cleanup
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        # Find images to delete if they are local files
        cursor.execute("""
            SELECT id, image_path FROM reports
            WHERE (status = 'Cleaned & Resolved' OR status = 'Resolved')
              AND resolved_at IS NOT NULL
              AND resolved_at <= ?
        """, (cutoff_str,))
        expired_rows = cursor.fetchall()
        for row in expired_rows:
            img_path = row[1]
            if img_path and not img_path.startswith("http") and not img_path.startswith("data:"):
                if os.path.exists(img_path):
                    try:
                        os.remove(img_path)
                    except Exception:
                        pass

        # Permanently delete the expired resolved reports
        cursor.execute("""
            DELETE FROM reports
            WHERE (status = 'Cleaned & Resolved' OR status = 'Resolved')
              AND resolved_at IS NOT NULL
              AND resolved_at <= ?
        """, (cutoff_str,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SQLite Cleanup Error]: {e}")


def get_all_reports():
    """Fetch all reports ordered by id descending from Supabase (or fallback to SQLite)."""
    cleanup_expired_reports()

    if is_supabase_enabled():
        try:
            url = f"{SUPABASE_URL}/rest/v1/reports?order=id.desc"
            resp = requests.get(url, headers=get_supabase_headers(), timeout=6)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"[Supabase Error] Fetch failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"[Supabase Connection Error]: {e}")

        if IS_VERCEL:
            return []

    # Fallback to SQLite (local development only)
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


def get_citizen_reports(reporter_phone=None, reporter_name=None):
    """Securely fetch waste reports submitted exclusively by the specified citizen."""
    cleanup_expired_reports()

    reporter_phone = (reporter_phone or "").strip()
    reporter_name = (reporter_name or "").strip()

    if not reporter_phone and not reporter_name:
        return []

    if is_supabase_enabled():
        try:
            if reporter_phone:
                url = f"{SUPABASE_URL}/rest/v1/reports?reporter_phone=eq.{reporter_phone}&order=id.desc"
            else:
                url = f"{SUPABASE_URL}/rest/v1/reports?reporter_name=eq.{reporter_name}&order=id.desc"
            resp = requests.get(url, headers=get_supabase_headers(), timeout=6)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"[Supabase Citizen Fetch Error] HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Supabase Citizen Fetch Error]: {e}")

        if IS_VERCEL:
            return []

    # Fallback to SQLite (local development only)
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if reporter_phone and reporter_name:
            cursor.execute("""
                SELECT * FROM reports 
                WHERE reporter_phone = ? OR reporter_name = ?
                ORDER BY id DESC
            """, (reporter_phone, reporter_name))
        elif reporter_phone:
            cursor.execute("SELECT * FROM reports WHERE reporter_phone = ? ORDER BY id DESC", (reporter_phone,))
        else:
            cursor.execute("SELECT * FROM reports WHERE reporter_name = ? ORDER BY id DESC", (reporter_name,))
        reports = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return reports
    except Exception as e:
        print(f"[SQLite Citizen Fetch Error]: {e}")
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
            resp = requests.post(url, json=payload, headers=get_supabase_headers(), timeout=8)
            if resp.status_code in (200, 201):
                return True
            else:
                print(f"[Supabase Error] Insert failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"[Supabase Insert Error]: {e}")

        if IS_VERCEL:
            return False

    # Fallback to SQLite (local development only)
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
    """Update status and resolution timestamp of a report in Supabase and SQLite."""
    # Normalize status string to standard options: 'Pending', 'Under Inspection', 'Cleaned & Resolved'
    norm = (new_status or "").strip().lower()
    if norm in ("resolved", "cleaned & resolved", "cleaned"):
        standard_status = "Cleaned & Resolved"
        resolved_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    elif norm in ("in progress", "under inspection", "inspection"):
        standard_status = "Under Inspection"
        resolved_at = None
    else:
        standard_status = "Pending"
        resolved_at = None

    if is_supabase_enabled():
        try:
            url = f"{SUPABASE_URL}/rest/v1/reports?id=eq.{report_id}"
            payload = {"status": standard_status, "resolved_at": resolved_at}
            resp = requests.patch(url, json=payload, headers=get_supabase_headers(), timeout=6)
            if resp.status_code in (200, 204):
                return True
            else:
                print(f"[Supabase Error] Update failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"[Supabase Update Error]: {e}")

        if IS_VERCEL:
            return False

    # Fallback to SQLite (local development only)
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE reports SET status = ?, resolved_at = ? WHERE id = ?", (standard_status, resolved_at, report_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[SQLite Update Error]: {e}")
        return False


def get_user_by_credentials(identifier, password):
    """Authenticate citizen user by phone or email and password.
    Returns (user_dict, error_status).
    """
    init_cloud_db()
    ident = (identifier or "").strip().lower()

    if is_supabase_enabled():
        try:
            # Query Supabase by phone or email (case-insensitive for email)
            url = f"{SUPABASE_URL}/rest/v1/users?or=(phone.eq.{ident},email.ilike.{ident})"
            resp = requests.get(url, headers=get_supabase_headers(), timeout=6)
            if resp.status_code == 200:
                rows = resp.json()
                if rows:
                    user = rows[0]
                    if verify_password(user.get("password"), password):
                        return user, None
                    return None, "invalid_credentials"
                return None, "invalid_credentials"
            else:
                print(f"[Supabase Auth Error] HTTP {resp.status_code}: {resp.text}")
                return None, "service_error"
        except Exception as e:
            print(f"[Supabase Auth Connection Error]: {e}")
            return None, "connection_error"

    # Fallback to SQLite (local development only)
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM users
            WHERE LOWER(phone) = ? OR LOWER(email) = ?
        """, (ident, ident))
        row = cursor.fetchone()
        conn.close()
        if row:
            user = dict(row)
            if verify_password(user.get("password"), password):
                return user, None
            return None, "invalid_credentials"
        return None, "invalid_credentials"
    except Exception as e:
        print(f"[get_user_by_credentials Error]: {e}")
        return None, "service_error"


def get_user_by_phone(phone):
    """Retrieve citizen user by 10-digit phone number."""
    init_cloud_db()
    phone_clean = str(phone).strip()

    if is_supabase_enabled():
        try:
            url = f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone_clean}"
            resp = requests.get(url, headers=get_supabase_headers(), timeout=6)
            if resp.status_code == 200:
                rows = resp.json()
                if rows:
                    return rows[0]
                return None
            else:
                print(f"[Supabase get_user_by_phone Error] HTTP {resp.status_code}: {resp.text}")
                return None
        except Exception as e:
            print(f"[Supabase get_user_by_phone Error]: {e}")
            return None

    # Fallback to SQLite (local development only)
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE phone = ?", (phone_clean,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[get_user_by_phone Error]: {e}")
        return None


def create_or_update_user(name, phone, email, password, role="citizen"):
    """Register or update a citizen account with cryptographic password hashing.
    Returns (success_bool, error_status).
    """
    init_cloud_db()
    name = (name or "").strip()
    phone = (phone or "").strip()
    email = (email or "").strip().lower()
    hashed_password = generate_password_hash(password)

    if is_supabase_enabled():
        try:
            # Check if user already exists in Supabase
            check_url = f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}"
            check_resp = requests.get(check_url, headers=get_supabase_headers(), timeout=6)
            if check_resp.status_code == 200:
                existing = check_resp.json()
                if existing:
                    patch_url = f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}"
                    patch_payload = {
                        "name": name,
                        "email": email,
                        "password": hashed_password,
                        "role": role
                    }
                    resp = requests.patch(patch_url, json=patch_payload, headers=get_supabase_headers(), timeout=6)
                    if resp.status_code in (200, 204):
                        return True, None
                else:
                    post_url = f"{SUPABASE_URL}/rest/v1/users"
                    post_payload = {
                        "name": name,
                        "phone": phone,
                        "email": email,
                        "password": hashed_password,
                        "role": role
                    }
                    resp = requests.post(post_url, json=post_payload, headers=get_supabase_headers(), timeout=6)
                    if resp.status_code in (200, 201):
                        return True, None
            print(f"[Supabase create_or_update_user Error] HTTP {check_resp.status_code}: {check_resp.text}")
            return False, "service_error"
        except Exception as e:
            print(f"[Supabase create_or_update_user Connection Error]: {e}")
            return False, "connection_error"

    # Fallback to SQLite (local development only)
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (name, phone, email, password, role)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                name=excluded.name,
                email=excluded.email,
                password=excluded.password,
                role=excluded.role
        """, (name, phone, email, hashed_password, role))
        conn.commit()
        conn.close()
        return True, None
    except Exception as e:
        print(f"[create_or_update_user Error]: {e}")
        return False, "service_error"


