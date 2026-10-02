import os
import sqlite3
import requests
import re
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash

def _clean_env_val(val):
    if not val:
        return ""
    return str(val).strip().strip('"').strip("'").strip()


# Load environment variables manually or from system
SUPABASE_URL = _clean_env_val(
    os.environ.get("SUPABASE_URL")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    or ""
).rstrip("/")

SUPABASE_SERVICE_ROLE_KEY = _clean_env_val(
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SECRET_KEY")
    or ""
)

SUPABASE_KEY = _clean_env_val(
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_SECRET_KEY")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or ""
)

SECRET_KEY = _clean_env_val(os.environ.get("SECRET_KEY", ""))

# Try reading from .env, .env.local, or .env.production if available
for env_file in (".env", ".env.local", ".env.production"):
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), env_file)
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = _clean_env_val(val)
                        if key in ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL") and not SUPABASE_URL:
                            SUPABASE_URL = val.rstrip("/")
                        elif key in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY") and not SUPABASE_SERVICE_ROLE_KEY:
                            SUPABASE_SERVICE_ROLE_KEY = val
                        elif key in ("SUPABASE_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY") and not SUPABASE_KEY:
                            SUPABASE_KEY = val
                        elif key == "SECRET_KEY" and not SECRET_KEY:
                            SECRET_KEY = val
        except Exception:
            pass

if not SUPABASE_KEY and SUPABASE_SERVICE_ROLE_KEY:
    SUPABASE_KEY = SUPABASE_SERVICE_ROLE_KEY

IS_VERCEL = bool(os.environ.get("VERCEL"))
LOCAL_DB_PATH = "/tmp/wastewatch.db" if IS_VERCEL else os.path.join(os.path.dirname(os.path.abspath(__file__)), "wastewatch.db")


def is_supabase_enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def log_safe_diagnostics():
    """Safely log diagnostic environment presence without revealing secret values."""
    print("=== Wastewatch Safe Diagnostic Report ===")
    print(f"SUPABASE_URL configured: {bool(SUPABASE_URL)}")
    print(f"SUPABASE_SERVICE_ROLE_KEY configured: {bool(os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or SUPABASE_SERVICE_ROLE_KEY)}")
    print(f"SUPABASE_KEY configured: {bool(os.environ.get('SUPABASE_KEY') or SUPABASE_KEY)}")
    print(f"SECRET_KEY configured: {bool(os.environ.get('SECRET_KEY') or SECRET_KEY)}")
    print(f"IS_VERCEL: {IS_VERCEL}")
    print(f"Supabase Auth Enabled: {is_supabase_enabled()}")
    print("=========================================")


# Log diagnostics once at module load
log_safe_diagnostics()


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
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def get_supabase_auth_headers():
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
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


def get_user_by_email(email):
    """Retrieve citizen user by email address from public.users."""
    email_clean = str(email or "").strip().lower()
    if not email_clean:
        return None

    if is_supabase_enabled():
        try:
            url = f"{SUPABASE_URL}/rest/v1/users?email=ilike.{email_clean}"
            resp = requests.get(url, headers=get_supabase_headers(), timeout=6)
            if resp.status_code == 200:
                rows = resp.json()
                if rows:
                    return rows[0]
                return None
        except Exception as e:
            print(f"[Supabase get_user_by_email Error]: {e}")
            return None

    if not IS_VERCEL:
        try:
            init_cloud_db()
            conn = sqlite3.connect(LOCAL_DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email_clean,))
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            print(f"[get_user_by_email Error]: {e}")
            return None
    return None


def get_user_by_phone(phone):
    """Retrieve citizen user by 10-digit phone number from public.users."""
    phone_clean = str(phone or "").strip()
    if not phone_clean:
        return None

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
                print(f"[Supabase get_user_by_phone Error] HTTP {resp.status_code}")
                return None
        except Exception as e:
            print(f"[Supabase get_user_by_phone Error]: {e}")
            return None

    if not IS_VERCEL:
        try:
            init_cloud_db()
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
    return None


def supabase_auth_signup(email, password, name, phone, role="citizen"):
    """Register citizen account using Supabase Auth signUp().
    After successful registration, creates a profile row in public.users.
    Does NOT store the password in public.users (kept strictly in Supabase Auth).
    Uses the Supabase Auth user's UUID as public.users.id if allowed by schema.
    Returns (user_profile_dict, error_status).
    """
    name = (name or "").strip()
    phone = (phone or "").strip()
    email = (email or "").strip().lower()
    role = (role or "citizen").strip().lower()

    if not email or not password:
        return None, "Email and password are required."

    # In production (Vercel) or when Supabase is configured, enforce Supabase Auth
    if IS_VERCEL or is_supabase_enabled():
        if not is_supabase_enabled():
            log_safe_diagnostics()
            err_msg = "Supabase configuration missing on server (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required)."
            print(f"[Supabase Auth SignUp Error] {err_msg}")
            return None, err_msg

        try:
            # 1. Attempt user creation via Admin API first (avoids email rate limits and auto-confirms)
            admin_url = f"{SUPABASE_URL}/auth/v1/admin/users"
            admin_payload = {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {
                    "name": name,
                    "phone": phone,
                    "role": role
                }
            }
            resp = requests.post(admin_url, json=admin_payload, headers=get_supabase_headers(), timeout=10)
            print(f"[Supabase Admin Create User] Status: {resp.status_code}")

            # If admin endpoint failed due to lack of admin permissions (e.g. anon key), fall back to public signup
            if resp.status_code not in (200, 201):
                err_admin = resp.json() if resp.text else {}
                err_msg = err_admin.get("msg") or err_admin.get("message") or ""
                if "already registered" in err_msg.lower() or "already exists" in err_msg.lower():
                    return None, "An account with this email already exists. Please sign in."

                signup_url = f"{SUPABASE_URL}/auth/v1/signup"
                signup_payload = {
                    "email": email,
                    "password": password,
                    "data": {
                        "name": name,
                        "phone": phone,
                        "role": role
                    }
                }
                resp = requests.post(signup_url, json=signup_payload, headers=get_supabase_auth_headers(), timeout=10)
                print(f"[Supabase Auth SignUp Fallback] Status: {resp.status_code}")

            if resp.status_code in (200, 201):
                auth_data = resp.json() if resp.text else {}
                auth_user = auth_data.get("user") if isinstance(auth_data.get("user"), dict) else auth_data
                auth_id = auth_user.get("id") if isinstance(auth_user, dict) else None

                # Requirement 7: Verify that the returned Supabase Auth user has an ID
                if not auth_id:
                    print(f"[Supabase Auth SignUp] Error: No user ID in response payload.")
                    return None, "Supabase authentication succeeded but returned no user ID."

                print(f"[Supabase Auth SignUp] Success. Created user ID: {auth_id}")

                # Auto-confirm user email using service role key if available
                try:
                    admin_confirm_url = f"{SUPABASE_URL}/auth/v1/admin/users/{auth_id}"
                    confirm_resp = requests.put(admin_confirm_url, json={"email_confirm": True}, headers=get_supabase_headers(), timeout=5)
                    print(f"[Supabase Auth Admin Confirm] Auto-confirm status: {confirm_resp.status_code}")
                except Exception as e:
                    print(f"[Supabase Auth Admin Confirm] Error during auto-confirm: {e}")

                # Requirement 8: Create corresponding profile row in public.users
                # Note: Password is NOT stored in public.users per Requirement 5
                profile_payload = {
                    "name": name,
                    "phone": phone,
                    "email": email,
                    "password": "",
                    "role": role
                }

                # Try with UUID id first
                profile_with_uuid = dict(profile_payload)
                profile_with_uuid["id"] = auth_id

                post_url = f"{SUPABASE_URL}/rest/v1/users"
                prof_resp = requests.post(post_url, json=profile_with_uuid, headers=get_supabase_headers(), timeout=6)
                print(f"[Supabase public.users Insert] Status with UUID: {prof_resp.status_code}")

                profile_inserted = prof_resp.status_code in (200, 201)
                prof_err_detail = ""

                # If public.users.id is BIGINT identity or user already exists, adapt safely
                if not profile_inserted:
                    prof_err_detail = prof_resp.text[:160] if prof_resp.text else ""
                    print(f"[Supabase public.users Insert] UUID insert failed ({prof_resp.status_code}): {prof_err_detail}. Adapting schema...")
                    check_url = f"{SUPABASE_URL}/rest/v1/users?or=(phone.eq.{phone},email.ilike.{email})"
                    check_res = requests.get(check_url, headers=get_supabase_headers(), timeout=6)
                    if check_res.status_code == 200 and check_res.json():
                        patch_url = f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}"
                        patch_res = requests.patch(patch_url, json=profile_payload, headers=get_supabase_headers(), timeout=6)
                        profile_inserted = patch_res.status_code in (200, 204)
                        print(f"[Supabase public.users Patch] Status: {patch_res.status_code}")
                    else:
                        alt_res = requests.post(post_url, json=profile_payload, headers=get_supabase_headers(), timeout=6)
                        profile_inserted = alt_res.status_code in (200, 201)
                        if not profile_inserted:
                            prof_err_detail = alt_res.text[:160] if alt_res.text else prof_err_detail
                        print(f"[Supabase public.users Insert without ID] Status: {alt_res.status_code}")

                if not profile_inserted:
                    print(f"[Supabase public.users Error] Could not insert into public.users. Error: {prof_err_detail}")
                    if "row-level security" in prof_err_detail.lower() or prof_resp.status_code in (401, 403):
                        return None, "Supabase Row-Level Security (RLS) blocked the user profile insert. Ensure SUPABASE_SERVICE_ROLE_KEY is used or RLS is configured on public.users."
                    return None, f"Created in Supabase Auth, but public.users profile failed: {prof_err_detail}"

                user_profile = {
                    "id": auth_id,
                    "name": name,
                    "phone": phone,
                    "email": email,
                    "role": role
                }
                return user_profile, None

            else:
                err_json = resp.json() if resp.text else {}
                safe_msg = (
                    err_json.get("msg")
                    or err_json.get("error_description")
                    or err_json.get("message")
                    or f"Supabase Auth error (HTTP {resp.status_code})"
                )
                print(f"[Supabase Auth SignUp Failed] HTTP {resp.status_code}: {safe_msg}")
                if "already registered" in safe_msg.lower() or "already exists" in safe_msg.lower():
                    return None, "An account with this email already exists. Please sign in."
                if "rate limit" in safe_msg.lower():
                    return None, "Supabase email rate limit reached. Please wait 10-15 minutes or disable 'Confirm email' in Supabase Auth."
                return None, safe_msg

        except Exception as e:
            print(f"[Supabase Auth SignUp Exception]: {e}")
            return None, f"Authentication service connection error: {str(e)}"

    # ONLY reached in local development when offline and Supabase is not configured
    print("[Local Dev Fallback] Registering user in local SQLite...")
    try:
        init_cloud_db()
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (name, phone, email, password, role)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                name=excluded.name,
                email=excluded.email,
                role=excluded.role
        """, (name, phone, email, "", role))
        conn.commit()
        conn.close()
        return {"name": name, "phone": phone, "email": email, "role": role}, None
    except Exception as e:
        print(f"[Local SignUp Fallback Error]: {e}")
        return None, "service_error"


def supabase_auth_signin(identifier, password):
    """Authenticate citizen user using Supabase Auth signInWithPassword().
    After login, retrieves the user's profile and role from public.users for role-based access.
    Returns (user_profile_dict, error_status).
    """
    ident = (identifier or "").strip()
    password = (password or "")

    if not ident or not password:
        return None, "invalid_credentials"

    if IS_VERCEL or is_supabase_enabled():
        if not is_supabase_enabled():
            log_safe_diagnostics()
            err_msg = "Supabase configuration missing on server (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required)."
            print(f"[Supabase Auth SignIn Error] {err_msg}")
            return None, err_msg

        try:
            email_to_auth = ident

            # If user entered 10-digit mobile number, resolve email from public.users
            if "@" not in ident:
                clean_phone = ident.strip()
                lookup_url = f"{SUPABASE_URL}/rest/v1/users?phone=eq.{clean_phone}&select=email"
                lookup_resp = requests.get(lookup_url, headers=get_supabase_headers(), timeout=6)
                if lookup_resp.status_code == 200 and lookup_resp.json():
                    email_to_auth = lookup_resp.json()[0].get("email", "")
                if not email_to_auth or "@" not in email_to_auth:
                    return None, "invalid_credentials"

            # Call Supabase Auth signInWithPassword() (GoTrue token endpoint)
            token_url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
            signin_payload = {
                "email": email_to_auth.lower(),
                "password": password
            }
            resp = requests.post(token_url, json=signin_payload, headers=get_supabase_auth_headers(), timeout=10)
            print(f"[Supabase Auth SignIn] HTTP Status: {resp.status_code}")

            if resp.status_code == 200:
                auth_data = resp.json() if resp.text else {}
                auth_user = auth_data.get("user") or {}
                auth_uid = auth_user.get("id")
                user_meta = auth_user.get("user_metadata") or {}

                # Retrieve user profile and role from public.users
                prof_url = f"{SUPABASE_URL}/rest/v1/users?email=ilike.{email_to_auth.lower()}"
                prof_resp = requests.get(prof_url, headers=get_supabase_headers(), timeout=6)
                user_row = None
                if prof_resp.status_code == 200 and prof_resp.json():
                    user_row = prof_resp.json()[0]

                if user_row:
                    user_profile = {
                        "id": user_row.get("id") or auth_uid,
                        "name": user_row.get("name") or user_meta.get("name", "Citizen"),
                        "phone": user_row.get("phone") or user_meta.get("phone", ""),
                        "email": user_row.get("email") or email_to_auth,
                        "role": user_row.get("role") or user_meta.get("role", "citizen")
                    }
                else:
                    user_profile = {
                        "id": auth_uid,
                        "name": user_meta.get("name", "Citizen"),
                        "phone": user_meta.get("phone", ""),
                        "email": email_to_auth,
                        "role": user_meta.get("role", "citizen")
                    }
                    try:
                        requests.post(f"{SUPABASE_URL}/rest/v1/users", json={
                            "name": user_profile["name"],
                            "phone": user_profile["phone"],
                            "email": user_profile["email"],
                            "password": "",
                            "role": user_profile["role"]
                        }, headers=get_supabase_headers(), timeout=4)
                    except Exception:
                        pass

                return user_profile, None

            else:
                err_data = resp.json() if resp.text else {}
                err_desc = err_data.get("error_description") or err_data.get("msg") or err_data.get("message") or ""
                print(f"[Supabase Auth SignIn Failed] HTTP {resp.status_code}: {err_desc}")
                if "confirm" in err_desc.lower():
                    return None, "email_not_confirmed"
                return None, "invalid_credentials"

        except Exception as e:
            print(f"[Supabase Auth SignIn Connection Error]: {e}")
            return None, "connection_error"

    # Local development fallback (when Supabase is unconfigured)
    print("[Local Dev Fallback] Authenticating with local SQLite...")
    try:
        init_cloud_db()
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(phone) = ? OR LOWER(email) = ?", (ident.lower(), ident.lower()))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row), None
        return None, "invalid_credentials"
    except Exception as e:
        print(f"[Local SignIn Fallback Error]: {e}")
        return None, "service_error"


def create_or_update_user(name, phone, email, password, role="citizen"):
    """Compatibility wrapper calling supabase_auth_signup."""
    user_prof, err = supabase_auth_signup(email, password, name, phone, role)
    return (True, None) if user_prof else (False, err)


def get_user_by_credentials(identifier, password):
    """Compatibility wrapper calling supabase_auth_signin."""
    return supabase_auth_signin(identifier, password)


def check_supabase_health():
    """Diagnose Supabase Auth and Database connection health without exposing secrets."""
    health = {
        "supabase_url_configured": bool(SUPABASE_URL),
        "supabase_key_configured": bool(SUPABASE_KEY),
        "supabase_service_role_configured": bool(SUPABASE_SERVICE_ROLE_KEY),
        "is_vercel": IS_VERCEL,
        "supabase_auth_enabled": is_supabase_enabled(),
        "auth_endpoint": None,
        "public_users_table": None,
        "recommendation": None
    }
    if not is_supabase_enabled():
        health["recommendation"] = "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not configured. If running locally, add them to .env. If on Vercel, set them in Project Settings -> Environment Variables."
        return health

    try:
        res = requests.get(f"{SUPABASE_URL}/auth/v1/settings", headers=get_supabase_headers(), timeout=5)
        health["auth_endpoint"] = {"status": res.status_code, "ok": res.status_code in (200, 204)}
    except Exception as e:
        health["auth_endpoint"] = {"status": None, "error": str(e)}

    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/users?select=count", headers=get_supabase_headers(), timeout=5)
        health["public_users_table"] = {"status": res.status_code, "ok": res.status_code in (200, 204, 206)}
        if res.status_code in (401, 403):
            health["public_users_table"]["error"] = "Row Level Security (RLS) is blocking access or key is not service_role key."
            health["recommendation"] = "Ensure you are using the secret service_role key (SUPABASE_SERVICE_ROLE_KEY) or disable RLS on public.users."
    except Exception as e:
        health["public_users_table"] = {"status": None, "error": str(e)}

    return health


def supabase_auth_reset_password(identifier, new_password):
    """Reset a citizen user's password in Supabase Auth (and local SQLite fallback).
    Accepts identifier as email address or 10-digit mobile number.
    Validates password complexity.
    Returns (success_boolean, message_string).
    """
    ident = str(identifier or "").strip()
    new_password = str(new_password or "")

    if not ident:
        return False, "Please enter your registered email address or 10-digit mobile number."

    if not new_password:
        return False, "Please enter a new password."

    # Validate password complexity (matches registration requirements)
    if (
        len(new_password) < 8
        or not re.search(r"[A-Z]", new_password)
        or not re.search(r"[a-z]", new_password)
        or not re.search(r"[0-9]", new_password)
        or not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", new_password)
    ):
        return False, "Password must be at least 8 characters and include uppercase, lowercase, number, and special character."

    if IS_VERCEL or is_supabase_enabled():
        if not is_supabase_enabled():
            return False, "Authentication service is currently unavailable. Please try again later."

        try:
            email_target = None
            auth_uid = None

            # 1. Resolve email if identifier is a mobile number
            if "@" not in ident:
                clean_phone = re.sub(r"\D", "", ident)
                if len(clean_phone) != 10:
                    return False, "Mobile number must contain exactly 10 digits."

                phone_url = f"{SUPABASE_URL}/rest/v1/users?phone=eq.{clean_phone}&select=id,email,name"
                phone_res = requests.get(phone_url, headers=get_supabase_headers(), timeout=6)
                if phone_res.status_code == 200 and phone_res.json():
                    row = phone_res.json()[0]
                    email_target = (row.get("email") or "").strip().lower()
                    row_id = str(row.get("id") or "")
                    if len(row_id) == 36 and row_id.count("-") == 4:
                        auth_uid = row_id
                else:
                    return False, f"No registered account found with mobile number {clean_phone}."
            else:
                email_target = ident.lower()

            if not email_target:
                return False, "Unable to determine the registered email address for this account."

            # 2. If auth_uid is not yet resolved, query public.users by email
            if not auth_uid:
                prof_url = f"{SUPABASE_URL}/rest/v1/users?email=ilike.{email_target}&select=id,email,name"
                prof_res = requests.get(prof_url, headers=get_supabase_headers(), timeout=6)
                if prof_res.status_code == 200 and prof_res.json():
                    row = prof_res.json()[0]
                    row_id = str(row.get("id") or "")
                    if len(row_id) == 36 and row_id.count("-") == 4:
                        auth_uid = row_id

            # 3. If auth_uid is still not known, search Supabase Auth Admin users list
            if not auth_uid:
                admin_users_url = f"{SUPABASE_URL}/auth/v1/admin/users?per_page=100"
                admin_res = requests.get(admin_users_url, headers=get_supabase_headers(), timeout=8)
                if admin_res.status_code == 200:
                    data = admin_res.json()
                    user_list = data.get("users", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for u in user_list:
                        if (u.get("email") or "").strip().lower() == email_target:
                            auth_uid = u.get("id")
                            break

            # 4. If user not found in Auth
            if not auth_uid:
                return False, f"No registered account found matching {ident}."

            # 5. Update password via Supabase Admin API
            update_url = f"{SUPABASE_URL}/auth/v1/admin/users/{auth_uid}"
            update_payload = {
                "password": new_password,
                "email_confirm": True
            }
            update_res = requests.put(update_url, json=update_payload, headers=get_supabase_headers(), timeout=10)
            print(f"[Supabase Auth Reset Password] User ID: {auth_uid}, Status: {update_res.status_code}")

            if update_res.status_code in (200, 204):
                # Clean up or sync public.users row
                try:
                    requests.patch(
                        f"{SUPABASE_URL}/rest/v1/users?email=ilike.{email_target}",
                        json={"password": ""},
                        headers=get_supabase_headers(),
                        timeout=5
                    )
                except Exception:
                    pass
                return True, "Your password has been successfully reset! You can now log in with your new password."
            else:
                err_json = update_res.json() if update_res.text else {}
                err_msg = err_json.get("msg") or err_json.get("message") or f"Supabase Auth error (HTTP {update_res.status_code})"
                print(f"[Supabase Auth Reset Password Error]: {err_msg}")
                return False, f"Password reset failed: {err_msg}"

        except Exception as e:
            print(f"[Supabase Auth Reset Password Exception]: {e}")
            return False, f"Error communicating with authentication service: {str(e)}"

    # Local development SQLite fallback (when offline)
    try:
        init_cloud_db()
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = ? OR phone = ?", (ident.lower(), ident))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, f"No registered account found with {ident}."

        hashed_pw = generate_password_hash(new_password)
        cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_pw, row["id"]))
        conn.commit()
        conn.close()
        return True, "Your password has been successfully reset! You can now log in with your new password."
    except Exception as e:
        print(f"[Local Reset Fallback Error]: {e}")
        return False, "Failed to update password in local database."
