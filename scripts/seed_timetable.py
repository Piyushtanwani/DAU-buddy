"""
Seed Timetable Script
=====================
Parses the active lecture timetable Excel file (Lecture_TT_Autumn2026-27_v9.xlsx)
and populates the timetables table with clean program batch mappings using curriculum.json.

Usage:
    python scripts/seed_timetable.py
"""
import os
import re
import sys
import json
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from core.database import db_connection

logger = config.get_logger("scripts.seed_timetable")

try:
    import openpyxl
except ImportError:
    logger.error("openpyxl not installed. Run: pip install openpyxl")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
POSSIBLE_PATHS = [
    os.path.join(DATA_DIR, "Lecture Data.xlsx"),
    os.path.join(DATA_DIR, "Lecture_TT_Autumn2026-27_v9.xlsx"),
]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

def find_excel_file() -> str:
    for path in POSSIBLE_PATHS:
        if os.path.exists(path):
            return path
    # Dynamic search for any Lecture*.xlsx in data/
    if os.path.exists(DATA_DIR):
        for f in os.listdir(DATA_DIR):
            if f.endswith(".xlsx") and "lecture" in f.lower():
                return os.path.join(DATA_DIR, f)
    raise FileNotFoundError(f"No timetable Excel file found in data/ folder ({DATA_DIR}).")

def load_curriculum():
    path = os.path.join(DATA_DIR, "curriculum.json")
    if not os.path.exists(path):
        logger.warning("curriculum.json not found. Run parse_curriculum.py first.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _parse_time(t) -> str | None:
    if not t:
        return None
    m = re.match(r"(\d{1,2}):(\d{2})", str(t))
    return f"{int(m.group(1)):02d}:{m.group(2)}:00" if m else None

def _resolve_slot(slot) -> tuple:
    if not slot:
        return None, None
    m = re.match(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", str(slot))
    if m:
        return _parse_time(m.group(1)), _parse_time(m.group(2))
    return None, None

def parse_excel(excel_path: str, curriculum: dict) -> list:
    wb = openpyxl.load_workbook(excel_path, data_only=True)

    # Abbreviation map: initials → full name
    abbrev_map = {}
    if "FacultyNameAbbreviations" in wb.sheetnames:
        for row in wb["FacultyNameAbbreviations"].iter_rows(min_row=2, values_only=True):
            if row[0] and row[1]:
                abbrev_map[str(row[1]).strip()] = str(row[0]).strip()

    sheet_name = "Lecture (Update)" if "Lecture (Update)" in wb.sheetnames else wb.sheetnames[0]
    all_rows = list(wb[sheet_name].iter_rows(values_only=True))

    header_idx = None
    day_cols = {}
    for i, row in enumerate(all_rows):
        if any(str(v).strip() in DAYS for v in row if v):
            header_idx = i
            break
    if header_idx is None:
        logger.error("Could not find day header row in Excel.")
        sys.exit(1)
    for ci, v in enumerate(all_rows[header_idx]):
        if v and str(v).strip() in DAYS:
            day_cols[str(v).strip()] = ci

    records = []
    cur_time = None
    
    for row in all_rows[header_idx + 1:]:
        t = row[0] if len(row) > 0 else None
        if t and str(t).strip():
            cur_time = str(t).strip()
        if not cur_time:
            continue

        start, end = _resolve_slot(cur_time)

        for day in DAYS:
            if day not in day_cols:
                continue
            dc = day_cols[day]
            course  = row[dc]     if len(row) > dc     else None
            faculty = row[dc + 1] if len(row) > dc + 1 else None
            room    = row[dc + 2] if len(row) > dc + 2 else None

            if not course:
                continue
            cs = str(course).strip()
            fs = str(faculty).strip() if faculty else ""
            rs = str(room).strip()    if room    else ""

            if not cs or cs in ("-", "—", "Course"):
                continue

            faculty_full = abbrev_map.get(fs, f"{fs} (unresolved)" if fs else "TBA")

            # Look up metadata from curriculum
            # The excel has course codes. Curriculum JSON has them as keys.
            meta_list = curriculum.get(cs, [])
            if not meta_list:
                meta_list = [{}]  # fallback for unknown courses
                
            for meta in meta_list:
                rec = {
                    "day": day,
                    "start": start,
                    "end": end,
                    "course_code": cs,
                    "course_name": meta.get("course_name", cs),
                    "course_type": meta.get("course_type", "Unknown"),
                    "program": meta.get("program", "Unknown Program"),
                    "semester": str(meta.get("semester", "")),
                    "faculty": faculty_full,
                    "room": rs,
                }
                records.append(rec)

    return records

def main():
    try:
        excel_path = find_excel_file()
        logger.info(f"Parsing active timetable from: {excel_path}")
        
        curriculum = load_curriculum()
        logger.info(f"Loaded {len(curriculum)} courses from curriculum.json")
        
        records = parse_excel(excel_path, curriculum)
        logger.info(f"Parsed {len(records)} timetable records.")

        with db_connection() as conn:
            with conn.cursor() as cur:
                # TRUNCATE existing timetables to keep only active timetable dataset
                cur.execute("TRUNCATE TABLE timetables;")
                logger.info("Cleared existing timetables table.")

                INSERT_SQL = """
                    INSERT INTO timetables
                        (session_type, course_code, course_name, course_type, program, semester, faculty_name,
                         day_of_week, start_time, end_time, room)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                counts = {}
                for rec in records:
                    prog = rec["program"]
                    cur.execute(INSERT_SQL, (
                        "Lecture",
                        rec["course_code"],
                        rec["course_name"],
                        rec["course_type"],
                        rec["program"],
                        rec["semester"] if rec["semester"] else None,
                        rec["faculty"],
                        rec["day"],
                        rec["start"],
                        rec["end"],
                        rec["room"]
                    ))
                    counts[prog] = counts.get(prog, 0) + 1

            conn.commit()

        logger.info("=== Timetable Seeded Successfully ===")
        for prog, n in sorted(counts.items()):
            logger.info(f"  {prog}: {n} rows")
        logger.info(f"Total inserted: {sum(counts.values())} records.")

    except Exception as e:
        logger.error(f"Failed to seed timetable data: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
