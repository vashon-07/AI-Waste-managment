import os
import sqlite3
import requests
from cloud_db import SUPABASE_URL, SUPABASE_KEY, is_supabase_enabled, get_supabase_headers

def migrate():
    if not is_supabase_enabled():
        print("ERROR: Supabase is not configured yet!")
        print("Please set SUPABASE_URL and SUPABASE_KEY in your .env file first.")
        return

    local_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wastewatch.db")
    if not os.path.exists(local_db):
        print(f"Local database not found at {local_db}")
        return

    conn = sqlite3.connect(local_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    print(f"Found {len(rows)} local reports to migrate to Supabase...")

    success_count = 0
    headers = get_supabase_headers()
    url = f"{SUPABASE_URL}/rest/v1/reports"

    for r in rows:
        payload = {
            "reporter_name": r["reporter_name"] or "Anonymous Citizen",
            "reporter_phone": r["reporter_phone"] or "",
            "image_path": r["image_path"] or "",
            "description": r["description"] or "",
            "latitude": float(r["latitude"]) if r["latitude"] else 17.6868,
            "longitude": float(r["longitude"]) if r["longitude"] else 83.2185,
            "address": r["address"] or "",
            "waste_type": r["waste_type"] or "Mixed Municipal",
            "raw_label": r["raw_label"] or "",
            "severity": r["severity"] or "Medium",
            "priority_score": float(r["priority_score"]) if r["priority_score"] else 50.0,
            "status": r["status"] or "Pending",
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                success_count += 1
            else:
                print(f"Failed row {r['id']}: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Error on row {r['id']}: {e}")

    print(f"Successfully migrated {success_count}/{len(rows)} reports to Supabase!")

if __name__ == "__main__":
    migrate()
