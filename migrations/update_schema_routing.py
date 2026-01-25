import sqlite3
import os

DB_PATH = "app.db"

def update_schema():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 1. Add status column
        print("Adding status column...")
        try:
            cursor.execute("ALTER TABLE agent_routing ADD COLUMN status VARCHAR DEFAULT 'active'")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("Column 'status' already exists.")
            else:
                raise e

        # 2. Relax NOT NULL constraints for user_id and phone_number_id
        # SQLite doesn't support ALTER COLUMN directly. We have to recreate the table.
        # This is a bit heavy but necessary for SQLite.

        print("Recreating table to relax constraints...")

        # Rename existing table
        cursor.execute("ALTER TABLE agent_routing RENAME TO agent_routing_old")

        # Create new table with nullable fields
        cursor.execute("""
            CREATE TABLE agent_routing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                agent_id VARCHAR NOT NULL,
                phone_number_id INTEGER,
                status VARCHAR DEFAULT 'active' NOT NULL,
                is_active BOOLEAN,
                created_at DATETIME,
                updated_at DATETIME,
                last_event_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(phone_number_id) REFERENCES phone_numbers(id)
            )
        """)

        # Copy data
        # We assume existing rows have data, and status='active' (default)
        cursor.execute("""
            INSERT INTO agent_routing (id, user_id, agent_id, phone_number_id, status, is_active, created_at, updated_at, last_event_at)
            SELECT id, user_id, agent_id, phone_number_id, IFNULL(status, 'active'), is_active, created_at, updated_at, last_event_at
            FROM agent_routing_old
        """)

        # Drop old table
        cursor.execute("DROP TABLE agent_routing_old")

        # Create index if needed? SQLAlchemy creates indexes.
        # SQLite usually preserves primary key index.
        # Let's verify indexes from models.py: id (PK), but models don't explicitly index FKs usually unless specified.
        # models.py says: id = Column(..., index=True)
        cursor.execute("CREATE INDEX ix_agent_routing_id ON agent_routing (id)")

        conn.commit()
        print("Schema update completed successfully.")

    except Exception as e:
        print(f"Error updating schema: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    update_schema()
