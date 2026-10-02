import os
import sys
import csv
import psycopg2

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from core.utils.venue import normalize_venue_id

def seed_venues():
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "daiict_db")
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASSWORD", "root")

    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "room_capacity.csv")
    
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return False

    print("Seeding venues...")
    
    conn = psycopg2.connect(
        dbname=db_name, user=db_user, password=db_pass, host=db_host, port=db_port
    )
    conn.autocommit = True
    
    try:
        with conn.cursor() as cur:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                count = 0
                for row in reader:
                    # CSV might have "RoomID" and "Capacity"
                    venue_id = row.get("RoomID")
                    if not venue_id:
                        continue
                        
                    venue_id = normalize_venue_id(venue_id)
                        
                    capacity_str = row.get("Capacity", "0").strip()
                    if not capacity_str.isdigit():
                        continue
                        
                    capacity = int(capacity_str)
                    if capacity <= 0:
                        continue
                        
                    # Official Mapping
                    booking_poc = None
                    vid_upper = venue_id.upper()
                    if vid_upper.startswith("CEP"):
                        booking_poc = config.CEP_BOOKING_POC
                    elif "LAB" in vid_upper or "LT" in vid_upper:
                        booking_poc = config.LAB_LT_BOOKING_POC

                    cur.execute("""
                        INSERT INTO venues (venue_id, capacity, venue_type, booking_poc)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (venue_id) DO UPDATE SET
                            capacity = EXCLUDED.capacity,
                            venue_type = EXCLUDED.venue_type,
                            booking_poc = EXCLUDED.booking_poc
                    """, (venue_id, capacity, None, booking_poc))
                    
                    count += 1
                    
        print(f"Successfully seeded {count} venues.")
        return True
    except Exception as e:
        print(f"Error seeding venues: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    load_dotenv(dotenv_path=env_path, override=True)
    success = seed_venues()
    sys.exit(0 if success else 1)
