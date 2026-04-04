import sqlite3
import os

DB_PATH = os.path.expanduser("~/.data-engine/leads.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("ALTER TABLE leads ADD COLUMN campaign_week TEXT;")
        print("Added campaign_week column")
    except sqlite3.OperationalError:
        print("campaign_week column already exists")
    
    try:
        conn.execute("ALTER TABLE leads ADD COLUMN outreach_status TEXT DEFAULT 'pending';")
        print("Added outreach_status column")
    except sqlite3.OperationalError:
        print("outreach_status column already exists")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
