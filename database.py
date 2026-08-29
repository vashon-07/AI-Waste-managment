import sqlite3

def create_database():
    connection = sqlite3.connect("wastewatch.db")

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


if __name__ == "__main__":
    create_database()
    print("Database created successfully!")