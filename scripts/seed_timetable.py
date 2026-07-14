import pandas as pd
import sys
import os
import psycopg2
import psycopg2.extras
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from core.database import db_connection

logger = config.get_logger("scripts.seed_timetable")

def load_faculty_mapping():
    mapping_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "faculty mapping.csv")
    if not os.path.exists(mapping_path):
        logger.warning(f"Faculty mapping file not found at {mapping_path}. Proceeding without mapping.")
        return {}
        
    try:
        df = pd.read_csv(mapping_path)
        mapping = {}
        for _, row in df.iterrows():
            if pd.notna(row['Acronym']) and pd.notna(row['Faculty Name']):
                acronym = str(row['Acronym']).strip()
                name = str(row['Faculty Name']).strip()
                mapping[acronym] = name
        return mapping
    except Exception as e:
        logger.error(f"Error loading faculty mapping: {e}")
        return {}

def resolve_faculty(faculty_str, mapping):
    if not faculty_str or not isinstance(faculty_str, str):
        return ""
    
    parts = [p.strip() for p in faculty_str.split(',')]
    resolved_parts = []
    for p in parts:
        if not p:
            continue
        resolved_parts.append(mapping.get(p, p))
        
    return ", ".join(resolved_parts)

def parse_time(time_str):
    if not isinstance(time_str, str):
        return None, None
    parts = time_str.split('-')
    if len(parts) == 2:
        try:
            start = pd.to_datetime(parts[0].strip()).strftime('%H:%M:%S')
            end = pd.to_datetime(parts[1].strip()).strftime('%H:%M:%S')
            return start, end
        except Exception:
            return None, None
    return None, None

def seed_lectures(conn, faculty_mapping):
    file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "Lecture Data.xlsx")
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return
        
    df = pd.read_excel(file_path, header=None)
    records = []
    
    # Days are at columns: 3(Mon), 10(Tue), 17(Wed), 24(Thu), 31(Fri)
    day_offsets = {
        'Monday': 3,
        'Tuesday': 10,
        'Wednesday': 17,
        'Thursday': 24,
        'Friday': 31
    }
    
    invalid_codes = {
        "Slot-1", "Slot-2", "Slot-3", "Slot-4",
        "Slot-5", "Slot-6", "Slot-7", "Slot-8",
        "Free-Slot"
    }
    
    current_time_slot = None
    current_batch = None
    
    for i, row in df.iterrows():
        if i < 4: # Skip headers
            continue
            
        time_slot = row[0]
        if pd.notna(time_slot) and isinstance(time_slot, str) and '-' in time_slot:
            current_time_slot = time_slot
            
        if not current_time_slot:
            continue
            
        start_time, end_time = parse_time(current_time_slot)
        if not start_time:
            continue
            
        if pd.notna(row[1]):
            current_batch = str(row[1]).strip()
        batch = current_batch
        
        for day, offset in day_offsets.items():
            if offset >= len(row):
                continue
                
            course_code = row.get(offset)
            if pd.notna(course_code) and isinstance(course_code, str):
                course_code = course_code.strip()
                if course_code in invalid_codes:
                    continue
                    
                course_name = row[offset+1] if offset+1 < len(row) and pd.notna(row[offset+1]) else ""
                faculty = row[offset+4] if offset+4 < len(row) and pd.notna(row[offset+4]) else ""
                faculty = resolve_faculty(faculty, faculty_mapping)
                room = row[offset+5] if offset+5 < len(row) and pd.notna(row[offset+5]) else ""
                
                records.append((
                    'Lecture', course_code, course_name, faculty, day, start_time, end_time, room, str(batch) if pd.notna(batch) else None
                ))
                
    if records:
        insert_query = """
            INSERT INTO timetables (
                session_type, course_code, course_name, faculty_name, day_of_week, start_time, end_time, location, batch_group
            ) VALUES %s
        """
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, insert_query, records, page_size=1000)
        logger.info(f"Inserted {len(records)} lecture records.")

def seed_labs(conn, faculty_mapping):
    file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "Lab Data.xlsx")
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return
        
    df = pd.read_excel(file_path, header=None)
    records = []
    
    for i, row in df.iterrows():
        if i < 4:
            continue
            
        time_slot = row[0]
        # Sometimes time slot is NaN, we skip unless we track current time. In labs, time slot seems provided per row.
        if not pd.notna(time_slot) or not isinstance(time_slot, str) or '-' not in time_slot:
            continue
            
        start_time, end_time = parse_time(time_slot)
        if not start_time:
            continue
            
        location = row[6] if pd.notna(row[6]) else ""
        course_code = row[7] if pd.notna(row[7]) else ""
        faculty = row[8] if pd.notna(row[8]) else ""
        faculty = resolve_faculty(faculty, faculty_mapping)
        
        days = {
            1: 'Monday',
            2: 'Tuesday',
            3: 'Wednesday',
            4: 'Thursday',
            5: 'Friday'
        }
        
        for col_idx, day in days.items():
            batch = row[col_idx]
            if pd.notna(batch) and isinstance(batch, str):
                records.append((
                    'Lab', course_code, "", faculty, day, start_time, end_time, location, batch
                ))

    if records:
        insert_query = """
            INSERT INTO timetables (
                session_type, course_code, course_name, faculty_name, day_of_week, start_time, end_time, location, batch_group
            ) VALUES %s
        """
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, insert_query, records, page_size=1000)
        logger.info(f"Inserted {len(records)} lab records.")

def main():
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                # Create table if it doesn't exist
                create_table_query = """
                CREATE TABLE IF NOT EXISTS timetables (
                    id             SERIAL PRIMARY KEY,
                    session_type   VARCHAR(50),
                    course_code    VARCHAR(100),
                    course_name    VARCHAR(255),
                    faculty_name   VARCHAR(255),
                    day_of_week    VARCHAR(20),
                    start_time     TIME,
                    end_time       TIME,
                    location       VARCHAR(255),
                    batch_group    VARCHAR(50),
                    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                ALTER TABLE timetables
                    ADD COLUMN IF NOT EXISTS search_vector tsvector
                    GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', coalesce(course_code, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(course_name, '')), 'B') ||
                        setweight(to_tsvector('english', coalesce(faculty_name, '')), 'C') ||
                        setweight(to_tsvector('english', coalesce(location, '')), 'D')
                    ) STORED;

                CREATE INDEX IF NOT EXISTS idx_timetables_search_vector ON timetables USING GIN (search_vector);
                CREATE INDEX IF NOT EXISTS idx_timetables_faculty ON timetables (faculty_name, day_of_week);
                CREATE INDEX IF NOT EXISTS idx_timetables_course ON timetables (course_code, day_of_week);
                """
                cur.execute(create_table_query)
                logger.info("Checked/Created timetables table.")

                # Clear existing timetables
                cur.execute("TRUNCATE TABLE timetables;")
                logger.info("Cleared existing timetables.")
            
            faculty_mapping = load_faculty_mapping()
            seed_lectures(conn, faculty_mapping)
            seed_labs(conn, faculty_mapping)
            
        logger.info("Successfully seeded all timetable data.")
    except Exception as e:
        logger.error(f"Failed to seed timetable data: {e}")

if __name__ == "__main__":
    main()
