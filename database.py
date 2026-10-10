import sqlite3


def create_database():
    connection = sqlite3.connect("wastewatch.db")
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
    try:
        cursor.execute("ALTER TABLE reports ADD COLUMN reason TEXT")
    except Exception:
        pass

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

    connection.commit()
    connection.close()


if __name__ == "__main__":
    create_database()
    print("Database created successfully!")