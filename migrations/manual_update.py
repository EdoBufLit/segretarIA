import sqlite3
import os

DB_PATH = "app.db"

def run_migration():
    if not os.path.exists(DB_PATH):
        print("Database not found, skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Add notes column
    try:
        cursor.execute("ALTER TABLE phone_numbers ADD COLUMN notes VARCHAR")
        print("Added 'notes' column.")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print("'notes' column already exists.")
        else:
            print(f"Error adding 'notes' column: {e}")

    # Handling user_id nullable in SQLite is complex (requires table recreation).
    # We will assume for now that if we insert, we MUST provide a user_id if the constraint exists.
    # If we really need it nullable, we'd do:
    # 1. Rename table
    # 2. Create new table with nullable user_id
    # 3. Copy data
    # 4. Drop old table

    # Let's try to be robust. If user_id is required, our app logic must handle it.

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run_migration()
