import sqlite3
import os

DB_PATH = "app.db"

def update_schema_phonenumbers():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("Recreating phone_numbers table to relax user_id constraint...")

        # Rename existing table
        cursor.execute("ALTER TABLE phone_numbers RENAME TO phone_numbers_old")

        # Create new table with nullable user_id
        cursor.execute("""
            CREATE TABLE phone_numbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                e164 VARCHAR NOT NULL,
                provider VARCHAR NOT NULL DEFAULT 'ehiweb',
                monthly_cost_cents INTEGER NOT NULL DEFAULT 200,
                status VARCHAR NOT NULL DEFAULT 'active',
                notes VARCHAR,
                deprovision_at DATETIME,
                released_at DATETIME,
                notified_at DATETIME,
                user_id INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Copy data
        # Note: We need to handle cases where user_id might be NULL in source if we were coming from a nullable schema,
        # but here we come from NOT NULL so it's fine.
        cursor.execute("""
            INSERT INTO phone_numbers (id, e164, provider, monthly_cost_cents, status, notes, deprovision_at, released_at, notified_at, user_id, created_at, updated_at)
            SELECT id, e164, provider, monthly_cost_cents, status, notes, deprovision_at, released_at, notified_at, user_id, created_at, updated_at
            FROM phone_numbers_old
        """)

        # Drop old table
        cursor.execute("DROP TABLE phone_numbers_old")

        # Recreate indexes
        cursor.execute("CREATE INDEX ix_phone_numbers_id ON phone_numbers (id)")
        cursor.execute("CREATE UNIQUE INDEX ix_phone_numbers_e164 ON phone_numbers (e164)")

        conn.commit()
        print("PhoneNumbers schema update completed successfully.")

    except Exception as e:
        print(f"Error updating phone_numbers schema: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    update_schema_phonenumbers()
