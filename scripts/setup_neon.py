import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import db_connection

def setup_db():
    sql_path = os.path.join(os.path.dirname(__file__), "init_db.sql")
    with open(sql_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Skip the CREATE DATABASE and \connect commands
    sql_to_run = "".join(line for line in lines[16:] if not line.strip().startswith("\\"))
    
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_to_run)
            print("Neon Database setup complete.")

if __name__ == "__main__":
    setup_db()
