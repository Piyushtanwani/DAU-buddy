import sys
import os

# Ensure the project root is in the path so we can import core.database
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from core.database import db_connection
except ImportError:
    print("Error: Could not import core.database. Please run this script from within the project directory.")
    sys.exit(1)

def migrate_hm409(cur):
    print("--- Migrating HM409 ---")
    
    # 1. Fetch the rows to be moved (Mon/Wed 8 to 8:50) so we can insert them later at 4 to 5
    cur.execute("""
        SELECT * FROM timetables 
        WHERE course_code ILIKE '%HM409%'
          AND day_of_week IN ('Monday', 'Wednesday')
          AND start_time = '08:00:00'
          AND end_time = '08:50:00'
    """)
    rows_to_move = cur.fetchall()
    cols = [desc[0] for desc in cur.description]
    print(f"Found {len(rows_to_move)} rows for HM409 Monday/Wednesday 08:00 that will be moved to 16:00.")
    
    # 2. Delete HM409 from Mon/Wed/Fri 8 to 8:50
    cur.execute("""
        DELETE FROM timetables 
        WHERE course_code ILIKE '%HM409%'
          AND day_of_week IN ('Monday', 'Wednesday', 'Friday')
          AND start_time = '08:00:00'
          AND end_time = '08:50:00'
    """)
    print(f"Deleted {cur.rowcount} rows from 08:00-08:50 (Mon/Wed/Fri).")
    
    # 3. Insert the moved rows into Mon/Wed 4 to 5 (16:00 to 17:00)
    inserted = 0
    for row in rows_to_move:
        row_dict = dict(zip(cols, row))
        # Modify time
        row_dict['start_time'] = '16:00:00'
        row_dict['end_time'] = '17:00:00'
        
        # Filter out generated or auto-incrementing keys
        if 'id' in row_dict:
            del row_dict['id']
        if 'search_vector' in row_dict:
            del row_dict['search_vector']
            
        keys = list(row_dict.keys())
        values = list(row_dict.values())
        placeholders = ', '.join(['%s'] * len(values))
        columns_str = ', '.join(keys)
        
        insert_query = f"INSERT INTO timetables ({columns_str}) VALUES ({placeholders})"
        cur.execute(insert_query, values)
        inserted += 1
        
    print(f"Inserted {inserted} new rows for HM409 at 16:00-17:00.")
    
    # 4. Remove any remaining Friday HM409 slots (just in case they were at different times)
    cur.execute("DELETE FROM timetables WHERE course_code ILIKE '%HM409%' AND day_of_week = 'Friday'")
    print(f"Deleted {cur.rowcount} remaining Friday rows for HM409.\n")


def migrate_it586(cur):
    print("--- Migrating IT586 ---")
    
    # 1. Fetch the rows to be moved (Thu 9 to 11) so we can insert them later at Mon 12 to 2
    cur.execute("""
        SELECT * FROM timetables 
        WHERE course_code ILIKE '%IT586%'
          AND day_of_week = 'Thursday'
          AND start_time = '09:00:00'
          AND end_time = '11:00:00'
    """)
    rows_to_move = cur.fetchall()
    cols = [desc[0] for desc in cur.description]
    print(f"Found {len(rows_to_move)} rows for IT586 Thursday 09:00 that will be moved to Monday 12:00.")
    
    # 2. Delete IT586 from Thursday 9 to 11
    cur.execute("""
        DELETE FROM timetables 
        WHERE course_code ILIKE '%IT586%'
          AND day_of_week = 'Thursday'
          AND start_time = '09:00:00'
          AND end_time = '11:00:00'
    """)
    print(f"Deleted {cur.rowcount} rows from 09:00-11:00 on Thursday.")
    
    # 3. Insert the moved rows into Monday 12 to 2 (12:00 to 14:00)
    inserted = 0
    for row in rows_to_move:
        row_dict = dict(zip(cols, row))
        # Modify day and time
        row_dict['day_of_week'] = 'Monday'
        row_dict['start_time'] = '12:00:00'
        row_dict['end_time'] = '14:00:00'
        
        # Filter out generated or auto-incrementing keys
        if 'id' in row_dict:
            del row_dict['id']
        if 'search_vector' in row_dict:
            del row_dict['search_vector']
            
        keys = list(row_dict.keys())
        values = list(row_dict.values())
        placeholders = ', '.join(['%s'] * len(values))
        columns_str = ', '.join(keys)
        
        insert_query = f"INSERT INTO timetables ({columns_str}) VALUES ({placeholders})"
        cur.execute(insert_query, values)
        inserted += 1
        
    print(f"Inserted {inserted} new rows for IT586 on Monday 12:00-14:00.\n")


if __name__ == "__main__":
    print("Starting timetable database migrations...")
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                migrate_hm409(cur)
                migrate_it586(cur)
            conn.commit()
            print("All changes committed to the database successfully.")
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
